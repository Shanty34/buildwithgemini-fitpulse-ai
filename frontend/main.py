"""FastAPI proxy for a deployed agent (Agent Runtime, ADK / A2A).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over A2A or ADK streamQuery, returning
replies as structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Run:
  pip install -r requirements.txt
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import base64
import json
import os
import re
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

REASONING_ENGINE_BASE = f"https://{LOCATION}-aiplatform.googleapis.com/v1/{RESOURCE}"

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP passthrough.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE context / session ID per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}
_adk_sessions: dict[str, str] = {}
_card: AgentCard | None = None
_mode: str | None = None  # "a2a" or "adk"


async def _get_a2a_card(client: httpx.AsyncClient) -> AgentCard | None:
    global _card
    if _card is not None:
        return _card
    try:
        resp = await client.get(A2A_CARD_URL)
        if resp.status_code == 200:
            card = AgentCard(**resp.json())
            card.url = A2A_BASE
            _card = card
            return _card
    except Exception:
        pass
    return None


def _extract_a2a_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, TextPart) and getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "data", None) is not None:
            meta = getattr(root, "metadata", None) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else None
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": root.data})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


def _parse_inline_a2ui(data_b64: str) -> dict | None:
    try:
        pad = len(data_b64) % 4
        if pad:
            data_b64 += "=" * (4 - pad)
        raw_bytes = base64.b64decode(data_b64)
        raw_str = raw_bytes.decode("utf-8")
        m = re.search(r"<a2a_datapart_json>(.*?)</a2a_datapart_json>", raw_str, re.DOTALL)
        if m:
            inner_json = json.loads(m.group(1))
            return inner_json.get("data")
    except Exception:
        pass
    return None


@app.post("/chat")
async def chat(req: Request):
    global _mode
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    headers = _auth_headers()
    async with httpx.AsyncClient(headers=headers, timeout=120) as client:
        if _mode is None or _mode == "a2a":
            card = await _get_a2a_card(client)
            if card is not None:
                _mode = "a2a"
                factory = ClientFactory(
                    ClientConfig(
                        supported_transports=[
                            TransportProtocol.jsonrpc,
                            TransportProtocol.http_json,
                        ],
                        httpx_client=client,
                    )
                )
                a2a_client = factory.create(card)

                msg = Message(
                    message_id=str(uuid.uuid4()),
                    role=Role.user,
                    parts=[Part(root=TextPart(text=message))],
                    context_id=_contexts.get(user_id),
                )

                last_task = None
                got_artifact_update = False
                async for event in a2a_client.send_message(msg):
                    if not isinstance(event, tuple):
                        continue
                    task, update = event
                    if task is not None:
                        last_task = task
                        if getattr(task, "context_id", None):
                            _contexts[user_id] = task.context_id
                    if isinstance(update, TaskArtifactUpdateEvent):
                        got_artifact_update = True
                        parts.extend(_extract_a2a_parts(update.artifact.parts))

                if not got_artifact_update and last_task is not None:
                    for artifact in getattr(last_task, "artifacts", None) or []:
                        parts.extend(_extract_a2a_parts(artifact.parts))

                if parts:
                    return JSONResponse({"parts": parts})

        # ADK Reasoning Engine mode (:streamQuery)
        _mode = "adk"
        session_id = _adk_sessions.get(user_id)
        if not session_id:
            sess_resp = await client.post(
                f"{REASONING_ENGINE_BASE}:query",
                json={"class_method": "async_create_session", "input": {"user_id": user_id}},
            )
            sess_resp.raise_for_status()
            session_id = sess_resp.json().get("output", {}).get("id")
            _adk_sessions[user_id] = session_id

        stream_url = f"{REASONING_ENGINE_BASE}:streamQuery"
        payload = {
            "class_method": "async_stream_query",
            "input": {
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
            },
        }

        async with client.stream("POST", stream_url, json=payload) as stream_resp:
            stream_resp.raise_for_status()
            async for line in stream_resp.aiter_lines():
                if not line or not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    content = event.get("content") or {}
                    for p in content.get("parts") or []:
                        if "text" in p and p["text"]:
                            parts.append({"kind": "text", "text": p["text"]})
                        elif "inline_data" in p:
                            a2ui_data = _parse_inline_a2ui(p["inline_data"].get("data", ""))
                            if a2ui_data:
                                parts.append({"kind": "a2ui", "data": a2ui_data})
                except json.JSONDecodeError:
                    continue

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


# Serve the chat UI (keep this mount last so /chat wins).
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
