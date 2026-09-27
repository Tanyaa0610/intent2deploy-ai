"""Semantic search + RAG Q&A against the payment-reliability demo scenario
(Steps 4-5 of the core-prototype spec). Real retrieval, real (mock-provider)
grounded answer — nothing hardcoded."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.rag.indexer import index_repository
from app.services.rag.retriever import retrieve


def test_semantic_search_finds_payment_files_for_payment_query(demo_repo_copy):
    index_repository(demo_repo_copy, "test_collection_payment_search")

    results = retrieve("test_collection_payment_search", "Where is payment processing implemented?", top_k=8)
    files = {r.file for r in results}

    assert "src/payments/service.py" in files or "src/payments/provider_client.py" in files
    # Different query -> different top files (proves this isn't hardcoded).
    auth_results = retrieve("test_collection_payment_search", "user authentication and login", top_k=8)
    assert {r.file for r in auth_results} != files


def test_rag_qa_answers_payment_duplicate_question_with_real_sources(monkeypatch, tmp_path):
    """Exercises the actual /api/repository/ask endpoint end-to-end against
    a fresh app + demo-repository copy, in mock mode."""
    import shutil
    from pathlib import Path

    from sqlmodel import Session, SQLModel, create_engine

    from app.api.deps import get_session
    from app.core import config as config_module
    from app.main import app
    from app.services import orchestrator as orch

    demo_repo = Path(__file__).resolve().parents[3] / "demo-repository"
    dest = tmp_path / "demo-repository"
    shutil.copytree(demo_repo, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))

    monkeypatch.setattr(config_module.settings, "workspaces_dir", str(tmp_path / "workspaces"))
    monkeypatch.setattr(config_module.settings, "chroma_persist_dir", str(tmp_path / "chroma_data"))

    engine = create_engine(f"sqlite:///{tmp_path / 'rag_qa.db'}")
    SQLModel.metadata.create_all(engine)

    def _get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _get_session_override
    client = TestClient(app)

    with Session(engine) as session:
        project = orch.create_project(session, "RAG QA Project")
        repo = orch.register_repository(session, project.id, str(dest))
        orch.run_indexing_for_repository(session, repo)
        repository_id = repo.id

    try:
        resp = client.post(
            "/api/repository/ask",
            json={"repository_id": repository_id, "question": "Where can duplicate payment requests occur?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"]
        assert body["evidence"]
        assert any("payment" in e["file"].lower() for e in body["evidence"])

        search_resp = client.post(
            "/api/repository/search",
            json={"repository_id": repository_id, "query": "payment idempotency duplicate charge", "top_k": 6},
        )
        assert search_resp.status_code == 200
        search_body = search_resp.json()
        assert search_body["results"]
        assert all({"file", "start_line", "end_line", "score", "content_preview"}.issubset(r.keys()) for r in search_body["results"])
    finally:
        app.dependency_overrides.pop(get_session, None)
