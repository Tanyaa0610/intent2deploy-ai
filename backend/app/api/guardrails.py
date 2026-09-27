"""AI-DevOps Guardrail Control Plane API (Part 8 of the guardrail rework).

Serves the 8-category guardrail system exclusively — SECURITY,
INFRASTRUCTURE, CI_CD, DEPLOYMENT, COST, AI_LLM, INPUT, OUTPUT. There is no
parallel old-schema endpoint kept alongside this one.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.enums import GuardrailAction, GuardrailCategory, GuardrailStatus
from app.models.models import GuardrailCheck, Workflow
from app.services.audit import log_event
from app.services.guardrails.engine import GUARDRAIL_CATALOG

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])


def _check_to_dict(c: GuardrailCheck) -> dict:
    return {
        "id": c.id,
        "workflow_id": c.workflow_id,
        "guardrail_id": c.guardrail_id,
        "category": c.category,
        "name": c.name,
        "description": c.description,
        "purpose": c.purpose,
        "trigger_condition": c.trigger_condition,
        "enforcement_point": c.enforcement_point,
        "severity": c.severity,
        "status": c.status,
        "action": c.action,
        "evidence": json.loads(c.evidence_json),
        "remediation": c.remediation,
        "configurable_threshold": c.configurable_threshold,
        "enabled": c.enabled,
        "created_at": c.created_at.isoformat(),
        "evaluated_at": c.evaluated_at.isoformat(),
    }


@router.get("")
def get_catalog(category: str | None = None) -> dict:
    """The full guardrail definition catalog (not tied to a workflow)."""
    items = GUARDRAIL_CATALOG
    if category:
        items = [g for g in items if g["category"] == category.upper()]
    return {"categories": [c.value for c in GuardrailCategory], "guardrails": items}


@router.get("/{workflow_id}")
def get_workflow_guardrails(
    workflow_id: str,
    category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    checkpoint: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id).order_by(GuardrailCheck.evaluated_at)
    if category:
        stmt = stmt.where(GuardrailCheck.category == category.upper())
    if severity:
        stmt = stmt.where(GuardrailCheck.severity == severity.upper())
    if status:
        stmt = stmt.where(GuardrailCheck.status == status.upper())
    if checkpoint:
        stmt = stmt.where(GuardrailCheck.enforcement_point == checkpoint)
    rows = session.exec(stmt).all()
    return {"guardrails": [_check_to_dict(r) for r in rows]}


@router.get("/{workflow_id}/summary")
def get_workflow_summary(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    rows = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id)).all()
    categories: dict[str, dict[str, int]] = {
        c.value: {"total": 0, "passed": 0, "warnings": 0, "blocked": 0, "failed": 0, "not_applicable": 0, "not_implemented": 0}
        for c in GuardrailCategory
    }
    for r in rows:
        bucket = categories.setdefault(r.category, {"total": 0, "passed": 0, "warnings": 0, "blocked": 0, "failed": 0, "not_applicable": 0, "not_implemented": 0})
        bucket["total"] += 1
        key = {
            GuardrailStatus.PASSED.value: "passed",
            GuardrailStatus.WARNING.value: "warnings",
            GuardrailStatus.BLOCKED.value: "blocked",
            GuardrailStatus.FAILED.value: "failed",
            GuardrailStatus.NOT_APPLICABLE.value: "not_applicable",
            GuardrailStatus.NOT_IMPLEMENTED.value: "not_implemented",
        }.get(r.status)
        if key:
            bucket[key] += 1
    return {
        "has_data": bool(rows),
        "categories": categories,
        "approval_required": sum(1 for r in rows if r.action == GuardrailAction.REQUIRE_APPROVAL.value),
    }


@router.get("/{workflow_id}/timeline")
def get_workflow_timeline(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    rows = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id).order_by(GuardrailCheck.evaluated_at)).all()
    return {
        "timeline": [
            {
                "guardrail_id": r.guardrail_id,
                "category": r.category,
                "name": r.name,
                "enforcement_point": r.enforcement_point,
                "status": r.status,
                "action": r.action,
                "severity": r.severity,
                "reason": r.trigger_condition,
                "evidence": json.loads(r.evidence_json),
                "remediation": r.remediation,
                "approval_required": r.action == GuardrailAction.REQUIRE_APPROVAL.value,
                "evaluated_at": r.evaluated_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/{workflow_id}/evaluate")
def evaluate_workflow_guardrails(workflow_id: str, session: Session = Depends(get_session)) -> dict:
    """Re-evaluate the guardrails whose inputs are current workflow state
    (not tied to a specific pipeline stage that must be re-run) — cost
    budget, repair-loop budget, and environment isolation."""
    from app.services.guardrails import engine as guardrails

    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")

    results = [
        guardrails.check_environment_verification("on_demand_evaluate", workflow.environment.value),
        guardrails.check_production_block("on_demand_evaluate", workflow.environment.value),
        guardrails.check_llm_call_limit("on_demand_evaluate", workflow.llm_call_count),
        guardrails.check_llm_token_limit("on_demand_evaluate", workflow.llm_estimated_tokens),
        guardrails.check_workflow_budget("on_demand_evaluate", workflow.llm_estimated_cost_usd),
        guardrails.check_repair_loop_limit("on_demand_evaluate", workflow.repair_attempts, guardrail_id="AI-08", category=guardrails.CAT.AI_LLM.value, name="Retry/Repair Limit"),
    ]
    rows = [guardrails.record(session, workflow_id, r) for r in results]
    return {"evaluated": [_check_to_dict(r) for r in rows]}


class ApproveGuardrailRequest(BaseModel):
    check_id: str
    approved: bool
    comment: str = ""


@router.post("/{workflow_id}/approve")
def approve_guardrail(workflow_id: str, payload: ApproveGuardrailRequest, session: Session = Depends(get_session)) -> dict:
    row = session.get(GuardrailCheck, payload.check_id)
    if row is None or row.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail=f"Guardrail check '{payload.check_id}' not found for workflow '{workflow_id}'.")
    if row.action != GuardrailAction.REQUIRE_APPROVAL.value:
        raise HTTPException(status_code=400, detail=f"Guardrail check '{payload.check_id}' does not require approval (action={row.action}).")

    row.status = GuardrailStatus.PASSED.value if payload.approved else GuardrailStatus.BLOCKED.value
    row.action = GuardrailAction.ALLOW.value if payload.approved else GuardrailAction.BLOCK.value
    row.remediation = payload.comment or row.remediation
    session.add(row)
    session.commit()
    session.refresh(row)

    log_event(
        session,
        workflow_id,
        "GUARDRAIL_APPROVAL_DECISION",
        stage=row.enforcement_point,
        message=payload.comment,
        metadata={"guardrail_id": row.guardrail_id, "approved": payload.approved},
    )
    return _check_to_dict(row)
