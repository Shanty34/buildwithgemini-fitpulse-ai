# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import firestore
from google.cloud import storage
from google.genai import types

from .a2ui_utils import a2ui_callback


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback to extract durable user facts and preferences to Vertex AI Memory Bank."""
    await callback_context.add_session_to_memory()
    return None


def log_workout(
    workout_type: str,
    duration_minutes: int,
    calories_burned: int,
    notes: str = "",
    muscle_groups: str = "",
    exercises: str = "",
) -> str:
    """Logs a completed workout session including target muscle groups and exercises.

    Args:
        workout_type: Type of exercise (e.g. running, strength, cycling, swimming, yoga).
        duration_minutes: Duration of the workout in minutes.
        calories_burned: Estimated calories burned.
        notes: Optional extra details or notes about the session.
        muscle_groups: Target muscle groups trained (e.g. chest, back, legs, shoulders, arms, core).
        exercises: Specific exercises performed (e.g. Bench Press, Squats, Pull-ups).

    Returns:
        Confirmation message with logged details.
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    details = (
        f"✅ Workout logged successfully at {now_str}!\n"
        f"- Type: {workout_type.title()}\n"
        f"- Duration: {duration_minutes} mins\n"
        f"- Calories: {calories_burned} kcal\n"
    )
    if muscle_groups:
        details += f"- Muscle Groups: {muscle_groups.title()}\n"
    if exercises:
        details += f"- Exercises: {exercises}\n"
    if notes:
        details += f"- Notes: {notes}\n"
    return details.strip()


def get_workout_plan(fitness_goal: str, days_per_week: int = 4) -> str:
    """Generates a structured multi-day workout plan based on fitness goals.

    Args:
        fitness_goal: Primary goal (e.g. strength, weight loss, endurance, hypertrophy).
        days_per_week: Number of workout days per week (default 4).

    Returns:
        A formatted workout plan breakdown.
    """
    goal_lower = fitness_goal.lower()
    if "strength" in goal_lower or "muscle" in goal_lower or "hypertrophy" in goal_lower:
        plan = (
            f"💪 **{days_per_week}-Day Strength & Muscle Plan**:\n"
            "- Day 1: Upper Body Heavy (Chest: Bench Press | Back: Bent Rows | Shoulders: Overhead Press)\n"
            "- Day 2: Lower Body Heavy (Legs: Squats, Romanian Deadlifts | Calves, Core)\n"
            "- Day 3: Rest & Active Recovery / Light Cardio\n"
            "- Day 4: Upper Body Hypertrophy (Chest: Incline DB Press | Back: Lat Pulldown | Shoulders: Lateral Raises)\n"
        )
        if days_per_week >= 5:
            plan += "- Day 5: Lower Body & Core (Legs: Leg Press, Hamstring Curls, Lunges)\n"
    elif "endurance" in goal_lower or "run" in goal_lower or "cardio" in goal_lower:
        plan = (
            f"🏃 **{days_per_week}-Day Endurance & Running Plan**:\n"
            "- Day 1: Easy Aerobic Run (Zone 2, 45 mins)\n"
            "- Day 2: Interval Speed Work (8x400m repeats with 90s rest)\n"
            "- Day 3: Cross-Training / Swimming / Mobility\n"
            "- Day 4: Long Distance Run (Zone 2, 60-90 mins)\n"
        )
        if days_per_week >= 5:
            plan += "- Day 5: Tempo Run (20 mins at threshold pace)\n"
    else:
        plan = (
            f"⚡ **{days_per_week}-Day General Fitness & Conditioning Plan**:\n"
            "- Day 1: Full Body Compound Circuit\n"
            "- Day 2: Zone 2 Steady Cardio (40 mins)\n"
            "- Day 3: Rest & Yoga / Mobility\n"
            "- Day 4: High-Intensity Interval Training (HIIT 25 mins)\n"
        )
    return plan


