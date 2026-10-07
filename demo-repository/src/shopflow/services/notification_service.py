"""Local notification service.

No real email/SMS integration — each "notification" is a structured
event persisted to the `notifications` table (and returned to the
caller), which is enough to assert on in tests and to show in the API/UI
without external infrastructure.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from src.shopflow.models.audit import Notification
from src.shopflow.models.enums import NotificationType


class NotificationService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _emit(self, event_type: NotificationType, payload: dict) -> Notification:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO notifications (event_type, payload, created_at) VALUES (?, ?, ?)",
            (event_type.value, json.dumps(payload), now),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
        return Notification.from_row(row)

    def notify_user_registered(self, user_id: int, username: str) -> Notification:
        return self._emit(NotificationType.USER_REGISTERED, {"user_id": user_id, "username": username})

    def notify_order_created(self, order_id: int, user_id: int, total: float) -> Notification:
        return self._emit(NotificationType.ORDER_CREATED, {"order_id": order_id, "user_id": user_id, "total": total})

    def notify_payment_succeeded(self, order_id: int, payment_id: int, amount: float) -> Notification:
        return self._emit(NotificationType.PAYMENT_SUCCEEDED, {"order_id": order_id, "payment_id": payment_id, "amount": amount})

    def notify_payment_failed(self, order_id: int, reason: str) -> Notification:
        return self._emit(NotificationType.PAYMENT_FAILED, {"order_id": order_id, "reason": reason})

    def notify_low_inventory(self, product_id: int, sku: str, quantity: int, threshold: int) -> Notification:
        return self._emit(
            NotificationType.LOW_INVENTORY,
            {"product_id": product_id, "sku": sku, "quantity": quantity, "threshold": threshold},
        )

    def notify_refund_completed(self, payment_id: int, refund_id: int, amount: float) -> Notification:
        return self._emit(NotificationType.REFUND_COMPLETED, {"payment_id": payment_id, "refund_id": refund_id, "amount": amount})

    def list_notifications(self, event_type: NotificationType | None = None, limit: int = 100) -> list[Notification]:
        if event_type is not None:
            rows = self.conn.execute(
                "SELECT * FROM notifications WHERE event_type = ? ORDER BY id DESC LIMIT ?", (event_type.value, limit)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Notification.from_row(r) for r in rows]
