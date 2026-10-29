"""Production verification boots the app the way it ships and tests the
running service over HTTP. It must pass a healthy app and catch broken ones:
server errors, leaked stack traces, crashes under hostile input, and apps
that never start."""
from __future__ import annotations

import pytest

from app.core import config
from app.services.readiness.engine import ReadinessInput, assess
from app.services.validation import production
from app.services.validation.pipeline import StageResult, overall_status
from app.services.validation.sandbox import CommandResult

BUGGY_APP = '''
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

app = FastAPI()
ITEMS = {}


@app.exception_handler(Exception)
async def debug_errors(request: Request, exc: Exception):
    return PlainTextResponse(traceback.format_exc(), status_code=500)  # leaks internals, like a debug server


class ItemIn(BaseModel):
    name: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/items")
def list_items():
    return sorted(ITEMS.values(), key=lambda i: i["missing"])  # KeyError once there is data


@app.post("/api/items", status_code=201)
def create(item: ItemIn):
    if "<" in item.name or "'" in item.name:
        raise ValueError("unescaped input reached the query builder")
    ITEMS[len(ITEMS) + 1] = {"id": len(ITEMS) + 1, "name": item.name}
    return ITEMS[len(ITEMS)]
'''


@pytest.fixture
def fast_load(monkeypatch):
    monkeypatch.setattr(config.settings, "prod_load_requests", 60)
    monkeypatch.setattr(config.settings, "prod_load_concurrency", 5)
    monkeypatch.setattr(config.settings, "prod_boot_timeout_seconds", 30)


def _write(root, files: dict[str, str]):
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content, encoding="utf-8")


def _by_stage(results):
    return {stage: r for stage, r in results}


def test_generated_web_app_passes_every_production_stage(tmp_path, fast_load):
    from app.services.greenfield import templates

    intent = "create a website for flight booking"
    _write(tmp_path, {f["path"]: f["content"] for f in templates.files(intent, templates.design(intent))})
    results = _by_stage(production.run(tmp_path))
    assert list(results) == list(production.STAGES)
    for stage, r in results.items():
        assert r.status == "passed", f"{stage}:\n{r.stdout}\n{r.stderr}"
    assert "POST /api/bookings with a valid body — HTTP 201" in results["prod_api"].stdout
    assert "DELETE /api/bookings/{record_id} removes it" in results["prod_api"].stdout
    assert "p95" in results["prod_load"].stdout
    assert "did not survive the restart" in results["prod_recovery"].stdout  # in-memory storage is reported


def test_broken_service_is_caught(tmp_path, fast_load):
    _write(tmp_path, {"app/__init__.py": "", "app/main.py": BUGGY_APP, "requirements.txt": "fastapi\nuvicorn\n"})
    results = _by_stage(production.run(tmp_path))
    assert results["prod_boot"].status == "passed"
    # The list endpoint crashes once a record exists and the error page leaks a stack trace.
    robustness = results["prod_robustness"]
    assert robustness.status == "failed"
    assert "FAIL  POST /api/items: script/SQL injection strings" in robustness.stdout
    assert "leaks a Python stack trace" in robustness.stdout
    assert results["prod_load"].status == "failed"  # GET /api/items now returns 500 under load
    stages = [StageResult("unit_tests", CommandResult("pytest", 0, "", "", 1))] + [StageResult(s, r) for s, r in results.items()]
    assert overall_status(stages) == "failed"  # a failing live check fails validation


def test_app_that_cannot_start_fails_boot_and_skips_the_rest(tmp_path, fast_load):
    _write(tmp_path, {"app/__init__.py": "", "requirements.txt": "fastapi\n",
                      "app/main.py": "from fastapi import FastAPI\nimport module_that_does_not_exist\napp = FastAPI()\n"})
    results = _by_stage(production.run(tmp_path))
    assert results["prod_boot"].status == "failed"
    assert "module_that_does_not_exist" in results["prod_boot"].stderr  # the app's own log explains why
    assert all(results[s].status == "skipped" for s in production.STAGES[1:])


def test_skipped_when_unit_tests_fail(tmp_path):
    results = production.run(tmp_path, skip_reason="Unit tests failed.")
    assert all(r.status == "skipped" for _, r in results)


