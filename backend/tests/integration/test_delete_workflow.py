"""Deleting a workflow removes its history and workspace, never the repository."""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.models import AuditEvent, GuardrailCheck, Plan, Workflow
from app.services import orchestrator as orch
from app.services.providers.local_provider import LocalProvider
from app.services.validation.sandbox import create_workspace, workspace_path


def test_delete_workflow_removes_history_and_workspace_only(db_session, demo_repo_copy):
    project = orch.create_project(db_session, "Delete me")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, LocalProvider())
    create_workspace(wf.id, demo_repo_copy)
    other = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality.")

    wf_id, other_id = wf.id, other.id
    result = orch.delete_workflow(db_session, wf_id)

    assert result["workspace_removed"] and result["records_removed"] > 0
    assert not workspace_path(wf_id).exists()
    assert db_session.get(Workflow, wf_id) is None
    for model in (AuditEvent, GuardrailCheck, Plan):
        assert not db_session.exec(select(model).where(model.workflow_id == wf_id)).all()
    assert db_session.get(Workflow, other_id) is not None  # other workflows untouched
    assert (demo_repo_copy / "src").is_dir()  # the repository itself is untouched
    with pytest.raises(orch.OrchestratorError):
        orch.delete_workflow(db_session, wf_id)
