import os
import re
from pathlib import Path
import google.generativeai as genai
import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "medical_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
TOP_K = 5
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 50

_embedder = None
_collection = None
_model = None

SYSTEM_PROMPT = (
    "You are MedBot, a knowledgeable and empathetic medical assistant. "
    "Answer questions accurately using the provided context from the medical knowledge base. "
    "Always remind users to consult a qualified healthcare professional for personalized advice. "
    "Never diagnose conditions definitively or replace professional medical consultation. "
    "If the answer is not clearly in the context, acknowledge that and provide general guidance. "
    "IMPORTANT — Language: Always reply in the SAME language the user writes in. "
    "If they write in Hindi (Devanagari), reply in Hindi. If they write in Hinglish "
    "(Hindi using English letters), reply in Hinglish. If English, reply in English. "
    "Match their language and tone naturally, and keep answers simple and easy to understand."
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
        # get_or_create so uploading works even if the KB was never ingested
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


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
    collection = _get_collection()
    embeddings = embedder.encode(chunks, convert_to_numpy=True)
    import time
    stamp = int(time.time())
    ids = [f"{Path(source_name).stem}_{stamp}_{i}" for i in range(len(chunks))]
    metas = [{"source": source_name} for _ in chunks]
    batch = 100
    for i in range(0, len(chunks), batch):
        collection.add(
            documents=chunks[i:i + batch],
            embeddings=embeddings[i:i + batch].tolist(),
            ids=ids[i:i + batch],
            metadatas=metas[i:i + batch],
        )
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
        collection = _get_collection()
        total = collection.count()

        # Sample a batch of metadata to find distinct source documents
        sources = {}
        try:
            sample = collection.get(include=["metadatas"], limit=10000)
            for md in (sample.get("metadatas") or []):
                if not md:
                    continue
                src = md.get("source") or md.get("filename") or md.get("file") or "unknown"
                sources[src] = sources.get(src, 0) + 1
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