def calculate_training_zones(max_hr: int, resting_hr: int = 60) -> str:
    """Calculates Karvonen Target Heart Rate training zones.

    Args:
        max_hr: Maximum heart rate in BPM (beats per minute).
        resting_hr: Resting heart rate in BPM (default 60).

    Returns:
        Formatted summary of heart rate zones 1 through 5.
    """
    hrr = max_hr - resting_hr
    z1_low, z1_high = int(resting_hr + hrr * 0.50), int(resting_hr + hrr * 0.60)
    z2_low, z2_high = int(resting_hr + hrr * 0.60), int(resting_hr + hrr * 0.70)
    z3_low, z3_high = int(resting_hr + hrr * 0.70), int(resting_hr + hrr * 0.80)
    z4_low, z4_high = int(resting_hr + hrr * 0.80), int(resting_hr + hrr * 0.90)
    z5_low, z5_high = int(resting_hr + hrr * 0.90), max_hr

    return (
        f"📊 **Target Heart Rate Zones (Max HR: {max_hr} BPM, Resting: {resting_hr} BPM)**:\n"
        f"- Zone 1 (Active Recovery 50-60%): {z1_low} - {z1_high} BPM\n"
        f"- Zone 2 (Aerobic Base 60-70%): {z2_low} - {z2_high} BPM\n"
        f"- Zone 3 (Tempo / Endurance 70-80%): {z3_low} - {z3_high} BPM\n"
        f"- Zone 4 (Threshold 80-90%): {z4_low} - {z4_high} BPM\n"
        f"- Zone 5 (Anaerobic / Max Effort 90-100%): {z5_low} - {z5_high} BPM"
    )


def query_workout_history(query: str = "") -> str:
    """Queries recent workout logs and progress metrics.

    Args:
        query: Specific search term or metric (e.g. 'running', 'this week', 'total volume').

    Returns:
        Summary of recent workout history.
    """
    return (
        "📜 **Recent Workout History Summary**:\n"
        "- 2026-09-20: Running (5.2 km, 28 mins, 340 kcal)\n"
        "- 2026-09-18: Strength Training - Chest & Triceps (Bench Press, Incline DB Flyes, Tricep Dips - 45 mins)\n"
        "- 2026-09-16: Swimming - Laps (30 mins, 250 kcal)\n"
        "Total active minutes this week: 103 mins | Total calories burned: 870 kcal"
    )


# Removed inline firestore import
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-39fe799c3cd6"
WORKOUTS_COLLECTION = "workouts"
GCS_BUCKET_NAME = "fitpulse-ai-media-39fe799c"


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client with hardcoded project ID for Agent Platform compatibility."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def save_workout_routine_to_firestore(
    title: str,
    workout_type: str,
    muscle_groups: str,
    duration_minutes: int,
    calories_burned: int,
    exercises_summary: str = "",
    difficulty: str = "Intermediate",
    low_impact: bool = True,
    notes: str = "",
) -> str:
    """Saves a new workout routine to the Firestore database.

    Args:
        title: Title of the workout routine (e.g. 'Upper Body Power Routine').
        workout_type: Type of exercise (e.g. Strength, Endurance, HIIT, Mobility).
        muscle_groups: Comma-separated target muscle groups (e.g. 'Chest, Triceps, Shoulders').
        duration_minutes: Estimated duration in minutes.
        calories_burned: Estimated calories burned.
        exercises_summary: Summary list of exercises included in the routine.
        difficulty: Difficulty level ('Beginner', 'Intermediate', 'Advanced').
        low_impact: Whether the routine is low-impact / joint-friendly (default True).
        notes: Optional additional notes or tips.

    Returns:
        Confirmation message with saved document ID.
    """
    db = get_firestore_client()
    doc_id = title.lower().replace(" ", "_").replace("&", "and")
    doc_id = "".join(c for c in doc_id if c.isalnum() or c in ("_", "-"))

    muscle_list = [m.strip().title() for m in muscle_groups.split(",") if m.strip()]
    doc_data = {
        "workout_id": doc_id,
        "title": title,
        "workout_type": workout_type.title(),
        "muscle_groups": muscle_list,
        "difficulty": difficulty.title(),
        "duration_minutes": duration_minutes,
        "calories_burned": calories_burned,
        "exercises": exercises_summary,
        "low_impact": low_impact,
        "notes": notes,
        "created_at": datetime.datetime.now().isoformat(),
    }
    db.collection(WORKOUTS_COLLECTION).document(doc_id).set(doc_data)
    return (
        f"🔥 Workout routine '{title}' saved to Firestore backend!\n"
        f"- Document ID: {doc_id}\n"
        f"- Muscle Groups: {', '.join(muscle_list)}\n"
        f"- Duration: {duration_minutes} mins | Calories: {calories_burned} kcal"
    )


