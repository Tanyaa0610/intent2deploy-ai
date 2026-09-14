from __future__ import annotations

from app.services.rag.retriever import RetrievalResult


def format_retrieved_context(results: list[RetrievalResult], max_chars_each: int = 500) -> str:
    if not results:
        return "(no relevant repository content was retrieved)"
    blocks = []
    for r in results:
        symbol = f" [{r.symbol}]" if r.symbol else ""
        blocks.append(
            f"### {r.file}:{r.start_line}-{r.end_line}{symbol} (score={r.score:.2f}, {r.reason})\n"
            f"{r.content_preview[:max_chars_each]}"
        )
    return "\n\n".join(blocks)


def to_context_dicts(results: list[RetrievalResult]) -> list[dict]:
    return [
        {
            "file": r.file,
            "start_line": r.start_line,
            "end_line": r.end_line,
            "score": r.score,
            "reason": r.reason,
            "chunk_type": r.chunk_type,
            "symbol": r.symbol,
            "retrieval_method": r.retrieval_method,
            "content_preview": r.content_preview,
        }
        for r in results
    ]
