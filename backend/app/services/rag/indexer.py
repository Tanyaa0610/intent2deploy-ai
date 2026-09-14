"""Repository indexing pipeline (master spec §8):

Repository -> file discovery -> language/file filtering -> code-aware
chunking -> metadata extraction -> embeddings -> vector store.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from app.core.security import is_ignored_path
from app.services.rag.chunking import chunk_file, detect_language
from app.services.rag.vectorstore import get_vectorstore, reset_collection

MAX_FILE_SIZE_BYTES = 400_000  # skip very large generated files
TEXT_PROBE_BYTES = 2048


@dataclass
class IndexStats:
    file_count: int
    chunk_count: int
    skipped_files: list[str]
    indexed_files: list[str]


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def discover_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            continue
        if is_ignored_path(rel):
            continue
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue
        files.append(path)
    return files


def index_repository(repo_root: Path, collection_name: str) -> IndexStats:
    """Index a repository into its ChromaDB collection.

    Existing content in the collection is cleared first so re-indexing is
    idempotent.
    """
    reset_collection(collection_name)
    store = get_vectorstore(collection_name)

    files = discover_files(repo_root)
    skipped: list[str] = []
    indexed: list[str] = []
    documents: list[Document] = []
    ids: list[str] = []
    total_chunks = 0

    for path in files:
        rel_path = str(path.relative_to(repo_root))
        try:
            with open(path, "rb") as fh:
                sample = fh.read(TEXT_PROBE_BYTES)
            if _looks_binary(sample):
                skipped.append(rel_path)
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            skipped.append(rel_path)
            continue

        chunks = chunk_file(rel_path, source)
        if not chunks:
            continue
        indexed.append(rel_path)
        language = detect_language(path)
        for chunk in chunks:
            doc = Document(
                page_content=chunk.content[:6000],
                metadata={
                    "file": chunk.file,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type.value,
                    "symbol": chunk.symbol,
                    "language": language,
                    "content_hash": chunk.content_hash,
                },
            )
            documents.append(doc)
            ids.append(f"{chunk.content_hash}-{uuid.uuid4().hex[:6]}")
            total_chunks += 1

    if documents:
        # Chroma has a practical batch-size ceiling; chunk the add calls.
        batch = 200
        for i in range(0, len(documents), batch):
            store.add_documents(documents[i : i + batch], ids=ids[i : i + batch])

    return IndexStats(
        file_count=len(indexed),
        chunk_count=total_chunks,
        skipped_files=skipped,
        indexed_files=indexed,
    )
