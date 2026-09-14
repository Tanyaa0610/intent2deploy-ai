from app.services.rag.chunking import chunk_file, chunk_python
from app.models.enums import ChunkType

PY_SOURCE = '''\
import os

def add(a, b):
    return a + b


class Calculator:
    def multiply(self, a, b):
        return a * b
'''


def test_chunk_python_splits_function_and_class():
    chunks = chunk_python("mod.py", PY_SOURCE)
    kinds = {c.symbol: c.chunk_type for c in chunks}
    assert kinds["add"] == ChunkType.FUNCTION
    assert kinds["Calculator"] == ChunkType.CLASS


def test_chunk_python_module_level_code_captured():
    chunks = chunk_python("mod.py", PY_SOURCE)
    module_chunks = [c for c in chunks if c.chunk_type == ChunkType.MODULE]
    assert any("import os" in c.content for c in module_chunks)


def test_chunk_file_detects_test_files():
    chunks = chunk_file("tests/test_foo.py", "def test_bar():\n    assert True\n")
    assert all(c.chunk_type == ChunkType.TEST for c in chunks)


def test_chunk_file_non_code_uses_fallback():
    chunks = chunk_file("README.md", "# Title\n\nSome paragraph text here.\n")
    assert len(chunks) >= 1
    assert chunks[0].language == "markdown"


def test_chunk_python_syntax_error_falls_back_gracefully():
    chunks = chunk_python("broken.py", "def foo(:\n    pass\n")
    assert len(chunks) >= 1
