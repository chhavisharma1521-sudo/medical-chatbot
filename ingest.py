"""
Run this script once (and again after adding new documents) to build the vector database.
Usage: python ingest.py
"""

import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

try:
    from pypdf import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

DATA_DIR = Path("data")
QDRANT_DIR = Path("qdrant_db")
COLLECTION_NAME = "medical_docs"
EMBED_DIM = 384
CHUNK_SIZE = 1200
CHUNK_OVERLAP_RATIO = 0.18
CHUNK_OVERLAP = int(CHUNK_SIZE * CHUNK_OVERLAP_RATIO)  # 216
EMBED_MODEL = "all-MiniLM-L6-v2"


def load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_pdf(path: Path) -> str:
    if not HAS_PDF:
        print(f"  [skip] pypdf not installed — cannot read {path.name}")
        return ""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text: str) -> list[str]:
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


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
        print(f"ERROR: No files found in '{DATA_DIR}/'. Add .txt or .pdf medical documents first.")
        sys.exit(1)

    print("Loading embedding model (downloads ~90 MB on first run)...")
    embedder = SentenceTransformer(EMBED_MODEL)

    print("Connecting to Qdrant...")
    url = os.getenv("QDRANT_URL")
    if url:
        client = QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY"))
    else:
        QDRANT_DIR.mkdir(exist_ok=True)
        client = QdrantClient(path=str(QDRANT_DIR))

    # Fresh rebuild — drop and recreate the collection
    client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    print("Created fresh collection.")

    all_docs, all_ids, all_meta = [], [], []
    doc_count = 0

    for fpath in sorted(DATA_DIR.rglob("*")):
        if fpath.suffix.lower() == ".txt":
            print(f"Loading {fpath.name} ...")
            text = load_txt(fpath)
        elif fpath.suffix.lower() == ".pdf":
            print(f"Loading {fpath.name} ...")
            text = load_pdf(fpath)
        else:
            continue

        chunks = chunk_text(text)
        if not chunks:
            print(f"  [warn] No usable text in {fpath.name}")
            continue

        for chunk in chunks:
            all_docs.append(chunk)
            all_ids.append(str(uuid.uuid4()))
            all_meta.append({"source": fpath.name})

        print(f"  -> {len(chunks)} chunks")
        doc_count += 1

    if not all_docs:
        print("ERROR: No text could be extracted from the documents.")
        sys.exit(1)

    print(f"\nGenerating embeddings for {len(all_docs)} chunks...")
    embeddings = embedder.encode(all_docs, show_progress_bar=True, convert_to_numpy=True)

    print("Storing in Qdrant...")
    batch = 100
    for i in range(0, len(all_docs), batch):
        points = [
            PointStruct(id=all_ids[j], vector=embeddings[j].tolist(),
                        payload={"text": all_docs[j], "source": all_meta[j]["source"]})
            for j in range(i, min(i + batch, len(all_docs)))
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    print(f"\nDone! {len(all_docs)} chunks from {doc_count} file(s) indexed.")
    print("Start the chatbot with:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
