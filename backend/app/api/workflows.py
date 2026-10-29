from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.deps import get_provider, get_session
from app.models.models import (
    AuditEvent,
    CIRun,
    GeneratedTest,
    GitOperation,
    Plan,
    ProposedChange,
    RepairAttempt,
    Repository,
    RetrievedDocument,
    ValidationResult,
    Workflow,
)
from app.schemas.api import (
    ApprovalRequest,
    CIStatusRequest,
    GitHubTokenRequest,
    MergeRequest,
    ReleaseMergeRequest,
    CreateWorkflowRequest,
    PRApprovalRequest,
    PushApprovalRequest,
    RepairApprovalRequest,
    RevisionRequest,
    UpdatePlanRequest,
    WorkflowResponse,
)
from app.services import orchestrator as orch
from app.services.orchestrator import OrchestratorError
from app.services.providers.base import LLMProvider

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except OrchestratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=WorkflowResponse)
def create_workflow(payload: CreateWorkflowRequest, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(
        orch.create_workflow,
        session,
        payload.project_id,
        payload.repository_id,
        payload.intent,
        payload.base_branch,
        payload.test_command,
        payload.build_command,
        payload.environment,
    )


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(project_id: str | None = None, session: Session = Depends(get_session)) -> list[Workflow]:
    stmt = select(Workflow).order_by(Workflow.created_at.desc())
    if project_id:
        stmt = stmt.where(Workflow.project_id == project_id)
    return list(session.exec(stmt).all())


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: str, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.get_workflow, session, workflow_id)


@router.delete("/{workflow_id}")
def delete_workflow_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Delete a workflow's history and local workspace (not the repository, not GitHub)."""
    return _wrap(orch.delete_workflow, session, workflow_id)


@router.post("/{workflow_id}/revise")
def revise_workflow_endpoint(
    workflow_id: str, payload: RevisionRequest, session: Session = Depends(get_session),
    provider: LLMProvider = Depends(get_provider),
) -> dict:
    """Report a problem found after testing (e.g. on staging). If the code on
    staging already does what is asked, says so with evidence; otherwise
    starts a follow-up workflow that fixes it, planned and waiting for approval."""
    try:
        revision = orch.create_revision(
            session, workflow_id, payload.problem, provider, payload.screenshots, payload.force, payload.addons
        )
    except orch.AlreadySatisfied as exc:
        return {"already_satisfied": True, "message": str(exc), "upgrades": exc.upgrades, "findings": [
            {"capability": f.capability, "present": f.present, "evidence": f.evidence} for f in exc.result.findings
        ]}
    except OrchestratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"already_satisfied": False, "workflow": WorkflowResponse.model_validate(revision, from_attributes=True).model_dump()}


