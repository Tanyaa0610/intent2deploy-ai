"""Hybrid retrieval (master spec §9): semantic vector retrieval + filename/
path matching + symbol matching + BM25 keyword retrieval, merged/reranked
into a single ranked list with an explainable `reason` for each result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from app.services.rag.embeddings import tokenize
from app.services.rag.vectorstore import get_vectorstore

SEMANTIC_WEIGHT = 0.5
BM25_WEIGHT = 0.3
PATH_WEIGHT = 0.12
SYMBOL_WEIGHT = 0.08


@dataclass
class RetrievalResult:
    file: str
    start_line: int
    end_line: int
    score: float
    reason: str
    chunk_type: str
    symbol: str
    retrieval_method: str
    content_preview: str
    reasons: list[str] = field(default_factory=list)


def _key(file: str, start: int, end: int) -> tuple[str, int, int]:
    return (file, start, end)


def retrieve(collection_name: str, query: str, top_k: int = 8) -> list[RetrievalResult]:
    store = get_vectorstore(collection_name)
    raw = store.get(include=["documents", "metadatas"])
    all_docs: list[str] = raw.get("documents") or []
    all_meta: list[dict] = raw.get("metadatas") or []

    if not all_docs:
        return []

    candidates: dict[tuple[str, int, int], dict] = {}

    def _ensure(meta: dict, content: str) -> dict:
        k = _key(meta["file"], meta["start_line"], meta["end_line"])
        if k not in candidates:
            candidates[k] = {
                "meta": meta,
                "content": content,
                "semantic": 0.0,
                "bm25": 0.0,
                "path": 0.0,
                "symbol": 0.0,
                "reasons": [],
            }
        return candidates[k]

    # --- 1. Semantic vector retrieval -------------------------------------
    # Chroma is configured with cosine distance (see vectorstore.py), so
    # distance in [0, 2] and similarity = 1 - distance in [-1, 1].
    try:
        semantic_hits = store.similarity_search_with_score(query, k=min(len(all_docs), max(top_k * 3, 10)))
    except Exception:
        semantic_hits = []
    for doc, distance in semantic_hits:
        similarity = max(0.0, 1.0 - float(distance))
        entry = _ensure(doc.metadata, doc.page_content)
        entry["semantic"] = max(entry["semantic"], similarity)
        if similarity > 0:
            entry["reasons"].append(f"semantic similarity {similarity:.2f} to the query")

    # --- 2. BM25 keyword retrieval -----------------------------------------
    tokenized_corpus = [tokenize(d) for d in all_docs]
    bm25 = BM25Okapi(tokenized_corpus) if any(tokenized_corpus) else None
    query_tokens = tokenize(query)
    if bm25 is not None and query_tokens:
        bm25_scores = bm25.get_scores(query_tokens)
        max_bm25 = max(bm25_scores) or 1.0
        for doc, meta, raw_score in zip(all_docs, all_meta, bm25_scores):
            if raw_score <= 0:
                continue
            entry = _ensure(meta, doc)
            norm = raw_score / max_bm25
            entry["bm25"] = max(entry["bm25"], norm)
            entry["reasons"].append("keyword overlap (BM25) with the query")

    # --- 3. Filename/path matching ------------------------------------------
    query_terms = set(query_tokens)
    for doc, meta in zip(all_docs, all_meta):
        path_terms = set(tokenize(meta["file"]))
        overlap = query_terms & path_terms
        if overlap:
            entry = _ensure(meta, doc)
            entry["path"] = max(entry["path"], min(1.0, 0.4 * len(overlap)))
            entry["reasons"].append(f"file path contains matching term(s): {', '.join(sorted(overlap))}")

    # --- 4. Symbol matching ---------------------------------------------------
    for doc, meta in zip(all_docs, all_meta):
        symbol = meta.get("symbol", "")
        if not symbol:
            continue
        symbol_terms = set(tokenize(symbol))
        overlap = query_terms & symbol_terms
        if overlap:
            entry = _ensure(meta, doc)
            entry["symbol"] = max(entry["symbol"], min(1.0, 0.5 * len(overlap)))
            entry["reasons"].append(f"symbol '{symbol}' matches query term(s): {', '.join(sorted(overlap))}")

    # --- Merge / rerank ---------------------------------------------------------
    results: list[RetrievalResult] = []
    for entry in candidates.values():
        meta = entry["meta"]
        combined = (
            SEMANTIC_WEIGHT * entry["semantic"]
            + BM25_WEIGHT * entry["bm25"]
            + PATH_WEIGHT * entry["path"]
            + SYMBOL_WEIGHT * entry["symbol"]
        )
        methods = []
        if entry["semantic"] > 0:
            methods.append("semantic")
        if entry["bm25"] > 0:
            methods.append("keyword")
        if entry["path"] > 0:
            methods.append("path")
        if entry["symbol"] > 0:
            methods.append("symbol")
        reason = "; ".join(dict.fromkeys(entry["reasons"])) or "matched by hybrid retrieval"
        results.append(
            RetrievalResult(
                file=meta["file"],
                start_line=meta["start_line"],
                end_line=meta["end_line"],
                score=round(combined, 4),
                reason=reason,
                chunk_type=meta.get("chunk_type", "other"),
                symbol=meta.get("symbol", ""),
                retrieval_method="+".join(methods) or "none",
                content_preview=entry["content"][:400],
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return [r for r in results if r.score > 0][:top_k]


def retrieve_multi(collection_name: str, queries: list[str], top_k: int = 12) -> list[RetrievalResult]:
    """Run retrieve() for each query and merge results, keeping the best
    score seen for each (file, start_line, end_line)."""
    best: dict[tuple[str, int, int], RetrievalResult] = {}
    for query in queries:
        for r in retrieve(collection_name, query, top_k=top_k):
            key = (r.file, r.start_line, r.end_line)
            if key not in best or r.score > best[key].score:
                best[key] = r
    merged = sorted(best.values(), key=lambda r: r.score, reverse=True)
    return merged[:top_k]


def keyword_search(collection_name: str, pattern: str) -> list[RetrievalResult]:
    """Simple non-ranked substring search, used by the repository search UI
    as a literal fallback to the hybrid `retrieve` function."""
    store = get_vectorstore(collection_name)
    raw = store.get(include=["documents", "metadatas"])
    compiled = re.compile(re.escape(pattern), re.IGNORECASE)
    out: list[RetrievalResult] = []
    for doc, meta in zip(raw.get("documents") or [], raw.get("metadatas") or []):
        if compiled.search(doc) or compiled.search(meta["file"]):
            out.append(
                RetrievalResult(
                    file=meta["file"],
                    start_line=meta["start_line"],
                    end_line=meta["end_line"],
                    score=1.0,
                    reason=f"literal match for '{pattern}'",
                    chunk_type=meta.get("chunk_type", "other"),
                    symbol=meta.get("symbol", ""),
                    retrieval_method="literal",
                    content_preview=doc[:400],
                )
            )
    return out
