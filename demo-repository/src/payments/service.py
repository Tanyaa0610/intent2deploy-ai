"""Payment service: charges orders through PaymentProviderClient.

Contains a deliberate reliability gap used by the "fix duplicate orders on
payment-provider timeout" benchmark task
(evaluation/tasks/task_011.json): `charge_order` has no idempotency
protection, so a client retry after a provider timeout (or a duplicated
request) can create two separate provider charges for the same order.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.payments.provider_client import PaymentProviderClient


@dataclass
class Charge:
    order_id: int
    amount: float
    provider_charge_id: str


class PaymentService:
    def __init__(self, provider: PaymentProviderClient | None = None) -> None:
        self._provider = provider or PaymentProviderClient()
        self._charges: list[Charge] = []

    def charge_order(self, order_id: int, amount: float, *, should_timeout: bool = False) -> Charge:
        """Charge `order_id` for `amount` via the external payment provider.

        BUG: no idempotency key is used, so calling this twice for the same
        order_id (e.g. because a client retried after a timeout, or the
        request was duplicated) creates two separate charges instead of
        returning the original result.
        """
        result = self._provider.charge(amount, should_timeout=should_timeout)
        charge = Charge(order_id=order_id, amount=amount, provider_charge_id=result.provider_charge_id)
        self._charges.append(charge)
        return charge

    def charges_for_order(self, order_id: int) -> list[Charge]:
        return [c for c in self._charges if c.order_id == order_id]
