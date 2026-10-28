"""Greenfield mode: a repository with no usable source code gets a project
designed and generated from scratch, then flows through the normal approval,
validation and commit pipeline."""
from __future__ import annotations

import json
import re
import shutil

import pytest
from sqlmodel import select

from app.models.enums import WorkflowState
from app.models.models import GeneratedTest, Plan, ProposedChange
from app.services import orchestrator as orch
from app.services.greenfield.service import _safe_path, is_source_file
from app.services.pipeline_view import build_pipeline
from app.services.providers.local_provider import LocalProvider
from app.services.validation.sandbox import workspace_path


def _workflow(db_session, path, intent):
    project = orch.create_project(db_session, "Greenfield")
    repo = orch.register_repository(db_session, project.id, str(path))
    return orch.create_workflow(db_session, project.id, repo.id, intent)


def _stages(db_session, workflow_id):
    return {s["name"]: s for s in build_pipeline(db_session, workflow_id)["stages"]}


def test_empty_repository_generates_tested_project_end_to_end(db_session, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    provider = LocalProvider()
    wf = _workflow(db_session, empty, "Make a login page for a food website")

    wf = orch.run_indexing(db_session, wf.id)
    assert wf.state == WorkflowState.INDEXED
    assert wf.project_mode == "greenfield"

    wf = orch.run_planning(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_PLAN_APPROVAL
    design = json.loads(wf.greenfield_design_json)
    assert design["requirements"] and design["components"] and design["stack"]
    plan = db_session.exec(select(Plan).where(Plan.workflow_id == wf.id)).first()
    planned = json.loads(plan.files_json)
    assert "app/main.py" in planned and any(f.startswith("tests/") for f in planned)

    stages = _stages(db_session, wf.id)
    assert stages["Repository RAG"]["status"] == "SKIPPED"  # no code to retrieve from
    assert stages["Architecture Analysis"]["status"] == "PASSED"
    assert "Designed:" in stages["Architecture Analysis"]["output"]

    orch.approve_plan(db_session, wf.id, True)
    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL
    changes = db_session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all()
    assert {c.file for c in changes} == set(planned)
    assert all(c.operation == "create" and c.patch for c in changes)

    wf = orch.approve_changes(db_session, wf.id, True)
    assert wf.baseline_tests_passed is None  # nothing existed to baseline
    assert (workspace_path(wf.id) / "app" / "main.py").exists()
    assert "Food Website" in (workspace_path(wf.id) / "static" / "index.html").read_text(encoding="utf-8")

    orch.run_test_generation(db_session, wf.id, provider)
    tests = db_session.exec(select(GeneratedTest).where(GeneratedTest.workflow_id == wf.id)).all()
    assert tests and all(t.file.startswith("tests/") for t in tests)

    wf = orch.run_validation(db_session, wf.id)
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL  # generated tests, lint and security pass

    wf = orch.approve_commit(db_session, wf.id, True)
    assert wf.state == WorkflowState.COMMITTED


def test_readme_only_repository_is_greenfield_and_readme_is_kept(db_session, tmp_path):
    repo_dir = tmp_path / "docs-only"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# My notes\n", encoding="utf-8")
    provider = LocalProvider()
    wf = _workflow(db_session, repo_dir, "Build a REST API for managing books")

    wf = orch.run_indexing(db_session, wf.id)
    assert wf.project_mode == "greenfield"  # a README is not usable source code
    orch.run_planning(db_session, wf.id, provider)
    plan = db_session.exec(select(Plan).where(Plan.workflow_id == wf.id)).first()
    assert "README.md" not in json.loads(plan.files_json)  # never planned over an existing file

    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    files = {c.file for c in db_session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all()}
    assert "README.md" not in files
    assert "app/main.py" in files


def test_existing_codebase_keeps_existing_workflow(db_session, demo_repo_copy):
    wf = _workflow(db_session, demo_repo_copy, "Add password reset functionality with appropriate tests.")
    wf = orch.run_indexing(db_session, wf.id)
    assert wf.project_mode == "existing"
    orch.run_planning(db_session, wf.id, LocalProvider())
    assert _stages(db_session, wf.id)["Repository RAG"]["status"] == "PASSED"


def test_indexing_failure_is_not_treated_as_empty(db_session, tmp_path):
    folder = tmp_path / "will-vanish"
    folder.mkdir()
    wf = _workflow(db_session, folder, "Make a login page")
    shutil.rmtree(folder)

    with pytest.raises(orch.OrchestratorError, match="Indexing failed"):
        orch.run_indexing(db_session, wf.id)
    db_session.refresh(wf)
    assert wf.state == WorkflowState.FAILED
    assert wf.project_mode == "existing"  # never switched to greenfield


def test_source_detection_and_path_safety():
    assert is_source_file("src/app.py") and is_source_file("web/index.html")
    assert not is_source_file("README.md") and not is_source_file("LICENSE") and not is_source_file("package.json")
    assert _safe_path("./app/main.py") == "app/main.py"
    assert _safe_path(".env.example") == ".env.example"
    for bad in ("../escape.py", "/etc/passwd", "C:/x.py", ".git/config", ""):
        assert _safe_path(bad) is None


@pytest.mark.parametrize(
    "intent, template",
    [
        ("Build a food delivery app like Zomato", "food_delivery_app"),
        ("create a food delivery app", "food_delivery_app"),
        ("Swiggy clone with restaurants and cart", "food_delivery_app"),
        ("Make a login page for a food website", "login_web_app"),
        ("Build a REST API for managing books", "web_app"),
        ("create a website for flight booking", "web_app"),
    ],
)
def test_template_choice(intent, template):
    from app.services.greenfield.templates import pick_template

    assert pick_template(intent) == template


def test_food_delivery_template_is_a_complete_app(tmp_path):
    import subprocess
    import sys

    from app.core.config import settings
    from app.services.greenfield import templates

    intent = "Build a food delivery app like Zomato"
    design = templates.design(intent)
    files = templates.files(intent, design)
    assert len(files) <= settings.max_greenfield_files
    assert {f["path"] for f in files} == {f["path"] for f in design["files"]}
    for f in files:
        (tmp_path / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f["path"]).write_text(f["content"], encoding="utf-8")
        assert f["content"].count("\n") < settings.max_patch_lines
    assert "Food Delivery App" in (tmp_path / "static" / "index.html").read_text(encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-2000:]


def test_general_requests_get_a_full_stack_web_app(tmp_path):
    import subprocess
    import sys

    from app.core.config import settings
    from app.services.greenfield import templates

    intent = "create a website for flight booking and should name as vanshita flight service"
    design = templates.design(intent)
    assert design["template"] == "web_app" and design["project_name"] == "vanshita-flight-service"
    files = templates.files(intent, design)
    assert len(files) <= settings.max_greenfield_files
    assert {f["path"] for f in files} == {f["path"] for f in design["files"]}
    for f in files:
        (tmp_path / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f["path"]).write_text(f["content"], encoding="utf-8")
        assert not re.search(r"__[A-Z][A-Z_]*__", f["content"]), f["path"]  # every placeholder filled
    page = (tmp_path / "static" / "index.html").read_text(encoding="utf-8")
    assert "Vanshita Flight Service" in page and "New Booking" in page  # brand name + domain labels
    assert '"/api/bookings"' in (tmp_path / "static" / "app.js").read_text(encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-2000:]


@pytest.mark.parametrize(
    "intent, title",
    [
        ("create a website for flight booking and should name as vanshita flight service", "Vanshita Flight Service"),
        ("make a gym membership tracker called FitHub", "FitHub"),
        ('build a library app named "Read More"', "Read More"),
        ("Build a REST API for managing books", "Managing Books"),
    ],
)
def test_app_title_uses_the_given_name(intent, title):
    from app.services.greenfield.templates import app_title

    assert app_title(intent) == title
