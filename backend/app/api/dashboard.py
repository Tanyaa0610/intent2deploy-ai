"""Dashboard home KPIs (Part A1). Every number is computed from real
persisted rows; an empty system reports `null`, never a fabricated 0%."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.enums import WorkflowState
from app.models.models import GuardrailCheck, ProductionReadinessAssessment, Workflow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

TERMINAL_STATES = {WorkflowState.COMPLETED, WorkflowState.FAILED}


@router.get("/summary")
def get_dashboard_summary(session: Session = Depends(get_session)) -> dict:
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
