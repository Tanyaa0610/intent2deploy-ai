"""End-to-end integration test: index -> plan -> approve -> codegen ->
approve -> generate tests -> validate -> commit -> report, using the real
sandboxed pipeline against a throwaway copy of the demo repository."""
from __future__ import annotations

from app.models.enums import WorkflowState
from app.services import orchestrator as orch
from app.services.providers.local_provider import LocalProvider
from app.services.reporting import build_report


def test_full_password_reset_workflow(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Integration Test Project")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))

    wf = orch.create_workflow(
        db_session,
        project.id,
        repo.id,
        "Add a password reset feature. Create appropriate tests and make sure existing authentication functionality is not affected.",
    )
    wf = orch.run_indexing(db_session, wf.id)
    assert wf.state == WorkflowState.INDEXED

    wf = orch.run_planning(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_PLAN_APPROVAL

    wf = orch.approve_plan(db_session, wf.id, True)
    assert wf.state == WorkflowState.CHANGES_GENERATING

    wf = orch.run_codegen(db_session, wf.id, provider)
    assert wf.state == WorkflowState.AWAITING_CHANGE_APPROVAL

    wf = orch.approve_changes(db_session, wf.id, True)
    assert wf.state == WorkflowState.TESTS_GENERATING

    wf = orch.run_test_generation(db_session, wf.id, provider)
    wf = orch.run_validation(db_session, wf.id)
    assert wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL

    wf = orch.approve_commit(db_session, wf.id, True)
    assert wf.state == WorkflowState.COMMITTED

    wf = orch.finalize_workflow(db_session, wf.id)
    assert wf.state == WorkflowState.COMPLETED
    assert wf.human_intervention_count == 3
    assert wf.repair_attempts == 0

    report = build_report(db_session, wf.id)
    assert report["final_status"] == "COMPLETED"
    assert report["final_validation"] == "passed"
    assert len(report["changes"]) >= 1
    assert len(report["evidence"]) > 0


def test_plan_rejection_stops_workflow(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Rejection Test Project")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Fix the null-reference bug in the order service.")
    wf = orch.run_indexing(db_session, wf.id)
    wf = orch.run_planning(db_session, wf.id, provider)

    wf = orch.approve_plan(db_session, wf.id, False, comment="needs more detail")
    assert wf.state == WorkflowState.PLAN_REJECTED
    assert wf.human_intervention_count == 1
