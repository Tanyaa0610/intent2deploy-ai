from __future__ import annotations

import json

from sqlmodel import Session

from app.models.models import AuditEvent


def log_event(
    session: Session,
    workflow_id: str,
    event_type: str,
    stage: str = "",
    message: str = "",
    metadata: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workflow_id=workflow_id,
        event_type=event_type,
        stage=stage,
        message=message,
        metadata_json=json.dumps(metadata or {}),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
