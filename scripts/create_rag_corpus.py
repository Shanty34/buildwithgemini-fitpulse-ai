import time
import vertexai
from vertexai.preview import rag
from vertexai.preview.rag.utils import resources as rr

PROJECT_ID = "qwiklabs-gcp-01-39fe799c3cd6"
LOCATION = "us-central1"
GCS_PATH = "gs://fitpulse-ai-media-39fe799c/rag/exercise_benefits_guide.md"

PARSING_PROMPT = (
    "Extract the individual exercise facts, muscle activation, joint impact, and physiological benefits described in this text. "
    "Output clean, self-contained prose."
)

print(f"Initializing Vertex AI RAG in {LOCATION} for project {PROJECT_ID}...")
vertexai.init(project=PROJECT_ID, location=LOCATION)

print("1. Setting serverless mode for RAG Engine...")
cfg = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragEngineConfig"
try:
    rag.update_rag_engine_config(
        rag_engine_config=rag.RagEngineConfig(
            name=cfg,
            rag_managed_db_config=rag.RagManagedDbConfig(mode=rr.Serverless()),
        )
    )
    print("   Serverless mode updated successfully.")
except Exception as e:
    print(f"   Serverless mode update note: {e}")

print("2. Creating RAG corpus 'fitpulse-exercise-benefits'...")
corpus = rag.create_corpus(
    display_name="fitpulse-exercise-benefits",
    embedding_model_config=rag.EmbeddingModelConfig(
        publisher_model="publishers/google/models/text-embedding-005"
    ),
)
corpus_name = corpus.name
print(f"   Corpus created: {corpus_name}")

print(f"3. Importing file {GCS_PATH} into corpus with LLM parser...")
try:
    resp = rag.import_files(
        corpus_name=corpus_name,
        paths=[GCS_PATH],
        transformation_config=rag.TransformationConfig(
            chunking_config=rag.ChunkingConfig(chunk_size=512, chunk_overlap=100)
        ),
        llm_parser=rag.LlmParserConfig(
            model_name="gemini-2.5-flash",
            custom_parsing_prompt=PARSING_PROMPT,
        ),
    )
    print(f"   Import complete! Files imported: {getattr(resp, 'imported_rag_files_count', 1)}")
except Exception as e:
    print(f"   LLM Parser import failed: {e}. Retrying without LLM parser...")
    resp = rag.import_files(
        corpus_name=corpus_name,
        paths=[GCS_PATH],
        transformation_config=rag.TransformationConfig(
            chunking_config=rag.ChunkingConfig(chunk_size=512, chunk_overlap=100)
        ),
    )
    print("   Import complete without LLM parser!")

print("\n4. Standalone Retrieval Test:")
time.sleep(3)
try:
    test_resp = rag.retrieval_query(
        text="What are the physiological benefits and safety form cues for the Romanian Deadlift?",
        rag_resources=[rag.RagResource(rag_corpus=corpus_name)],
        rag_retrieval_config=rag.RagRetrievalConfig(top_k=3),
    )
    contexts = getattr(test_resp.contexts, "contexts", [])
    print(f"   Retrieved {len(contexts)} contexts:")
    for i, c in enumerate(contexts):
        score = getattr(c, "score", None)
        text = getattr(c, "text", "")[:150]
        print(f"   [{i+1}] (Score: {score}) {text}...")
except Exception as e:
    print(f"   Retrieval test note: {e}")

print(f"\nFINISHED! Corpus Name: {corpus_name}")
