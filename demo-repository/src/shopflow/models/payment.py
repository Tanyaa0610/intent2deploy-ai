from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Payment:
    id: int
    order_id: int
    amount: float
    status: str
    provider_charge_id: str | None
    idempotency_key: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Payment":
        return cls(
            id=row["id"],
            order_id=row["order_id"],
            amount=row["amount"],
            status=row["status"],
            provider_charge_id=row["provider_charge_id"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Refund:
    id: int
    payment_id: int
    amount: float
    status: str
    reason: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Refund":
        return cls(
            id=row["id"],
            payment_id=row["payment_id"],
            amount=row["amount"],
            status=row["status"],
            reason=row["reason"],
            created_at=row["created_at"],
        )
