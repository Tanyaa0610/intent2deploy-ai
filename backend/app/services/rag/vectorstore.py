from __future__ import annotations

from pathlib import Path

from langchain_chroma import Chroma

from app.core.config import settings
from app.services.rag.embeddings import LangChainEmbeddingsAdapter

_embeddings = LangChainEmbeddingsAdapter()


def get_vectorstore(collection_name: str) -> Chroma:
    persist_dir = Path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name,
        embedding_function=_embeddings,
        persist_directory=str(persist_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )


def reset_collection(collection_name: str) -> None:
    """Delete and recreate a collection (used on re-indexing)."""
    store = get_vectorstore(collection_name)
    try:
        store.delete_collection()
    except Exception:
        pass