def search_workout_routines_from_firestore(
    muscle_group: str = "",
    workout_type: str = "",
    low_impact_only: bool = False,
) -> str:
    """Queries curated workout routines from the Firestore database.

    Args:
        muscle_group: Target muscle group filter (e.g. 'Chest', 'Legs', 'Back').
        workout_type: Workout type filter (e.g. 'Strength', 'Endurance', 'HIIT').
        low_impact_only: Filter for joint-friendly / low-impact routines only.

    Returns:
        Formatted summary of matching workout routines found in Firestore.
    """
    db = get_firestore_client()
    query_ref = db.collection(WORKOUTS_COLLECTION)
    docs = list(query_ref.stream())

    matching = []
    m_lower = muscle_group.lower().strip()
    t_lower = workout_type.lower().strip()

    for doc in docs:
        d = doc.to_dict()
        doc_muscles = [m.lower() for m in d.get("muscle_groups", [])]
        doc_type = d.get("workout_type", "").lower()
        is_low_impact = d.get("low_impact", False)

        if m_lower and not any(m_lower in m for m in doc_muscles):
            continue
        if t_lower and t_lower not in doc_type:
            continue
        if low_impact_only and not is_low_impact:
            continue

        matching.append(d)

    if not matching:
        return f"No workout routines matching criteria (Muscle: '{muscle_group}', Type: '{workout_type}') found in Firestore database."

    output = f"📚 **Found {len(matching)} Workout Routine(s) in Firestore**:\n"
    for r in matching:
        output += (
            f"\n🏋️ **{r.get('title')}** (ID: {r.get('workout_id')})\n"
            f"- Type: {r.get('workout_type')} | Difficulty: {r.get('difficulty')}\n"
            f"- Muscle Groups: {', '.join(r.get('muscle_groups', []))}\n"
            f"- Duration: {r.get('duration_minutes')} mins | Calories: {r.get('calories_burned')} kcal\n"
            f"- Low Impact: {'Yes ✅' if r.get('low_impact') else 'No'}\n"
            f"- Notes: {r.get('notes', 'N/A')}\n"
        )
    return output.strip()


def calculate_1rm_and_volume(weight_kg: float, reps: int, sets: int = 1) -> str:
    """Calculates estimated 1-Rep Max (1RM) using Epley formula and total workload tonnage.

    Args:
        weight_kg: Weight lifted in kilograms.
        reps: Number of repetitions performed per set.
        sets: Number of sets completed (default 1).

    Returns:
        Formatted summary of estimated 1RM, percentage load targets, and total volume.
    """
    if reps <= 0 or weight_kg <= 0:
        return "Please provide positive values for weight and reps."

    one_rm = round(weight_kg * (1 + reps / 30.0), 1)
    total_volume = round(weight_kg * reps * sets, 1)

    pct_90 = round(one_rm * 0.90, 1)
    pct_80 = round(one_rm * 0.80, 1)
    pct_70 = round(one_rm * 0.70, 1)

    return (
        f"🏋️ **1-Rep Max (1RM) & Workload Analysis**:\n"
        f"- Weight Lifted: {weight_kg} kg x {reps} reps ({sets} set{'s' if sets > 1 else ''})\n"
        f"- Estimated 1RM: **{one_rm} kg**\n"
        f"- Total Workload Tonnage: **{total_volume} kg**\n"
        f"📊 **Training Intensity Targets**:\n"
        f"  • Heavy Strength (90% 1RM): ~{pct_90} kg (3-5 reps)\n"
        f"  • Hypertrophy (80% 1RM): ~{pct_80} kg (8-10 reps)\n"
        f"  • Endurance / Speed (70% 1RM): ~{pct_70} kg (12-15 reps)"
    )


