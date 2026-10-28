"""Resuming a failed workflow from where it stopped, after fixing the cause."""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.enums import WorkflowState
from app.models.models import AuditEvent
from app.services import orchestrator as orch
from app.services.providers.local_provider import LocalProvider


def _events(session, workflow_id, event_type):
    return session.exec(select(AuditEvent).where(AuditEvent.workflow_id == workflow_id, AuditEvent.event_type == event_type)).all()


def test_codegen_failure_resumes_after_the_repository_is_fixed(db_session, tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "old_service.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    provider = LocalProvider()
    project = orch.create_project(db_session, "Resume")
    repo = orch.register_repository(db_session, project.id, str(repo_dir))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Build a REST API for managing books")
    orch.run_indexing(db_session, wf.id)
    assert wf.project_mode == "existing"
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    with pytest.raises(orch.OrchestratorError, match="already contains code"):
        orch.run_codegen(db_session, wf.id, provider)
    db_session.refresh(wf)
    assert wf.state == WorkflowState.FAILED and wf.failed_from == WorkflowState.CHANGES_GENERATING.value

    (repo_dir / "old_service.py").unlink()  # the fix: leave the repository empty
    wf = orch.resume_workflow(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_PLAN_APPROVAL  # repository changed kind -> fresh plan to approve
    assert wf.project_mode == "greenfield" and wf.failed_from == ""
    assert _events(db_session, wf.id, "WORKFLOW_RESUMED")

    orch.approve_plan(db_session, wf.id, True)
    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL  # continues from there, same workflow


def test_rejected_commit_resumes_at_commit_approval(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Resume commit")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, provider)
    orch.run_validation(db_session, wf.id)
    wf = orch.approve_commit(db_session, wf.id, False, comment="not yet")
    assert wf.state == WorkflowState.FAILED

    wf = orch.resume_workflow(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL
    wf = orch.approve_commit(db_session, wf.id, True)
    assert wf.state == WorkflowState.COMMITTED


def test_refused_request_and_non_failed_workflows_cannot_resume(db_session, demo_repo_copy):
    project = orch.create_project(db_session, "Refused")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    with pytest.raises(orch.OrchestratorError):
        orch.create_workflow(db_session, project.id, repo.id, "Drop the production database and delete all user records")
    refused = db_session.exec(select(orch.Workflow).where(orch.Workflow.project_id == project.id)).first()
    assert refused.failed_from == "INPUT_REFUSED"
    with pytest.raises(orch.OrchestratorError, match="can't be resumed"):
        orch.resume_workflow(db_session, refused.id, LocalProvider())

    ok = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality.")
    with pytest.raises(orch.OrchestratorError, match="Only a failed workflow"):
        orch.resume_workflow(db_session, ok.id, LocalProvider())


def test_failure_point_is_inferred_for_older_failed_workflows(db_session, demo_repo_copy):
    from app.models.enums import AuditEventType
    from app.services.audit import log_event

    project = orch.create_project(db_session, "Legacy")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality.")
    wf.state = WorkflowState.FAILED  # failed before failed_from existed
    db_session.add(wf)
    db_session.commit()
    log_event(db_session, wf.id, AuditEventType.WORKFLOW_FAILED, stage="codegen", message="old failure")
    assert orch.failure_point(db_session, wf) == WorkflowState.CHANGES_GENERATING.value
