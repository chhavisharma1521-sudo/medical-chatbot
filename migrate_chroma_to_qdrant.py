"""
One-time migration: copy the existing knowledge base from ChromaDB (chroma_db/)
into Qdrant (qdrant_db/). Embeddings are reused as-is — nothing is recomputed.

Usage:  python migrate_chroma_to_qdrant.py
"""
import uuid
from pathlib import Path

import chromadb
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

COLLECTION_NAME = "medical_docs"
CHROMA_DIR = Path("chroma_db")
QDRANT_DIR = Path("qdrant_db")
EMBED_DIM = 384  # all-MiniLM-L6-v2


def main():
    print("Reading from ChromaDB...")
    cclient = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = cclient.get_collection(COLLECTION_NAME)
    total = col.count()
    print(f"  found {total} chunks")

    got = col.get(include=["documents", "embeddings", "metadatas"])
    docs = got["documents"]
    embs = got["embeddings"]
    metas = got["metadatas"] or [{} for _ in docs]

    if not docs:
        print("Nothing to migrate.")
        return

    print("Writing to Qdrant...")
    QDRANT_DIR.mkdir(exist_ok=True)
    qclient = QdrantClient(path=str(QDRANT_DIR))
    try:
        qclient.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    qclient.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )

    points = []
    for doc, emb, meta in zip(docs, embs, metas):
        src = (meta or {}).get("source", "unknown")
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=list(emb),
            payload={"text": doc, "source": src},
        ))

    batch = 100
    for i in range(0, len(points), batch):
        qclient.upsert(collection_name=COLLECTION_NAME, points=points[i:i + batch])

    migrated = qclient.count(collection_name=COLLECTION_NAME, exact=True).count
    print(f"Done! Migrated {migrated} chunks into qdrant_db/")


if __name__ == "__main__":
    main()