def fetch_fitness_nutrition_info(food_item: str) -> str:
    """Fetches real post-workout nutritional data (calories, protein, carbs, fat) from a public REST API.

    Args:
        food_item: Name of the fruit or recovery snack (e.g. 'banana', 'apple', 'orange', 'strawberry').

    Returns:
        Formatted summary of nutritional macros per 100g serving.
    """
    api_key = os.environ.get("NINJA_API_KEY") or os.environ.get("EXERCISE_API_KEY")
    item_clean = food_item.strip().lower()

    if api_key:
        try:
            url = f"https://api.api-ninjas.com/v1/nutrition?query={urllib.parse.quote(item_clean)}"
            req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    item = data[0]
                    name = item.get("name", item_clean).title()
                    cals = item.get("calories")
                    prot = item.get("protein_g")
                    carbs = item.get("carbohydrates_total_g")
                    fat = item.get("fat_total_g")
                    return (
                        f"🥗 **Nutritional Profile for {name}**:\n"
                        f"- Calories: {cals} kcal\n"
                        f"- Protein: {prot} g\n"
                        f"- Carbohydrates: {carbs} g\n"
                        f"- Total Fat: {fat} g"
                    )
        except Exception:
            pass

    try:
        url = f"https://www.fruityvice.com/api/fruit/{urllib.parse.quote(item_clean)}"
        req = urllib.request.Request(url, headers={"User-Agent": "FitPulseAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            nutr = data.get("nutritions", {})
            name = data.get("name", item_clean.title())
            cals = nutr.get("calories")
            prot = nutr.get("protein")
            carbs = nutr.get("carbohydrates")
            fat = nutr.get("fat")
            sugar = nutr.get("sugar")
            return (
                f"🍌 **Post-Workout Recovery Nutrition ({name})** per 100g:\n"
                f"- Calories: {cals} kcal\n"
                f"- Protein: {prot} g\n"
                f"- Carbohydrates: {carbs} g\n"
                f"- Total Fat: {fat} g\n"
                f"- Sugar: {sugar} g"
            )
    except Exception as e:
        return f"Unable to fetch nutrition info for '{food_item}': {e}"


def consult_exercise_guide(query: str) -> str:
    """Consults the indexed exercise benefits guide for detailed physiological benefits, targeted muscle activation, joint impact, and form safety cues.

    Args:
        query: Specific exercise, muscle group, or physiological benefit to look up (e.g. 'Romanian Deadlifts', 'chest exercises', 'joint safety for squats').

    Returns:
        Relevant knowledge excerpts retrieved from the exercise benefits corpus.
    """
    try:
        client = discoveryengine.SearchServiceClient()
        serving_config = "projects/qwiklabs-gcp-01-39fe799c3cd6/locations/global/collections/default_collection/dataStores/fitpulse-exercise-benefits/servingConfigs/default_search"
        req = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=3,
        )
        res = client.search(req)
        passages = []
        for r in res.results:
            data = dict(r.document.struct_data)
            title = data.get("title", "")
            text = data.get("text", "")
            if text:
                passages.append(f"### {title}\n{text}")
        return "\n\n---\n\n".join(passages) or "No specific exercise guide details found for that query."
    except Exception as e:
        return f"Exercise guide lookup error: {e}"


def generate_fitness_image(
    prompt: str,
    tool_context: ToolContext = None,
) -> str:
    """Generates a high-quality fitness illustration, exercise form diagram, or nutrition image using gemini-3.1-flash-lite-image in the global region.

    Args:
        prompt: Detailed description of the fitness image to generate (e.g. 'A dumbbell bench press form guide', 'Post-workout protein smoothie bowl').

    Returns:
        Public Cloud Storage HTTPS URL of the generated image.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=f"Generate a clear, high quality fitness image of: {prompt}",
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return "Unable to generate image bytes from model response."

        img_id = uuid.uuid4().hex[:8]
        ext = "png" if "png" in mime_type.lower() else "jpg"
        filename = f"fitness_{img_id}.{ext}"

        # 1. Save artifact to ToolContext for Playground panel
        if tool_context and hasattr(tool_context, "save_artifact"):
            try:
                artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                tool_context.save_artifact(filename=filename, artifact=artifact_part)
            except Exception as e:
                print(f"Warning: Failed to save artifact in tool_context: {e}")

        # 2. Upload image bytes directly to GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        gcs_object_path = f"generated/{filename}"
        blob = bucket.blob(gcs_object_path)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_object_path}"
        return (
            f"🖼️ **Generated Fitness Image**:\n"
            f"- Prompt: '{prompt}'\n"
            f"- Public URL: {public_url}"
        )
    except Exception as e:
        return f"Image generation failed: {e}"


REASONING_ENGINE_RESOURCE = "projects/19860830182/locations/us-east1/reasoningEngines/1661874441988079616"

sandbox_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=REASONING_ENGINE_RESOURCE
)

a2ui_schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_system_prompt = a2ui_schema_manager.generate_system_prompt(
    role_description="You are FitPulse AI, an intelligent personal workout coach.",
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

base_agent_instruction = (
    "You are FitPulse AI, an intelligent personal workout coach. "
    "You help users build training plans, log workouts, calculate heart rate zones, estimate 1-rep max (1RM), look up recovery nutrition, and track progress. "
    "You leverage a Firestore database backend to query curated workout routines and save custom routines. "
    "You leverage an indexed Exercise Benefits RAG Corpus to ground your answers on physiological benefits, target muscle activation, joint impact, and safety cues — call consult_exercise_guide whenever answering questions about exercise form, benefits, or mechanics. "
    "You can generate custom fitness, exercise form, and post-workout meal images using generate_fitness_image — call generate_fitness_image whenever a user requests an image, diagram, or illustration. "
    "You can execute Python code safely in an Agent Engine sandbox to calculate complex training metrics, power-to-weight ratios, or statistical volume trends. "
    "You leverage long-term Memory Bank to automatically remember and retrieve all muscle group exercises, "
    "targeted muscle groups (e.g. Chest, Back, Quads, Hamstrings, Shoulders, Biceps, Triceps, Core), "
    "exercise selections, personal records, injuries, and exercise preferences across conversations. "
    "Whenever a user asks for workout routines or wants to store a routine, use your Firestore tools. "
    "Whenever a user asks about 1-rep max, max weight, or training volume, use calculate_1rm_and_volume. "
    "Whenever a user asks for nutritional content or post-workout food macros, use fetch_fitness_nutrition_info. "
    "Whenever a user asks about exercise benefits, form, or targeted muscle groups, call consult_exercise_guide. "
    "Whenever a user asks to see or generate an image, diagram, or meal illustration, call generate_fitness_image. "
    "Whenever complex calculations, statistics, or custom data transformations are needed, execute Python code in the sandbox."
)

full_agent_instruction = f"{base_agent_instruction}\n\n{a2ui_system_prompt}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=sandbox_executor,
    instruction=full_agent_instruction,
    tools=[
        PreloadMemoryTool(),
        log_workout,
        get_workout_plan,
        calculate_training_zones,
        query_workout_history,
        search_workout_routines_from_firestore,
        save_workout_routine_to_firestore,
        calculate_1rm_and_volume,
        fetch_fitness_nutrition_info,
        consult_exercise_guide,
        generate_fitness_image,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="fitpulse-ai",
)
