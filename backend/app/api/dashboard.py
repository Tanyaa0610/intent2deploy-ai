"""Dashboard home KPIs (Part A1). Every number is computed from real
persisted rows; an empty system reports `null`, never a fabricated 0%."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.enums import WorkflowState
from app.models.models import GuardrailCheck, ProductionReadinessAssessment, Project, Repository, Workflow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

TERMINAL_STATES = {WorkflowState.COMPLETED, WorkflowState.FAILED}

# Human-readable next-action labels keyed by workflow state
_NEXT_ACTIONS: dict[str, str] = {
    "AWAITING_PLAN_APPROVAL": "Review & approve plan",
    "AWAITING_CHANGE_APPROVAL": "Review & approve changes",
    "AWAITING_COMMIT_APPROVAL": "Approve commit",
    "REPAIRING": "Review repair proposal",
    "VALIDATION_FAILED": "Diagnose & repair",
    "PLAN_REJECTED": "Regenerate plan",
    "CHANGES_REJECTED": "Regenerate changes",
    "CREATED": "Start indexing",
    "INDEXED": "Generate plan",
    "COMMITTED": "Finalize workflow",
}


@router.get("/summary")
def get_dashboard_summary(session: Session = Depends(get_session)) -> dict:
    workflows = session.exec(select(Workflow)).all()
    if not workflows:
        return {
            "active_workflows": 0,
            "completed_workflows": 0,
            "failed_workflows": 0,
            "awaiting_approval": 0,
            "validation_pass_rate": None,
            "production_readiness": None,
            "human_interventions": 0,
            "guardrail_violations": 0,
            "avg_execution_time_ms": None,
            "avg_repair_attempts": None,
            "has_data": False,
        }

    active = [w for w in workflows if w.state not in TERMINAL_STATES]
    completed = [w for w in workflows if w.state == WorkflowState.COMPLETED]
    failed = [w for w in workflows if w.state == WorkflowState.FAILED]
    awaiting = [w for w in workflows if "AWAITING" in w.state.value]

    validations = session.exec(select(GuardrailCheck).where(GuardrailCheck.guardrail_id == "CICD-01")).all()
    validation_pass_rate = round(sum(1 for v in validations if v.status == "PASSED") / len(validations), 3) if validations else None

    readiness_rows = session.exec(select(ProductionReadinessAssessment)).all()
    readiness_dist = {"READY": 0, "READY_WITH_WARNINGS": 0, "NOT_READY": 0}
    for r in readiness_rows:
        readiness_dist[r.decision] = readiness_dist.get(r.decision, 0) + 1
    production_readiness = readiness_dist if readiness_rows else None

    guardrail_checks = session.exec(select(GuardrailCheck)).all()
    guardrail_violations = sum(1 for g in guardrail_checks if g.status in ("BLOCKED", "FAILED"))

    timed = [w for w in workflows if w.total_ms]
    avg_execution_time_ms = round(sum(w.total_ms for w in timed) / len(timed)) if timed else None

    avg_repair_attempts = round(sum(w.repair_attempts for w in workflows) / len(workflows), 2) if workflows else None

    return {
        "active_workflows": len(active),
        "completed_workflows": len(completed),
        "failed_workflows": len(failed),
        "awaiting_approval": len(awaiting),
        "validation_pass_rate": validation_pass_rate,
        "production_readiness": production_readiness,
        "human_interventions": sum(w.human_intervention_count for w in workflows),
        "guardrail_violations": guardrail_violations,
        "avg_execution_time_ms": avg_execution_time_ms,
        "avg_repair_attempts": avg_repair_attempts,
        "has_data": True,
    }


@router.get("/attention")
def get_attention_items(session: Session = Depends(get_session)) -> dict:
    """Returns workflows that need immediate human attention, ordered by urgency."""
    workflows = session.exec(
        select(Workflow).order_by(Workflow.updated_at.desc())
    ).all()

    projects = {p.id: p for p in session.exec(select(Project)).all()}
    repos = {r.id: r for r in session.exec(select(Repository)).all()}

    # Priority ordering: approvals first, then failures, then running, then recent
    priority_order = [
        "AWAITING_PLAN_APPROVAL",
        "AWAITING_CHANGE_APPROVAL",
        "AWAITING_COMMIT_APPROVAL",
        "REPAIRING",
        "VALIDATION_FAILED",
        "PLAN_REJECTED",
        "CHANGES_REJECTED",
        "FAILED",
        "CREATED",
        "INDEXED",
        "COMMITTED",
    ]

    def sort_key(w: Workflow) -> tuple:
        try:
            state_val = w.state.value if hasattr(w.state, "value") else str(w.state)
            pri = priority_order.index(state_val)
        except ValueError:
            pri = 99
        return (pri,)

    attention_states = set(priority_order)
    attention_wfs = [
        w for w in workflows
        if (w.state.value if hasattr(w.state, "value") else str(w.state)) in attention_states
    ]
    attention_wfs.sort(key=sort_key)

    # Recent completed (last 5)
    recent_completed = [w for w in workflows if w.state == WorkflowState.COMPLETED][:5]

    def _fmt(w: Workflow) -> dict:
        state_str = w.state.value if hasattr(w.state, "value") else str(w.state)
        return {
            "id": w.id,
            "intent": w.intent,
            "state": state_str,
            "project_name": projects.get(w.project_id, {}).name if projects.get(w.project_id) else w.project_id,
            "repository_name": (repos.get(w.repository_id, {}).source or "").split("/")[-1] if repos.get(w.repository_id) else w.repository_id,
            "updated_at": w.updated_at.isoformat(),
            "repair_attempts": w.repair_attempts,
            "human_intervention_count": w.human_intervention_count,
            "awaiting_action": _NEXT_ACTIONS.get(state_str),
        }

    return {
        "attention": [_fmt(w) for w in attention_wfs[:10]],
        "recent_completed": [_fmt(w) for w in recent_completed],
    }

    workflows = session.exec(select(Workflow)).all()
    if not workflows:
        return {
            "active_workflows": 0,
            "completed_workflows": 0,
            "validation_pass_rate": None,
            "production_readiness": None,
            "human_interventions": 0,
            "guardrail_violations": 0,
            "avg_execution_time_ms": None,
            "avg_repair_attempts": None,
            "has_data": False,
        }

    active = [w for w in workflows if w.state not in TERMINAL_STATES]
    completed = [w for w in workflows if w.state == WorkflowState.COMPLETED]

    validations = session.exec(select(GuardrailCheck).where(GuardrailCheck.guardrail_id == "CICD-01")).all()
    validation_pass_rate = round(sum(1 for v in validations if v.status == "PASSED") / len(validations), 3) if validations else None

    readiness_rows = session.exec(select(ProductionReadinessAssessment)).all()
    readiness_dist = {"READY": 0, "READY_WITH_WARNINGS": 0, "NOT_READY": 0}
    for r in readiness_rows:
        readiness_dist[r.decision] = readiness_dist.get(r.decision, 0) + 1
    production_readiness = readiness_dist if readiness_rows else None

    guardrail_checks = session.exec(select(GuardrailCheck)).all()
    guardrail_violations = sum(1 for g in guardrail_checks if g.status in ("BLOCKED", "FAILED"))

    timed = [w for w in workflows if w.total_ms]
    avg_execution_time_ms = round(sum(w.total_ms for w in timed) / len(timed)) if timed else None

    avg_repair_attempts = round(sum(w.repair_attempts for w in workflows) / len(workflows), 2) if workflows else None

    return {
        "active_workflows": len(active),
        "completed_workflows": len(completed),
        "validation_pass_rate": validation_pass_rate,
        "production_readiness": production_readiness,
        "human_interventions": sum(w.human_intervention_count for w in workflows),
        "guardrail_violations": guardrail_violations,
        "avg_execution_time_ms": avg_execution_time_ms,
        "avg_repair_attempts": avg_repair_attempts,
        "has_data": True,
    }
