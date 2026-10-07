"""Audit logging for security- and business-relevant actions.

Every call goes through `redact()` before being persisted, so passwords,
hashes, tokens, and similar secrets never land in the audit trail — see
`utils/logging.py`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from src.shopflow.models.audit import AuditEvent
from src.shopflow.utils.logging import get_logger, redact

_logger = get_logger("audit")


class AuditService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(self, actor_user_id: int | None, action: str, details: dict | None = None) -> AuditEvent:
        safe_details = redact(details or {})
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO audit_events (actor_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (actor_user_id, action, json.dumps(safe_details), now),
        )
        self.conn.commit()
        _logger.info(action, extra={"fields": {"actor_user_id": actor_user_id, **safe_details}})
        row = self.conn.execute("SELECT * FROM audit_events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return AuditEvent.from_row(row)

    def list_events(self, limit: int = 100) -> list[AuditEvent]:
        rows = self.conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [AuditEvent.from_row(r) for r in rows]