@router.get("/{workflow_id}/attachments/{name}")
def attachment_endpoint(workflow_id: str, name: str) -> FileResponse:
    """A screenshot attached to a problem report."""
    from app.services import attachments

    try:
        path = attachments.path_for(workflow_id, name)
    except attachments.AttachmentError:
        path = None
    if path is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return FileResponse(path, media_type=attachments.MEDIA_TYPES[path.suffix.lstrip(".")],
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


@router.get("/{workflow_id}/revisions", response_model=list[WorkflowResponse])
def list_revisions_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> list[Workflow]:
    return orch.list_revisions(session, workflow_id)


@router.get("/{workflow_id}/addons")
def addons_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Built-in upgrades for the code on staging: available, applied or not supported."""
    from app.models.models import Repository
    from app.services import addons

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None or not Path(repository.local_path).is_dir():
        return {"addons": []}
    return {"addons": addons.statuses(Path(repository.local_path))}


@router.get("/{workflow_id}/revision-check")
def revision_check_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """For a revision: what the code on staging already has of what was reported."""
    from app.models.models import Repository
    from app.services import revision_check

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if not workflow.revision_note or repository is None or not Path(repository.local_path).is_dir():
        return {"checked": False, "already_satisfied": False, "findings": []}
    result = revision_check.check(Path(repository.local_path), workflow.revision_note)
    return {"checked": True, "already_satisfied": result.already_satisfied, "findings": [
        {"capability": f.capability, "present": f.present, "evidence": f.evidence} for f in result.findings
    ]}


@router.post("/{workflow_id}/resume", response_model=WorkflowResponse)
def resume_workflow_endpoint(
    workflow_id: str, session: Session = Depends(get_session), provider: LLMProvider = Depends(get_provider)
) -> Workflow:
    """Continue a failed workflow from where it stopped, after the cause was fixed."""
    return _wrap(orch.resume_workflow, session, workflow_id, provider)


@router.post("/{workflow_id}/index", response_model=WorkflowResponse)
def run_indexing(workflow_id: str, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.run_indexing, session, workflow_id)


@router.post("/{workflow_id}/plan", response_model=WorkflowResponse)
def run_planning(workflow_id: str, session: Session = Depends(get_session), provider: LLMProvider = Depends(get_provider)) -> Workflow:
    return _wrap(orch.run_planning, session, workflow_id, provider)


@router.get("/{workflow_id}/plan")
def get_plan(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    plan = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan found for this workflow")
    return {
        "id": plan.id,
        "summary": plan.summary,
        "assumptions": json.loads(plan.assumptions_json),
        "acceptance_criteria": json.loads(plan.acceptance_criteria_json),
        "steps": json.loads(plan.steps_json),
        "files_likely_to_change": json.loads(plan.files_json),
        "dependencies": json.loads(plan.dependencies_json),
        "test_strategy": json.loads(plan.test_strategy_json),
        "risks": json.loads(plan.risks_json),
        "prompt_version": plan.prompt_version,
        "approved": plan.approved,
        "approval_comment": plan.approval_comment,
    }


@router.patch("/{workflow_id}/plan")
def update_plan(workflow_id: str, payload: UpdatePlanRequest, session: Session = Depends(get_session)) -> dict:
    """Update editable plan fields before approval.
    Only permitted when the workflow is in AWAITING_PLAN_APPROVAL state.
    Does not change workflow state — the user must still call approve-plan.
    """
    plan = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan found for this workflow")
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.state not in ("AWAITING_PLAN_APPROVAL", "PLAN_REJECTED"):
        raise HTTPException(
            status_code=400,
            detail=f"Plan can only be edited in AWAITING_PLAN_APPROVAL or PLAN_REJECTED state, current state: {workflow.state}",
        )
    import json as _json
    if payload.summary is not None:
        plan.summary = payload.summary
    if payload.assumptions is not None:
        plan.assumptions_json = _json.dumps(payload.assumptions)
    if payload.acceptance_criteria is not None:
        plan.acceptance_criteria_json = _json.dumps(payload.acceptance_criteria)
    if payload.steps is not None:
        plan.steps_json = _json.dumps([s.model_dump() for s in payload.steps])
    if payload.files_likely_to_change is not None:
        plan.files_json = _json.dumps(payload.files_likely_to_change)
    if payload.test_strategy is not None:
        plan.test_strategy_json = _json.dumps(payload.test_strategy)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return {
        "id": plan.id,
        "summary": plan.summary,
        "assumptions": _json.loads(plan.assumptions_json),
        "acceptance_criteria": _json.loads(plan.acceptance_criteria_json),
        "steps": _json.loads(plan.steps_json),
        "files_likely_to_change": _json.loads(plan.files_json),
        "dependencies": _json.loads(plan.dependencies_json),
        "test_strategy": _json.loads(plan.test_strategy_json),
        "risks": _json.loads(plan.risks_json),
        "prompt_version": plan.prompt_version,
        "approved": plan.approved,
        "approval_comment": plan.approval_comment,
    }


@router.post("/{workflow_id}/approve-plan", response_model=WorkflowResponse)
def approve_plan(workflow_id: str, payload: ApprovalRequest, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.approve_plan, session, workflow_id, payload.approved, payload.comment)


@router.post("/{workflow_id}/generate-changes", response_model=WorkflowResponse)
def generate_changes_endpoint(workflow_id: str, session: Session = Depends(get_session), provider: LLMProvider = Depends(get_provider)) -> Workflow:
    return _wrap(orch.run_codegen, session, workflow_id, provider)


@router.get("/{workflow_id}/changes")
def get_changes(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    return {
        "changes": [
            {
                "id": c.id,
                "file": c.file,
                "operation": c.operation,
                "reason": c.reason,
                "patch": c.patch,
                "confidence": c.confidence,
                "risks": json.loads(c.risks_json),
                "acceptance_criterion": c.acceptance_criterion,
            }
            for c in changes
        ]
    }


@router.post("/{workflow_id}/approve-changes", response_model=WorkflowResponse)
def approve_changes(workflow_id: str, payload: ApprovalRequest, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.approve_changes, session, workflow_id, payload.approved, payload.comment)


@router.post("/{workflow_id}/generate-tests", response_model=WorkflowResponse)
def generate_tests_endpoint(workflow_id: str, session: Session = Depends(get_session), provider: LLMProvider = Depends(get_provider)) -> Workflow:
    return _wrap(orch.run_test_generation, session, workflow_id, provider)


@router.get("/{workflow_id}/tests")
def get_tests(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    tests = session.exec(select(GeneratedTest).where(GeneratedTest.workflow_id == workflow_id)).all()
    return {
        "tests": [
            {"id": t.id, "file": t.file, "content": t.content, "rationale": t.rationale, "category": t.category}
            for t in tests
        ]
    }


@router.post("/{workflow_id}/validate", response_model=WorkflowResponse)
def validate_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.run_validation, session, workflow_id)


@router.get("/{workflow_id}/validation")
def get_validation(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    results = session.exec(
        select(ValidationResult).where(ValidationResult.workflow_id == workflow_id).order_by(ValidationResult.timestamp)
    ).all()
    return {
        "results": [
            {
                "stage": r.stage,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "exit_code": r.exit_code,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "attempt": r.attempt,
                "command": r.command,
            }
            for r in results
        ]
    }


@router.post("/{workflow_id}/repair")
def propose_repair_endpoint(workflow_id: str, session: Session = Depends(get_session), provider: LLMProvider = Depends(get_provider)) -> dict:
    repair = _wrap(orch.propose_repair_for_workflow, session, workflow_id, provider)
    return {"id": repair.id, "attempt_number": repair.attempt_number, "diagnosis": repair.diagnosis, "repair_patch": repair.repair_patch}


@router.post("/{workflow_id}/approve-repair", response_model=WorkflowResponse)
def approve_repair_endpoint(workflow_id: str, payload: RepairApprovalRequest, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.approve_repair, session, workflow_id, payload.repair_id, payload.approved)


@router.get("/{workflow_id}/repairs")
def get_repairs(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    repairs = session.exec(select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id)).all()
    return {
        "repairs": [
            {
                "id": r.id,
                "attempt_number": r.attempt_number,
                "diagnosis": r.diagnosis,
                "repair_patch": r.repair_patch,
                "approved": r.approved,
                "result": r.result,
            }
            for r in repairs
        ]
    }


@router.post("/{workflow_id}/commit", response_model=WorkflowResponse)
def commit_endpoint(workflow_id: str, payload: ApprovalRequest, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.approve_commit, session, workflow_id, payload.approved, payload.comment)


@router.post("/{workflow_id}/github/push")
def push_endpoint(workflow_id: str, payload: PushApprovalRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.github import github_ops
    from app.services.guardrails import engine as guardrails
    from app.services.validation.sandbox import workspace_path

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    guardrails.record(session, workflow_id, guardrails.check_deployment_approval("external_github_action:push", payload.approved))
    if not payload.approved:
        return {"status": "declined"}
    if not workflow.branch_name:
        raise HTTPException(status_code=400, detail="Nothing to push yet: approve the commit first.")
    workspace = workspace_path(workflow_id)
    target = github_ops.resolve_target(session.get(Repository, workflow.repository_id))
    try:
        branch = github_ops.push_branch(workspace, workflow.branch_name, target, payload.token)
    except github_ops.GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except github_ops.GitHubOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.add(GitOperation(workflow_id=workflow_id, operation="push", detail=f"{target.full_name}:{branch}", ref=branch, approved=True))
    session.commit()
    return {"status": "pushed", "branch": branch, "repository": target.full_name, "url": f"{target.url}/tree/{branch}"}


@router.post("/{workflow_id}/github/publish")
def publish_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    """Push the feature branch and open a pull request into main (never pushes main itself)."""
    from app.services.github import delivery

    try:
        return delivery.publish(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/pr/status")
def pr_status_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    """PR state, checks, conflicts, permission, and every reason it can't be merged yet."""
    from app.services.github import delivery

    try:
        return delivery.status(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/checks/{check_id}")
def check_details_endpoint(
    workflow_id: str, check_id: int, payload: GitHubTokenRequest, session: Session = Depends(get_session)
) -> dict:
    """What one CI check ran: steps, durations, output and individual test results."""
    from app.services.github import delivery

    try:
        return delivery.check_details(session, workflow_id, check_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/release/open")
def release_open_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    """Open the release PR: staging -> main."""
    from app.services.github import delivery

    try:
        return delivery.release_open(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/release/status")
def release_status_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.github import delivery

    try:
        return delivery.release_status(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/release/merge")
def release_merge_endpoint(workflow_id: str, payload: ReleaseMergeRequest, session: Session = Depends(get_session)) -> dict:
    """Release staging to main — only after it was run and verified, checks pass and it is approved."""
    from app.services.github import delivery

    try:
        return delivery.release_merge(
            session, workflow_id, payload.token.strip() or None, payload.approved, payload.verified_on_staging, payload.comment
        )
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/preview/start")
def preview_start_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    """Download the staging branch and run it locally so it can be checked."""
    from app.services.github import delivery

    try:
        return delivery.preview_start(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{workflow_id}/github/preview")
def preview_info_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.services.github import delivery

    try:
        return delivery.preview_info(session, workflow_id)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/preview/stop")
def preview_stop_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.services.github import delivery

    try:
        return delivery.preview_stop(session, workflow_id)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/preview/rollback")
def preview_rollback_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Switch the running site back to the previous release (zero downtime)."""
    from app.services.github import delivery

    try:
        return delivery.preview_rollback(session, workflow_id)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/update-branch")
def update_branch_endpoint(workflow_id: str, payload: GitHubTokenRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.github import delivery

    try:
        return delivery.update_branch(session, workflow_id, payload.token.strip() or None)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workflow_id}/github/merge")
def merge_endpoint(workflow_id: str, payload: MergeRequest, session: Session = Depends(get_session)) -> dict:
    """Merge the PR into main — only with explicit approval and after every check passes."""
    from app.services.github import delivery

    try:
        return delivery.merge(session, workflow_id, payload.token.strip() or None, payload.approved, payload.comment)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{workflow_id}/github/target")
def github_target_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Where push/PR/CI for this workflow go, so the UI can say so before acting."""
    from app.core.config import settings
    from app.services.github import github_ops

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    target = github_ops.resolve_target(session.get(Repository, workflow.repository_id))
    return {
        "configured": target is not None,
        "repository": target.full_name if target else None,
        "url": target.url if target else None,
        "source": target.source if target else None,
        "server_token": bool(settings.github_token),
        "branch": workflow.branch_name,
    }


@router.post("/{workflow_id}/github/pr")
def pr_endpoint(workflow_id: str, payload: PRApprovalRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.github import github_ops
    from app.services.guardrails import engine as guardrails

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    guardrails.record(session, workflow_id, guardrails.check_deployment_approval("external_github_action:pr", payload.approved))
    if not payload.approved:
        return {"status": "declined"}
    target = github_ops.resolve_target(session.get(Repository, workflow.repository_id))
    try:
        pr = github_ops.create_pull_request(
            target,
            workflow.branch_name,
            workflow.base_branch,
            payload.title or f"Intent2Deploy AI: {workflow.intent[:60]}",
            payload.body,
            payload.token,
        )
    except github_ops.GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except github_ops.GitHubOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.add(GitOperation(workflow_id=workflow_id, operation="pr_created", detail=pr.url, ref=str(pr.number), approved=True))
    session.commit()
    return {"status": "created", "url": pr.url, "number": pr.number}


@router.post("/{workflow_id}/github/ci")
def ci_status_endpoint(
    workflow_id: str, payload: CIStatusRequest | None = None, session: Session = Depends(get_session)
) -> dict:
    """Latest GitHub Actions result for this workflow's branch in its own repository."""
    from app.core.config import settings
    from app.services.github import github_ops

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    target = github_ops.resolve_target(session.get(Repository, workflow.repository_id))
    token = (payload.token if payload else "").strip()
    local = {"provider": "local", "url": "", "repository": target.full_name if target else None}
    if target is None:
        return {**local, "status": "not_linked", "detail": "This repository isn't linked to GitHub, so only LOCAL VALIDATION results are available."}
    if not workflow.branch_name:
        return {**local, "status": "not_committed", "detail": "Approve the commit first; there is no branch yet."}
    if not token and not settings.github_token:
        return {**local, "status": "needs_token", "detail": f"Enter a GitHub token to read Actions results from {target.full_name}."}
    try:
        ci = github_ops.get_branch_ci_status(target, workflow.branch_name, token)
    except github_ops.GitHubOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.add(
        CIRun(
            workflow_id=workflow_id,
            provider="github_actions",
            run_id=str(ci.run_id or ""),
            status=ci.state,
            url=ci.url,
            conclusion=ci.detail,
        )
    )
    session.commit()
    return {"provider": "github_actions", "status": ci.state, "detail": ci.detail, "url": ci.url, "repository": target.full_name}


@router.get("/{workflow_id}/file")
def workflow_file_endpoint(workflow_id: str, path: str, session: Session = Depends(get_session)) -> dict:
    """A file of the workflow's repository (path traversal, secret, binary and
    oversized files are refused)."""
    from app.services.repos import manager as rm

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None or not Path(repository.local_path).is_dir():
        raise HTTPException(status_code=404, detail="Repository not found.")
    try:
        return rm.read_file(Path(repository.local_path), path)
    except rm.RepoManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{workflow_id}/ci/workflows")
def ci_workflows_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """What CI runs for this project: its GitHub Actions workflows (when they
    run, their jobs and steps), read from the workflow's code."""
    import yaml

    from app.services.validation.sandbox import workspace_path

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    workspace = workspace_path(workflow_id)
    root = workspace if workspace.is_dir() else Path(repository.local_path) if repository else None
    found = []
    folder = root / ".github" / "workflows" if root else None
    for path in sorted(folder.glob("*.y*ml")) if folder and folder.is_dir() else []:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        on = data.get("on", data.get(True, {}))  # YAML 1.1 reads the key `on` as True
        on = {k: None for k in on} if isinstance(on, list) else ({on: None} if isinstance(on, str) else on or {})
        triggers = []
        for event, cfg in on.items():
            branches = (cfg or {}).get("branches") if isinstance(cfg, dict) else None
            triggers.append(f"{event} to {', '.join(branches)}" if branches else
                            "every pull request" if event == "pull_request" else str(event))
        jobs = []
        for job_id, job in (data.get("jobs") or {}).items():
            steps = [st.get("name") or st.get("uses") or (st.get("run") or "").splitlines()[0][:80]
                     for st in (job or {}).get("steps", []) if isinstance(st, dict)]
            jobs.append({"id": job_id, "name": (job or {}).get("name", job_id), "runs_on": (job or {}).get("runs-on", ""),
                         "steps": [x for x in steps if x]})
        found.append({"file": f".github/workflows/{path.name}", "name": data.get("name", path.stem),
                      "triggers": triggers, "jobs": jobs})
    return {"workflows": found}


@router.post("/{workflow_id}/complete", response_model=WorkflowResponse)
def complete_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> Workflow:
    return _wrap(orch.finalize_workflow, session, workflow_id)


@router.get("/{workflow_id}/events")
def get_events(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    events = session.exec(select(AuditEvent).where(AuditEvent.workflow_id == workflow_id).order_by(AuditEvent.timestamp)).all()
    return {
        "events": [
            {
                "event_type": e.event_type,
                "stage": e.stage,
                "message": e.message,
                "metadata": json.loads(e.metadata_json),
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ]
    }


@router.get("/{workflow_id}/evidence")
def get_evidence(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    docs = session.exec(select(RetrievedDocument).where(RetrievedDocument.workflow_id == workflow_id)).all()
    return {
        "evidence": [
            {
                "file": d.file,
                "start_line": d.start_line,
                "end_line": d.end_line,
                "score": d.score,
                "reason": d.reason,
                "chunk_type": d.chunk_type,
                "symbol": d.symbol,
                "retrieval_method": d.retrieval_method,
                "content_preview": d.content_preview,
            }
            for d in docs
        ]
    }


@router.get("/{workflow_id}/report")
def get_report(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.services.reporting import build_report

    return _wrap(build_report, session, workflow_id)


@router.get("/{workflow_id}/evaluation")
def get_workflow_evaluation(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Faculty-framework evaluation (7 fixed categories) for ONE workflow,
    derived deterministically from its persisted evidence — see
    app.services.workflow_evaluation. Distinct from the multi-task
    baseline-vs-Intent2Deploy benchmark served under /api/evaluation."""
    from app.services.workflow_evaluation import build_workflow_evaluation

    return _wrap(build_workflow_evaluation, session, workflow_id)


@router.get("/{workflow_id}/report.json")
def get_report_json_download(workflow_id: str, session: Session = Depends(get_session)):
    """Same trace as GET /report (single source of truth — see
    app.services.reporting), served as a downloadable attachment."""
    from fastapi.responses import JSONResponse

    from app.services.reporting import build_report

    trace = _wrap(build_report, session, workflow_id)
    filename = f"intent2deploy-workflow-{workflow_id}.json"
    return JSONResponse(content=trace, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{workflow_id}/report.md")
def get_report_markdown(workflow_id: str, session: Session = Depends(get_session)):
    from fastapi.responses import PlainTextResponse

    from app.services.reporting import build_report, report_to_markdown

    trace = _wrap(build_report, session, workflow_id)
    filename = f"intent2deploy-workflow-{workflow_id}.md"
    return PlainTextResponse(
        report_to_markdown(trace),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Production control-plane: architecture / risks / guardrails / chaos / readiness
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}/architecture")
def get_architecture_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    return _wrap(orch.get_architecture, session, workflow_id)


@router.post("/{workflow_id}/risks/analyze")
def run_risk_analysis_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    rows = _wrap(orch.run_risk_analysis, session, workflow_id)
    return {"risks": [_risk_to_dict(r) for r in rows]}


@router.get("/{workflow_id}/risks")
def get_risks_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.models.models import RiskItem

    rows = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    return {"risks": [_risk_to_dict(r) for r in rows]}


def _risk_to_dict(r) -> dict:
    return {
        "risk_id": r.risk_id,
        "title": r.title,
        "component": r.component,
        "severity": r.severity,
        "likelihood": r.likelihood,
        "blast_radius": r.blast_radius,
        "detection": r.detection,
        "mitigation": r.mitigation,
        "validation_method": r.validation_method,
        "status": r.status,
        "evidence": json.loads(r.evidence_json),
        "source": r.source,
    }


# NOTE: per-workflow guardrail results are served by app.api.guardrails
# (GET /api/guardrails/{workflow_id}) — not duplicated here.


@router.post("/{workflow_id}/chaos/run")
def run_chaos_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    rows = _wrap(orch.run_chaos_simulation, session, workflow_id)
    return {"experiments": [_chaos_to_dict(c) for c in rows]}


@router.get("/{workflow_id}/chaos")
def get_chaos_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.models.models import ChaosExperiment

    rows = session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id)).all()
    return {"experiments": [_chaos_to_dict(c) for c in rows]}


def _chaos_to_dict(c) -> dict:
    return {
        "experiment_id": c.experiment_id,
        "target": c.target,
        "hypothesis": c.hypothesis,
        "fault": c.fault,
        "expected_behavior": c.expected_behavior,
        "observed_behavior": c.observed_behavior,
        "result": c.result,
        "environment": c.environment,
        "evidence": json.loads(c.evidence_json),
        "timestamp": c.timestamp.isoformat(),
    }


@router.post("/{workflow_id}/readiness/assess")
def run_readiness_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    row = _wrap(orch.run_production_readiness, session, workflow_id)
    return _readiness_to_dict(row)


@router.get("/{workflow_id}/readiness")
def get_readiness_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.models.models import ProductionReadinessAssessment

    row = session.exec(
        select(ProductionReadinessAssessment)
        .where(ProductionReadinessAssessment.workflow_id == workflow_id)
        .order_by(ProductionReadinessAssessment.created_at.desc())
    ).first()
    if row is None:
        return {"decision": None, "reasons": [], "checklist": {}}
    return _readiness_to_dict(row)


def _readiness_to_dict(row) -> dict:
    return {
        "decision": row.decision,
        "reasons": json.loads(row.reasons_json),
        "checklist": json.loads(row.checklist_json),
        "created_at": row.created_at.isoformat(),
    }


@router.get("/{workflow_id}/pipeline")
def get_pipeline_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    from app.services.pipeline_view import build_pipeline

    return _wrap(build_pipeline, session, workflow_id)
