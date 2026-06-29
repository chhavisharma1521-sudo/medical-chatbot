import os
from pathlib import Path
import google.generativeai as genai
import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "medical_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
TOP_K = 5

_embedder = None
_collection = None
_model = None

SYSTEM_PROMPT = (
    "You are MedBot, a knowledgeable and empathetic medical assistant. "
    "Answer questions accurately using the provided context from the medical knowledge base. "
    "Always remind users to consult a qualified healthcare professional for personalized advice. "
    "Never diagnose conditions definitively or replace professional medical consultation. "
    "If the answer is not clearly in the context, acknowledge that and provide general guidance."
)


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def _get_model():
    global _model
    if _model is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in the .env file")
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction=SYSTEM_PROMPT,
        )
    return _model


def answer(question: str, history: list[dict]) -> str:
    embedder = _get_embedder()
    collection = _get_collection()
    model = _get_model()

    query_vec = embedder.encode(question, convert_to_numpy=True).tolist()

    results = collection.query(
        query_embeddings=[query_vec],
        n_results=min(TOP_K, collection.count()),
    )

    docs = results["documents"][0] if results["documents"] else []
    context = "\n\n---\n\n".join(docs) if docs else "No relevant documents found."

    gemini_history = []
    for msg in history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})

    chat = model.start_chat(history=gemini_history)

    full_message = (
        f"Medical Knowledge Base Context:\n{context}\n\n"
        f"Patient Question: {question}"
    )

    response = chat.send_message(full_message)
    return response.text
