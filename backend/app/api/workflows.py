from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_provider, get_session
from app.models.models import (
    AuditEvent,
    GeneratedTest,
    GitOperation,
    Plan,
    ProposedChange,
    RepairAttempt,
    RetrievedDocument,
    ValidationResult,
    Workflow,
)
from app.schemas.api import (
    ApprovalRequest,
    CreateWorkflowRequest,
    PRApprovalRequest,
    PushApprovalRequest,
    RepairApprovalRequest,
    WorkflowResponse,
)
from app.services import orchestrator as orch
from app.services.evaluation.automation_provider import AutomationProviderUnavailableError, GitHubActionsProvider
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
    workspace = workspace_path(workflow_id)
    try:
        branch = github_ops.push_branch(workspace, workflow.branch_name)
    except github_ops.GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except github_ops.GitHubOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.add(GitOperation(workflow_id=workflow_id, operation="push", detail=branch, ref=branch, approved=True))
    session.commit()
    return {"status": "pushed", "branch": branch}


@router.post("/{workflow_id}/github/pr")
def pr_endpoint(workflow_id: str, payload: PRApprovalRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.github import github_ops
    from app.services.guardrails import engine as guardrails

    workflow = _wrap(orch.get_workflow, session, workflow_id)
    guardrails.record(session, workflow_id, guardrails.check_deployment_approval("external_github_action:pr", payload.approved))
    if not payload.approved:
        return {"status": "declined"}
    try:
        pr = github_ops.create_pull_request(
            workflow.branch_name, workflow.base_branch, payload.title or f"Intent2Deploy AI: {workflow.intent[:60]}", payload.body
        )
    except github_ops.GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except github_ops.GitHubOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.add(GitOperation(workflow_id=workflow_id, operation="pr_created", detail=pr.url, ref=str(pr.number), approved=True))
    session.commit()
    return {"status": "created", "url": pr.url, "number": pr.number}


@router.post("/{workflow_id}/github/ci")
def ci_status_endpoint(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    provider = GitHubActionsProvider()
    workflow = _wrap(orch.get_workflow, session, workflow_id)
    if not provider.is_available():
        return {"provider": "local", "status": "not_configured", "detail": "GitHub Actions is not configured; only LOCAL VALIDATION results are available."}
    try:
        result = provider.trigger(workflow_id, workflow.branch_name)
    except AutomationProviderUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": result.provider, "status": result.status, "detail": result.detail, "url": result.url}


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
