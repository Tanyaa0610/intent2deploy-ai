# RAG Design

## Indexing pipeline

```
Repository -> file discovery -> language/file filtering ->
code-aware chunking -> metadata extraction -> embeddings -> vector store
```

Implemented in `backend/app/services/rag/indexer.py`.

- **File discovery**: recursive walk (`discover_files`), skipping ignored
  directories/files (`.git`, `node_modules`, virtualenvs, build output,
  `.env*`, binaries, media) via `app/core/security.py::is_ignored_path`,
  and skipping files above `MAX_FILE_SIZE_BYTES`.
- **Language/file filtering**: `chunking.py::detect_language` maps
  extensions to a language tag; binary files are additionally probed by
  sampling the first 2KB for null bytes / non-UTF-8 content.
- **Code-aware chunking** (`chunking.py`):
  - Python: parsed with the standard-library `ast` module. One chunk per
    top-level function/class (including nested code), plus a module-level
    chunk for imports/top-level statements not covered by a def/class.
  - JavaScript/TypeScript: regex-based function/class boundary detection
    (no JS parser dependency is installed — documented limitation).
  - Everything else (docs, JSON/YAML, README, requirements/package
    manifests): a LangChain `RecursiveCharacterTextSplitter` sliding
    window, which prefers paragraph/line breaks over blind fixed-width
    cuts.
- **Metadata extracted per chunk**: file path, start/end line, chunk type
  (function/class/module/test/config/doc), symbol name, language, and a
  SHA-256 content hash (used as part of the vector-store document ID).
- **Embeddings**: see below.
- **Vector store**: ChromaDB, persisted per-repository under
  `CHROMA_PERSIST_DIR`, one collection per indexed repository
  (`repo_<name>_<project_id>`), configured for cosine distance.

## Why a deterministic hashing embedding, not a downloaded model

The default embedding (`app/services/rag/embeddings.py`) is a
feature-hashing ("hashing trick") bag-of-words embedding: identifier-aware
tokenization (splits `camelCase`/`snake_case`), term-frequency weighting,
hashed into a fixed 384-dimensional vector, L2-normalized for cosine
similarity.

This is a deliberate, documented trade-off for a course project that must
be reproducible in a live viva: relying on downloading a transformer
embedding model (e.g. via ChromaDB's default ONNX MiniLM function) adds a
network dependency that can hang or fail at demo time with no useful
error. The hashing embedding is:

- fully offline and deterministic (same input -> same vector, every run),
- fast enough for a live demo on a laptop,
- swappable — `LangChainEmbeddingsAdapter` implements LangChain's
  `Embeddings` interface, so a real API-backed embedding model can be
  substituted without touching any calling code.

It is a legitimate, if lower-quality-than-transformer, embedding
technique — not a placeholder. The retrieval quality metrics in
`evaluation/results/` are measured against this embedding; a live LLM
run with a transformer or API embedding would be expected to score
higher on retrieval precision, and that comparison is left as documented
future work (see `docs/evaluation.md`).

## Retrieval

`app/services/rag/retriever.py::retrieve` combines four signals:

1. **Semantic vector retrieval** — Chroma cosine similarity search.
2. **BM25 keyword retrieval** — `rank_bm25.BM25Okapi` over the same
   identifier-aware tokenization, run in-memory over the collection's
   documents (practical at demo-repository scale).
3. **Filename/path matching** — token overlap between the query and the
   file's path components.
4. **Symbol matching** — token overlap between the query and the chunk's
   symbol name (function/class name).

Scores are merged with fixed weights
(`SEMANTIC_WEIGHT=0.5, BM25_WEIGHT=0.3, PATH_WEIGHT=0.12, SYMBOL_WEIGHT=0.08`)
and every result carries a human-readable `reason` string built from
which signals fired — this is what the UI's Repository Intelligence and
Plan evidence panels display, satisfying the explainability requirement.

`retrieve_multi` runs several expanded queries (from the
`retrieval_query_generation` prompt) and merges the best score seen per
chunk, since a single literal query under-covers the retrieval need.

## Retrieval evaluation

Where a benchmark task specifies `expected_files` (ground truth),
`scripts/run_evaluation.py` computes real Precision@K and Recall@K by
intersecting retrieved files against that ground truth — see
`docs/evaluation.md` for measured numbers.
