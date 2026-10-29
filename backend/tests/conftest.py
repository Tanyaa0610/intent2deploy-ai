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
    # Don't build Docker images in tests (slow, machine-dependent); the
    # docker_build stage is exercised explicitly in test_containerize.py.
    monkeypatch.setattr(config.settings, "docker_validation", False)
    # Booting and load-testing every workflow's app is slow; production
    # verification is exercised explicitly in test_production_validation.py.
    monkeypatch.setattr(config.settings, "production_validation", False)
    # Alerts raised in tests go to a throwaway database, never the real one.
    from app import models  # noqa: F401
    from app.services import alerts

    alert_engine = create_engine(f"sqlite:///{tmp_path / 'alerts.db'}")
    SQLModel.metadata.create_all(alert_engine)
    monkeypatch.setattr(alerts, "engine_override", alert_engine)
    monkeypatch.setattr(config.settings, "alert_webhook_url", "")
    yield
