"""Refund processing.

GAP (task_020.json): refund eligibility only checks the refund amount
against the payment's captured amount — it does not check that the
payment actually reached CAPTURED status, so a refund can incorrectly
be issued against a FAILED or still-PENDING payment.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import ConflictError, NotFoundError, ValidationFailedError
from src.shopflow.models.enums import RefundStatus
from src.shopflow.models.payment import Refund
from src.shopflow.services.notification_service import NotificationService
from src.shopflow.services.payment_service import PaymentService


class RefundService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        payment_service: PaymentService | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.conn = conn
        self.payments = payment_service or PaymentService(conn)
        self.notifications = notification_service or NotificationService(conn)

    def create_refund(self, payment_id: int, amount: float, reason: str = "") -> Refund:
        if amount <= 0:
            raise ValidationFailedError("Refund amount must be positive")
        payment = self.payments.get_by_id(payment_id)

        already_refunded = self._total_refunded(payment_id)
        remaining = round(payment.amount - already_refunded, 2)
        # NOTE: does not check `payment.status` — see module docstring.
        if amount > remaining:
            raise ConflictError(
                f"Refund amount {amount} exceeds the remaining refundable amount ({remaining}) for payment {payment_id}"
            )

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO refunds (payment_id, amount, status, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (payment_id, amount, RefundStatus.COMPLETED.value, reason, now),
        )
        self.conn.commit()
        refund = self.get_by_id(cur.lastrowid)
        self.notifications.notify_refund_completed(payment_id, refund.id, amount)
        return refund

    def get_by_id(self, refund_id: int) -> Refund:
        row = self.conn.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Refund {refund_id} not found")
        return Refund.from_row(row)

    def list_for_payment(self, payment_id: int) -> list[Refund]:
        rows = self.conn.execute("SELECT * FROM refunds WHERE payment_id = ? ORDER BY id", (payment_id,)).fetchall()
        return [Refund.from_row(r) for r in rows]

    def _total_refunded(self, payment_id: int) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE payment_id = ? AND status = ?",
            (payment_id, RefundStatus.COMPLETED.value),
        ).fetchone()
        return row["total"]
