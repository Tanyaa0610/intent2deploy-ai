"""Every endpoint the frontend API client calls must be registered."""
from __future__ import annotations

from app.main import app

EXPECTED = {
    ("POST", "/api/workflows/{workflow_id}/approve-plan"),
    ("PATCH", "/api/workflows/{workflow_id}/plan"),
    ("POST", "/api/workflows/{workflow_id}/approve-changes"),
    ("POST", "/api/workflows/{workflow_id}/commit"),
    ("POST", "/api/workflows/{workflow_id}/approve-repair"),
}


def test_approval_routes_are_registered():
    registered = {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops}
    assert EXPECTED <= registered, EXPECTED - registered


def test_ask_repository_returns_where_the_answer_is(tmp_path):
    """'Where is the docker configuration' points at the Docker files first."""
    from app.api.repositories import _locations

    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("app = 1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "docker-hook").write_text("x\n", encoding="utf-8")
    evidence = [{"file": "app/main.py", "start_line": 1, "end_line": 1, "symbol": "app", "retrieval_method": "semantic",
                 "score": 0.2}]
    locations = _locations(tmp_path, "where is the docker fikle configuration", evidence)
    assert [loc["file"] for loc in locations] == ["Dockerfile", "docker-compose.yml", "app/main.py"]
    assert locations[0]["why"] == "the file name matches 'docker'" and locations[2]["why"].startswith("its content matches")
