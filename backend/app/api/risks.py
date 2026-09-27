"""Production Risk Dashboard (Part C) — aggregates real RiskItem rows
across every workflow."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.models import RiskItem, Workflow

router = APIRouter(prefix="/api/risks", tags=["risks"])


@router.get("/summary")
def get_summary(session: Session = Depends(get_session)) -> dict:
    risks = session.exec(select(RiskItem)).all()
    if not risks:
        return {
            "total": 0,
            "by_severity": None,
            "by_component": None,
            "open": 0,
            "mitigated": 0,
            "accepted": 0,
            "has_data": False,
        }
    by_severity: dict[str, int] = {}
    by_component: dict[str, int] = {}
    for r in risks:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_component[r.component or "general"] = by_component.get(r.component or "general", 0) + 1
    return {
        "total": len(risks),
        "by_severity": by_severity,
        "by_component": by_component,
        "open": sum(1 for r in risks if r.status == "OPEN"),
        "mitigated": sum(1 for r in risks if r.status == "MITIGATED"),
        "accepted": sum(1 for r in risks if r.status == "ACCEPTED"),
        "has_data": True,
    }


@router.get("")
def list_risks(session: Session = Depends(get_session)) -> dict:
    workflows_by_id = {w.id: w for w in session.exec(select(Workflow)).all()}
    risks = session.exec(select(RiskItem).order_by(RiskItem.created_at.desc())).all()
    return {
        "risks": [
            {
                "workflow_id": r.workflow_id,
                "workflow_intent": workflows_by_id[r.workflow_id].intent[:80] if r.workflow_id in workflows_by_id else "",
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
            for r in risks
        ]
    }
