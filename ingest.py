"""
Run this script once (and again after adding new documents) to build the vector database.
Usage: python ingest.py
"""

import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import chromadb
from sentence_transformers import SentenceTransformer

try:
    from pypdf import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

DATA_DIR = Path("data")
CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "medical_docs"
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

    print("Connecting to ChromaDB...")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    try:
        client.delete_collection(COLLECTION_NAME)
        print("Cleared previous collection.")
    except Exception:
        pass

    collection = client.create_collection(COLLECTION_NAME)

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

        for i, chunk in enumerate(chunks):
            all_docs.append(chunk)
            all_ids.append(f"{fpath.stem}_{doc_count}_{i}")
            all_meta.append({"source": fpath.name})

        print(f"  -> {len(chunks)} chunks")
        doc_count += 1

    if not all_docs:
        print("ERROR: No text could be extracted from the documents.")
        sys.exit(1)

    print(f"\nGenerating embeddings for {len(all_docs)} chunks...")
    embeddings = embedder.encode(all_docs, show_progress_bar=True, convert_to_numpy=True)

    print("Storing in ChromaDB...")
    batch = 100
    for i in range(0, len(all_docs), batch):
        collection.add(
            documents=all_docs[i:i + batch],
            embeddings=embeddings[i:i + batch].tolist(),
            ids=all_ids[i:i + batch],
            metadatas=all_meta[i:i + batch],
        )

    print(f"\nDone! {len(all_docs)} chunks from {doc_count} file(s) indexed.")
    print("Start the chatbot with:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
