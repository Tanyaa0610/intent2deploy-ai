"""Code-aware chunking (master spec §8, §9: "code-aware chunking rather than
blindly splitting every N characters").

Strategy:
- Python: parse with `ast` and emit one chunk per top-level function/class
  (with nested code included), plus a module-level chunk for imports and
  other top-level statements.
- JS/TS: heuristic regex-based function/class boundary detection (no JS
  parser dependency is installed; documented limitation).
- Everything else (docs, config, JSON/YAML, README, requirements/package
  manifests): a LangChain `RecursiveCharacterTextSplitter` sliding window,
  which is still smarter than naive fixed-width splitting because it
  prefers to break on blank lines/sentence boundaries first.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.models.enums import ChunkType

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
    ".txt": "text",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
}


@dataclass
class Chunk:
    file: str
    start_line: int
    end_line: int
    content: str
    chunk_type: ChunkType
    symbol: str
    language: str
    content_hash: str


def detect_language(path: Path) -> str:
    return LANGUAGE_BY_EXT.get(path.suffix.lower(), "unknown")


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _is_test_file(rel_path: str) -> bool:
    lowered = rel_path.lower()
    return "test" in lowered or lowered.startswith("tests/") or "/tests/" in lowered


def chunk_python(rel_path: str, source: str) -> list[Chunk]:
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _fallback_chunks(rel_path, source, "python")

    chunks: list[Chunk] = []
    covered_lines: set[int] = set()
    base_type = ChunkType.TEST if _is_test_file(rel_path) else ChunkType.OTHER

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            content = "\n".join(lines[start - 1 : end])
            chunk_type = ChunkType.CLASS if isinstance(node, ast.ClassDef) else ChunkType.FUNCTION
            if base_type == ChunkType.TEST:
                chunk_type = ChunkType.TEST
            chunks.append(
                Chunk(
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    content=content,
                    chunk_type=chunk_type,
                    symbol=node.name,
                    language="python",
                    content_hash=_hash(content),
                )
            )
            covered_lines.update(range(start, end + 1))

    # Module-level chunk: everything not already covered by a function/class
    module_lines = [
        (i + 1, line) for i, line in enumerate(lines) if (i + 1) not in covered_lines and line.strip()
    ]
    if module_lines:
        start = module_lines[0][0]
        end = module_lines[-1][0]
        content = "\n".join(lines[start - 1 : end])
        if content.strip():
            chunks.append(
                Chunk(
                    file=rel_path,
                    start_line=start,
                    end_line=end,
                    content=content,
                    chunk_type=ChunkType.MODULE,
                    symbol="",
                    language="python",
                    content_hash=_hash(content),
                )
            )

    return chunks or _fallback_chunks(rel_path, source, "python")


_JS_DEF_RE_PATTERNS = [
    r"^\s*(export\s+)?(async\s+)?function\s+(\w+)",
    r"^\s*(export\s+)?(default\s+)?class\s+(\w+)",
    r"^\s*(export\s+)?const\s+(\w+)\s*=\s*(\(.*?\)|async)\s*=>",
]


def chunk_javascript(rel_path: str, source: str) -> list[Chunk]:
    import re

    lines = source.splitlines()
    boundaries: list[tuple[int, str]] = []
    combined = re.compile("|".join(_JS_DEF_RE_PATTERNS))
    for i, line in enumerate(lines):
        m = combined.match(line)
        if m:
            name = next((g for g in m.groups() if g and g not in ("export ", "async ", "default ")), "anonymous")
            boundaries.append((i + 1, name))

    if not boundaries:
        return _fallback_chunks(rel_path, source, "javascript")

    chunks: list[Chunk] = []
    base_type = ChunkType.TEST if _is_test_file(rel_path) else ChunkType.FUNCTION
    for idx, (start, name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines)
        content = "\n".join(lines[start - 1 : end])
        chunks.append(
            Chunk(
                file=rel_path,
                start_line=start,
                end_line=end,
                content=content,
                chunk_type=base_type,
                symbol=name,
                language="javascript",
                content_hash=_hash(content),
            )
        )
    return chunks


def _fallback_chunks(rel_path: str, source: str, language: str, window: int = 60) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1800, chunk_overlap=150, separators=["\n\n", "\n", " ", ""]
    )
    chunk_type = ChunkType.DOC if language in ("markdown", "text") else ChunkType.CONFIG
    if _is_test_file(rel_path):
        chunk_type = ChunkType.TEST

    docs = splitter.create_documents([source])
    chunks: list[Chunk] = []
    cursor = 0
    lines = source.splitlines()
    for doc in docs:
        text = doc.page_content
        # locate this fragment's approximate line range within the source
        start_idx = source.find(text, cursor)
        if start_idx == -1:
            start_idx = cursor
        start_line = source.count("\n", 0, start_idx) + 1
        end_line = start_line + text.count("\n")
        cursor = max(start_idx + 1, cursor)
        chunks.append(
            Chunk(
                file=rel_path,
                start_line=start_line,
                end_line=min(end_line, len(lines) or end_line),
                content=text,
                chunk_type=chunk_type,
                symbol="",
                language=language,
                content_hash=_hash(text),
            )
        )
    return chunks


def chunk_file(rel_path: str, source: str) -> list[Chunk]:
    path = Path(rel_path)
    language = detect_language(path)
    if not source.strip():
        return []
    if language == "python":
        return chunk_python(rel_path, source)
    if language in ("javascript", "typescript"):
        return chunk_javascript(rel_path, source)
    return _fallback_chunks(rel_path, source, language)
