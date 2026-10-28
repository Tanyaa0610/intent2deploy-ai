"""Every project is containerized before completion: detection, generated
Docker files, the plan/codegen step for existing repositories, the Docker
build validation stage, readiness and the commit gate."""
from __future__ import annotations

import json

import pytest
import yaml
from sqlmodel import select

from app.core import config
from app.models.enums import WorkflowState
from app.models.models import Plan, ProposedChange, ValidationResult
from app.services import containerize
from app.services import orchestrator as orch
from app.services.providers.local_provider import LocalProvider
from app.services.validation.sandbox import workspace_path

INTENT = "Add password reset functionality with appropriate tests."


@pytest.mark.parametrize(
    "files, kind, entry, port",
    [
        ({"src/shop/main.py": "app = FastAPI(title='x')\n@app.get('/health')\n", "requirements.txt": "fastapi\n"},
         "python-asgi", "src.shop.main:app", 8000),
        ({"server.py": "application = Flask(__name__)\n", "requirements.txt": "flask\n"}, "python-flask", "server:application", 8000),
        ({"package.json": json.dumps({"scripts": {"start": "node index.js"}})}, "node", "", 3000),
        ({"index.html": "<h1>hi</h1>"}, "static", "", 80),
    ],
)
def test_detects_project_types(files, kind, entry, port):
    spec = containerize.detect(files)
    assert (spec.kind, spec.entry, spec.port) == (kind, entry, port)
    out = containerize.docker_files(spec, files, "My App")
    assert {"Dockerfile", ".dockerignore", "docker-compose.yml", ".github/workflows/docker.yml", "README.md"} <= set(out)
    assert f"EXPOSE {port}" in out["Dockerfile"]
    assert "## Docker" in out["README.md"] and "docker build -t my-app ." in out["README.md"]
    ci = yaml.safe_load(out[".github/workflows/docker.yml"])
    assert set(ci[True]["push"]["branches"]) == {"main", "staging"}  # builds after each merge
    steps = [s.get("name") for s in ci["jobs"]["docker"]["steps"]]
    assert "Build image" in steps and "Check the running container" in steps


def test_unknown_project_type_is_not_guessed():
    assert containerize.detect({"notes.md": "hello"}) is None


def test_existing_repository_gets_containerized_through_plan_and_changes(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Docker existing")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, INTENT)
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    plan = db_session.exec(select(Plan).where(Plan.workflow_id == wf.id)).first()
    assert "Dockerfile" in json.loads(plan.files_json)
    assert any("Containerize" in s["description"] for s in json.loads(plan.steps_json))

    orch.approve_plan(db_session, wf.id, True)
    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL  # scope guardrail accepts the Docker files
    files = {c.file for c in db_session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all()}
    assert {"Dockerfile", "docker-compose.yml", ".github/workflows/docker.yml", "README.md"} <= files

    orch.approve_changes(db_session, wf.id, True)
    dockerfile = (workspace_path(wf.id) / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["uvicorn", "src.shopflow.main:app"' in dockerfile


def test_commit_is_refused_without_a_dockerfile(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "No docker")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, INTENT)
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)
    orch.run_validation(db_session, wf.id)
    (workspace_path(wf.id) / "Dockerfile").unlink()  # simulate a project that isn't containerized

    with pytest.raises(orch.OrchestratorError, match="containerized"):
        orch.approve_commit(db_session, wf.id, True)
    db_session.refresh(wf)
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL  # nothing committed; fix and approve again
    assessment = orch.run_production_readiness(db_session, wf.id)
    assert assessment.decision == "NOT_READY" and "not containerized" in assessment.reasons_json


def test_docker_build_stage_is_skipped_and_explained_without_docker(db_session, demo_repo_copy, monkeypatch):
    from app.services.validation import sandbox

    monkeypatch.setattr(config.settings, "docker_validation", True)
    monkeypatch.setattr(sandbox, "docker_available", lambda: (False, "Docker is installed but its engine isn't running."))
    provider = LocalProvider()
    project = orch.create_project(db_session, "Docker skipped")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, INTENT)
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)
    wf = orch.run_validation(db_session, wf.id)

    stage = db_session.exec(
        select(ValidationResult).where(ValidationResult.workflow_id == wf.id, ValidationResult.stage == "docker_build")
    ).first()
    assert stage.status == "skipped" and "isn't running" in stage.stdout
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL  # skipped doesn't fail validation; CI builds it
    assessment = orch.run_production_readiness(db_session, wf.id)
    assert json.loads(assessment.checklist_json)["container"] == "SKIPPED"


def test_readme_and_compose_show_where_the_project_actually_runs(tmp_path):
    from types import SimpleNamespace

    from app.services.greenfield import templates
    from app.services.preview import preferred_port

    repo = SimpleNamespace(remote_url="https://github.com/acme/flights.git", source="", local_path=str(tmp_path))
    port, preview = orch._project_port(repo)
    assert (port, preview) == (preferred_port("acme/flights@staging"), True)  # same port as the staging preview

    design = templates.design("create a website for flight booking", port, preview)
    files = {f["path"]: f["content"] for f in templates.files("create a website for flight booking", design)}
    readme = files["README.md"]
    assert f"**Where it runs:** http://127.0.0.1:{port}" in readme
    assert f"--port {port}" in readme and "8010" not in readme
    assert f'"{port}:8000"' in files["docker-compose.yml"]
    assert design["run_command"].endswith(f"--port {port}")

    local = SimpleNamespace(remote_url="", source=str(tmp_path), local_path=str(tmp_path))
    assert orch._project_port(local) == (8010, False)  # no GitHub link -> no preview -> default port
