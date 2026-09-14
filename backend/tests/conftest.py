from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
DEMO_REPO = PROJECT_ROOT / "demo-repository"


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    from app import models  # noqa: F401  (populate SQLModel metadata)

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def demo_repo_copy(tmp_path):
    """A throwaway copy of the demo repository so tests never mutate the
    real fixture on disk."""
    dest = tmp_path / "demo-repository"
    shutil.copytree(DEMO_REPO, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dest


@pytest.fixture(autouse=True)
def isolate_workspaces_and_chroma(tmp_path, monkeypatch):
    """Point workspace/vector-store directories at a temp dir so tests
    never touch the real project's chroma_data/ or workspaces/."""
    from app.core import config

    monkeypatch.setattr(config.settings, "workspaces_dir", str(tmp_path / "workspaces"))
    monkeypatch.setattr(config.settings, "chroma_persist_dir", str(tmp_path / "chroma_data"))
    yield
