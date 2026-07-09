import os
import re
import time
import uuid
from pathlib import Path
import google.generativeai as genai
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

QDRANT_DIR = Path("qdrant_db")
COLLECTION_NAME = "medical_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384          # all-MiniLM-L6-v2 output size
TOP_K = 5
CHUNK_SIZE = 1200
CHUNK_OVERLAP_RATIO = 0.18
CHUNK_OVERLAP = int(CHUNK_SIZE * CHUNK_OVERLAP_RATIO)  # 216

_embedder = None
_client = None
_model = None

SYSTEM_PROMPT = (
    "You are MedBot, a knowledgeable and empathetic medical assistant. "
    "Answer questions accurately using the provided context from the medical knowledge base. "
    "Always remind users to consult a qualified healthcare professional for personalized advice. "
    "Never diagnose conditions definitively or replace professional medical consultation. "
    "If the answer is not clearly in the context, acknowledge that and provide general guidance. "
    "\n\n### MOST IMPORTANT RULE — REPLY LANGUAGE (never break this):\n"
    "Decide your reply language ONLY from the PATIENT'S QUESTION — never from the knowledge base "
    "context (that context is always in English, so ignore its language completely).\n"
    "- If the patient's question is in plain ENGLISH -> reply fully in ENGLISH.\n"
    "- If the question is in HINDI (Devanagari script, e.g. 'अस्थमा क्या है') -> reply fully in HINDI.\n"
    "- If the question is in HINGLISH (Hindi written in English letters, e.g. 'asthma kya hota hai') "
    "-> reply in HINGLISH.\n"
    "Match the patient's language and tone in EVERY reply, even if the medical context you were given "
    "is in English. Keep answers simple and easy to understand."
)


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_client() -> QdrantClient:
    """Return a Qdrant client. Uses a hosted server if QDRANT_URL is set,
    otherwise a local on-disk store (qdrant_db/) — no separate server needed."""
    global _client
    if _client is None:
        url = os.getenv("QDRANT_URL")
        if url:
            _client = QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY"))
        else:
            QDRANT_DIR.mkdir(exist_ok=True)
            _client = QdrantClient(path=str(QDRANT_DIR))
        _ensure_collection(_client)
    return _client


def _ensure_collection(client: QdrantClient):
    """Create the collection if it doesn't exist yet (so uploads work even before ingest)."""
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )


def _chunk_text(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= CHUNK_SIZE:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            words = current.split()
            overlap = " ".join(words[-(CHUNK_OVERLAP // 5):]) if words else ""
            current = (overlap + " " + sent).strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) > 40]


def add_document_to_kb(text: str, source_name: str) -> int:
    """Chunk, embed and add a document's text to the vector DB so the chatbot can use it. Returns chunk count."""
    chunks = _chunk_text(text)
    if not chunks:
        return 0
    embedder = _get_embedder()
    client = _get_client()
    embeddings = embedder.encode(chunks, convert_to_numpy=True)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=emb.tolist(),
            payload={"text": chunk, "source": source_name},
        )
        for chunk, emb in zip(chunks, embeddings)
    ]
    batch = 100
    for i in range(0, len(points), batch):
        client.upsert(collection_name=COLLECTION_NAME, points=points[i:i + batch])
    return len(chunks)


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


def kb_stats() -> dict:
    """Return knowledge-base / vector DB statistics for the admin panel."""
    try:
        client = _get_client()
        total = client.count(collection_name=COLLECTION_NAME, exact=True).count

        # Scroll through points to find distinct source documents
        sources = {}
        try:
            offset = None
            scanned = 0
            while True:
                points, offset = client.scroll(
                    collection_name=COLLECTION_NAME, limit=1000,
                    offset=offset, with_payload=True, with_vectors=False,
                )
                for p in points:
                    md = p.payload or {}
                    src = md.get("source") or md.get("filename") or md.get("file") or "unknown"
                    sources[src] = sources.get(src, 0) + 1
                scanned += len(points)
                if offset is None or scanned >= 10000:
                    break
        except Exception:
            pass

        return {
            "available": True,
            "collection": COLLECTION_NAME,
            "embed_model": EMBED_MODEL,
            "total_chunks": total,
            "total_sources": len(sources),
            "sources": [{"name": k, "chunks": v} for k, v in sorted(sources.items(), key=lambda x: -x[1])],
        }
    except Exception as e:
        return {
            "available": False,
            "collection": COLLECTION_NAME,
            "embed_model": EMBED_MODEL,
            "total_chunks": 0,
            "total_sources": 0,
            "sources": [],
            "error": str(e),
        }


def answer(question: str, history: list[dict]) -> str:
    embedder = _get_embedder()
    client = _get_client()
    model = _get_model()

    query_vec = embedder.encode(question, convert_to_numpy=True).tolist()

    hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vec,
        limit=TOP_K,
        with_payload=True,
    ).points

    docs = [(h.payload or {}).get("text", "") for h in hits]
    docs = [d for d in docs if d]
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
