"""Alerts and live deployment monitoring."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import Session

from app.services import alerts, preview

router = APIRouter(tags=["alerts"])


def _row(a) -> dict:  # noqa: ANN001
    return {"id": a.id, "severity": a.severity, "source": a.source, "deployment": a.deployment,
            "workflow_id": a.workflow_id, "title": a.title, "detail": a.detail, "acknowledged": a.acknowledged,
            "delivered_to": a.delivered_to, "created_at": a.created_at.isoformat() + "Z"}


@router.get("/api/alerts")
def list_alerts(open_only: bool = False, limit: int = 100) -> dict:
    with Session(alerts._engine()) as session:
        rows = alerts.list_alerts(session, limit=min(max(limit, 1), 500), open_only=open_only)
        return {"alerts": [_row(a) for a in rows], "open": alerts.open_counts(session)}


@router.post("/api/alerts/{alert_id}/ack")
def acknowledge(alert_id: str) -> dict:
    with Session(alerts._engine()) as session:
        if alerts.acknowledge(session, alert_id) == 0:
            raise HTTPException(status_code=404, detail="No open alert with that id.")
        return {"acknowledged": 1, "open": alerts.open_counts(session)}


@router.post("/api/alerts/ack-all")
def acknowledge_all() -> dict:
    with Session(alerts._engine()) as session:
        return {"acknowledged": alerts.acknowledge(session), "open": alerts.open_counts(session)}


@router.get("/api/deployments")
def deployments() -> dict:
    """Every running deployment with its live/standby status and monitor stats."""
    return {"deployments": preview.all_deployments()}
