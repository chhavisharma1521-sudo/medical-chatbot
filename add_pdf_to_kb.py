"""
Add ONE pdf/txt file into the existing Qdrant knowledge base (incremental — keeps old data).
Usage:  python add_pdf_to_kb.py "path/to/file.pdf"
"""
import re
import sys
import uuid
import time
from pathlib import Path

import pypdf
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

QDRANT_DIR = Path("qdrant_db")
COLLECTION_NAME = "medical_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384
CHUNK_SIZE = 1200
CHUNK_OVERLAP = int(CHUNK_SIZE * 0.18)


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
    path = Path(sys.argv[1])
    source = path.name
    print(f"Reading {source} ...")
    if path.suffix.lower() == ".pdf":
        reader = pypdf.PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    print(f"  extracted {len(text):,} characters")

    chunks = chunk_text(text)
    print(f"  {len(chunks):,} chunks")
    if not chunks:
        print("No usable text. Aborting.")
        return

    print("Loading embedding model ...")
    embedder = SentenceTransformer(EMBED_MODEL)

    QDRANT_DIR.mkdir(exist_ok=True)
    client = QdrantClient(path=str(QDRANT_DIR))
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
    before = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print(f"  KB has {before} chunks before adding")

    print("Embedding + storing (this can take a few minutes) ...")
    t = time.time()
    batch = 256
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        embs = embedder.encode(part, convert_to_numpy=True)
        points = [
            PointStruct(id=str(uuid.uuid4()), vector=embs[j].tolist(),
                        payload={"text": part[j], "source": source})
            for j in range(len(part))
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"    {min(i + batch, len(chunks))}/{len(chunks)} done")

    after = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print(f"\nDone in {time.time()-t:.0f}s. KB now has {after} chunks (added {after - before}).")


if __name__ == "__main__":
    main()
