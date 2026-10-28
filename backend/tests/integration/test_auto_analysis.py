"""Risk analysis runs automatically once a plan exists (and again after
codegen), so the pipeline's Risk Analysis stage is never left PENDING
waiting for an action the UI does not offer."""
from __future__ import annotations

from sqlmodel import select

from app.models.enums import WorkflowState
from app.models.models import AuditEvent, RiskItem
from app.services import orchestrator as orch
from app.services.pipeline_view import build_pipeline
from app.services.providers.local_provider import LocalProvider


def _stage(session, workflow_id, name):
    return next(s for s in build_pipeline(session, workflow_id)["stages"] if s["name"] == name)


def test_risks_computed_after_planning_and_codegen(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Auto analysis")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    wf = orch.run_indexing(db_session, wf.id)
    wf = orch.run_planning(db_session, wf.id, provider)

    assert wf.state == WorkflowState.AWAITING_PLAN_APPROVAL
    assert db_session.exec(select(RiskItem).where(RiskItem.workflow_id == wf.id)).all()
    assert _stage(db_session, wf.id, "Risk Analysis")["status"] != "PENDING"

    wf = orch.approve_plan(db_session, wf.id, True)
    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL
    assert db_session.exec(select(RiskItem).where(RiskItem.workflow_id == wf.id)).all()


def test_follow_up_failure_is_recorded_not_raised(db_session, demo_repo_copy, monkeypatch):
    project = orch.create_project(db_session, "Auto analysis failure")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    wf = orch.run_indexing(db_session, wf.id)

    def boom(session, workflow_id):
        raise RuntimeError("risk engine exploded")

    monkeypatch.setattr(orch, "run_risk_analysis", boom)
    wf = orch.run_planning(db_session, wf.id, LocalProvider())

    assert wf.state == WorkflowState.AWAITING_PLAN_APPROVAL
    events = db_session.exec(select(AuditEvent).where(AuditEvent.workflow_id == wf.id)).all()
    assert any(e.event_type == "AUTO_ANALYSIS_FAILED" and "exploded" in e.message for e in events)


def test_rejected_changes_can_be_regenerated(db_session, demo_repo_copy):
    from app.models.models import ProposedChange

    provider = LocalProvider()
    project = orch.create_project(db_session, "Regenerate")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    first = len(db_session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all())

    wf = orch.approve_changes(db_session, wf.id, False, comment="try again")
    assert wf.state == WorkflowState.CHANGES_REJECTED

    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL
    # Replaced, not accumulated.
    assert len(db_session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all()) == first


def test_failed_validation_can_be_rerun_and_replaces_results(db_session, demo_repo_copy, monkeypatch):
    from app.models.models import ValidationResult

    provider = LocalProvider()
    project = orch.create_project(db_session, "Rerun validation")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)

    real = orch.run_pipeline

    def broken(*args, **kwargs):  # simulates a broken validation environment
        stages = real(*args, **kwargs)
        for s in stages:
            if s.stage == "unit_tests":
                s.result.exit_code = 1
        return stages

    monkeypatch.setattr(orch, "run_pipeline", broken)
    wf = orch.run_validation(db_session, wf.id)
    assert wf.state == WorkflowState.VALIDATION_FAILED
    first = len(db_session.exec(select(ValidationResult).where(ValidationResult.workflow_id == wf.id)).all())

    monkeypatch.setattr(orch, "run_pipeline", real)
    wf = orch.run_validation(db_session, wf.id)
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL
    rows = db_session.exec(select(ValidationResult).where(ValidationResult.workflow_id == wf.id)).all()
    assert len(rows) == first  # replaced, not appended
    # Payment-idempotency failures live in files a password-reset change never
    # touches: reported as pre-existing, not as failures of this change.
    from app.models.models import ChaosExperiment

    chaos = db_session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == wf.id)).all()
    ch01 = next(c for c in chaos if c.experiment_id == "CH01")
    assert ch01.result == "PRE_EXISTING"
    assert "Pre-existing" in ch01.observed_behavior


def test_codegen_with_no_changes_fails_clearly(db_session, demo_repo_copy):
    import json

    import pytest

    from app.models.models import Plan

    provider = LocalProvider()
    project = orch.create_project(db_session, "No changes")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Make a login page for a food website")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    plan = db_session.exec(select(Plan).where(Plan.workflow_id == wf.id)).first()
    plan.files_json = json.dumps([])  # plan targets nothing
    db_session.add(plan)
    db_session.commit()
    orch.approve_plan(db_session, wf.id, True)

    with pytest.raises(orch.OrchestratorError, match="no changes"):
        orch.run_codegen(db_session, wf.id, provider)
    db_session.refresh(wf)
    assert wf.state == WorkflowState.FAILED  # not left awaiting an approval of nothing


def test_repair_proposal_is_not_duplicated_and_result_is_recorded(db_session, demo_repo_copy, monkeypatch):
    from app.models.models import RepairAttempt

    provider = LocalProvider()
    project = orch.create_project(db_session, "Repair flow")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)

    real = orch.run_pipeline

    def broken(*args, **kwargs):
        stages = real(*args, **kwargs)
        for s in stages:
            if s.stage == "unit_tests":
                s.result.exit_code = 1
        return stages

    monkeypatch.setattr(orch, "run_pipeline", broken)
    wf = orch.run_validation(db_session, wf.id)
    assert wf.state == WorkflowState.VALIDATION_FAILED

    first = orch.propose_repair_for_workflow(db_session, wf.id, provider)
    second = orch.propose_repair_for_workflow(db_session, wf.id, provider)
    assert first.id == second.id
    assert len(db_session.exec(select(RepairAttempt).where(RepairAttempt.workflow_id == wf.id)).all()) == 1

    monkeypatch.setattr(orch, "run_pipeline", real)
    if first.repair_patch:
        wf = orch.approve_repair(db_session, wf.id, first.id, True)
        db_session.refresh(first)
        assert first.result in ("passed", "failed")  # never left "pending" after re-validation
        assert (first.result == "passed") == (wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL)
    else:
        wf = orch.approve_repair(db_session, wf.id, first.id, False)
        db_session.refresh(first)
        assert first.result == "failed"