def test_request_bodies_are_generated_from_the_openapi_schema():
    root = {"components": {"schemas": {
        "Address": {"type": "object", "required": ["phone"], "properties": {"phone": {"type": "string", "pattern": r"^\d{10}$"}}},
        "Order": {"type": "object", "properties": {
            "email": {"type": "string"}, "qty": {"type": "integer", "minimum": 2}, "when": {"type": "string", "format": "date"},
            "kind": {"enum": ["pickup", "delivery"]}, "note": {"anyOf": [{"type": "string", "minLength": 3}, {"type": "null"}]},
            "address": {"$ref": "#/components/schemas/Address"}, "tags": {"type": "array", "items": {"type": "string"}},
        }},
    }}}
    body = production.sample_value({"$ref": "#/components/schemas/Order"}, root)
    assert body["email"] == "qa.user@example.com" and body["qty"] == 2 and body["when"] == "2030-01-15"
    assert body["kind"] == "pickup" and len(body["note"]) >= 3 and body["address"]["phone"] == "9876543210"
    assert body["tags"] == ["Sample tags"]


def test_readiness_blocks_on_failed_production_checks():
    base = dict(validation_passed=True, blocked_guardrails=[], warning_guardrails=[], open_critical_risks=0,
                open_high_risks=0, chaos_pass_rate=1.0, rollback_status="PASSED", ci_passed=True, container_status="PASSED")
    failed = assess(ReadinessInput(**base, production_status="FAILED"))
    assert failed.decision == "NOT_READY" and failed.checklist["production_tests"] == "FAILED"
    assert assess(ReadinessInput(**base, production_status="PASSED")).decision == "READY"
    skipped = assess(ReadinessInput(**base, production_status="SKIPPED"))
    assert skipped.decision == "READY_WITH_WARNINGS"


def test_workflow_validation_runs_the_service_live(db_session, demo_repo_copy, monkeypatch, fast_load):
    """End to end on an existing repository: the validated workspace is booted
    and tested, results are stored per stage, and readiness reflects them."""
    import json

    from sqlmodel import select

    from app.models.enums import WorkflowState
    from app.models.models import ValidationResult
    from app.services import orchestrator as orch
    from app.services.providers.local_provider import LocalProvider

    monkeypatch.setattr(config.settings, "production_validation", True)
    provider = LocalProvider()
    project = orch.create_project(db_session, "Live checks")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)
    wf = orch.run_validation(db_session, wf.id)

    rows = {r.stage: r for r in db_session.exec(select(ValidationResult).where(ValidationResult.workflow_id == wf.id)).all()}
    for stage in production.STAGES:
        assert rows[stage].status == "passed", f"{stage}:\n{rows[stage].stdout}\n{rows[stage].stderr}"
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL
    assessment = orch.run_production_readiness(db_session, wf.id)
    assert json.loads(assessment.checklist_json)["production_tests"] == "PASSED"


@pytest.mark.parametrize("broken", [False, True])
def test_ci_production_check_script_passes_good_apps_and_fails_broken_ones(tmp_path, broken):
    """The script every project ships for CI (.github/scripts/production_check.py)
    is run exactly as the Docker workflow runs it, against the started app."""
    import subprocess
    import sys

    from app.services import containerize
    from app.services.greenfield import templates

    if broken:
        _write(tmp_path, {"app/__init__.py": "", "app/main.py": BUGGY_APP})
        script = tmp_path / containerize.PRODUCTION_CHECK_PATH
        script.parent.mkdir(parents=True)
        script.write_text(containerize.production_check_script(), encoding="utf-8")
    else:
        intent = "create a website for flight booking"
        _write(tmp_path, {f["path"]: f["content"] for f in templates.files(intent, templates.design(intent))})
    app = production.RunningApp(tmp_path, "app.main:app", 8000, "/health")
    app.start()
    try:
        result = subprocess.run(
            [sys.executable, containerize.PRODUCTION_CHECK_PATH, app.base_url, "--requests", "60", "--concurrency", "5"],
            cwd=tmp_path, capture_output=True, text=True, timeout=180,
        )
    finally:
        app.remove()
    if broken:
        assert result.returncode == 1
        assert "FAIL  Hostile: POST /api/items injection strings" in result.stdout
    else:
        assert result.returncode == 0, result.stdout
        assert "PASS  API: DELETE /api/bookings/{id}" in result.stdout and "p95" in result.stdout
