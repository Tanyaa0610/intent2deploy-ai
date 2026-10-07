"""Payment processing: charges orders through PaymentProviderClient.

This module is deliberately the most "unfinished" part of ShopFlow — it
is the target of several evaluation tasks that reason about changes
spanning `payment_service.py` -> `integrations/payment_provider.py` ->
`order_service.py`:

- BUG (task_011.json / task_012.json): `charge_order` takes no
  idempotency key, so calling it twice for the same order (e.g. a
  client retry after a provider timeout) creates two separate charges
  instead of returning the original result. The `payments.idempotency_key`
  column already exists in the schema, unused.
- BUG (task_016.json): a provider timeout is recorded as an immediate
  FAILED payment with no retry — see `integrations/payment_provider.py`
  for the injectable `should_timeout` simulation hook.
- GAP (task_017.json): failures are not yet logged through
  `utils/logging.py`'s structured, redacting logger.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.integrations.payment_provider import (
    PaymentProviderClient,
    PaymentProviderDeclined,
    PaymentProviderTimeout,
)
from src.shopflow.models.enums import PaymentStatus
from src.shopflow.models.payment import Payment
from src.shopflow.services.notification_service import NotificationService
from src.shopflow.services.order_service import OrderService


class PaymentService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: PaymentProviderClient | None = None,
        order_service: OrderService | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.conn = conn
        self._provider = provider or PaymentProviderClient()
        self.orders = order_service or OrderService(conn)
        self.notifications = notification_service or NotificationService(conn)

    def charge_order(
        self, order_id: int, amount: float, *, should_timeout: bool = False, should_decline: bool = False
    ) -> Payment:
        """Charge `order_id` for `amount` via the external payment
        provider and move the order to CONFIRMED or FAILED accordingly.
        See module docstring for the known gaps this method has."""
        self.orders.mark_payment_pending(order_id)

        try:
            result = self._provider.charge(amount, should_timeout=should_timeout, should_decline=should_decline)
        except (PaymentProviderTimeout, PaymentProviderDeclined) as exc:
            payment = self._record_payment(order_id, amount, PaymentStatus.FAILED, provider_charge_id=None)
            self.orders.apply_payment_result(order_id, payment)
            self.notifications.notify_payment_failed(order_id, str(exc))
            return payment

        payment = self._record_payment(order_id, amount, PaymentStatus.CAPTURED, provider_charge_id=result.provider_charge_id)
        self.orders.apply_payment_result(order_id, payment)
        self.notifications.notify_payment_succeeded(order_id, payment.id, amount)
        return payment

    def _record_payment(
        self, order_id: int, amount: float, status: PaymentStatus, provider_charge_id: str | None
    ) -> Payment:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO payments (order_id, amount, status, provider_charge_id, idempotency_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (order_id, amount, status.value, provider_charge_id, now, now),
        )
        self.conn.commit()
        return self.get_by_id(cur.lastrowid)

    def get_by_id(self, payment_id: int) -> Payment:
        row = self.conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            from src.shopflow.exceptions import NotFoundError

            raise NotFoundError(f"Payment {payment_id} not found")
        return Payment.from_row(row)

    def get_payments_for_order(self, order_id: int) -> list[Payment]:
        rows = self.conn.execute("SELECT * FROM payments WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
        return [Payment.from_row(r) for r in rows]

    def total_captured_for_payment(self, payment_id: int) -> float:
        payment = self.get_by_id(payment_id)
        return payment.amount if payment.status == PaymentStatus.CAPTURED.value else 0.0
