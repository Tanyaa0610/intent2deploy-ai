from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class AuditEvent:
    id: int
    actor_user_id: int | None
    action: str
    details: str  # JSON-encoded, already redacted before being stored
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AuditEvent":
        return cls(
            id=row["id"],
            actor_user_id=row["actor_user_id"],
            action=row["action"],
            details=row["details"],
            created_at=row["created_at"],
        )


@dataclass
class Notification:
    id: int
    event_type: str
    payload: str  # JSON-encoded
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Notification":
        return cls(id=row["id"], event_type=row["event_type"], payload=row["payload"], created_at=row["created_at"])
