"""A minimal stand-in for an external payment provider's SDK client.

Deliberately simple (no real network I/O) so the demo repository stays
self-contained, but shaped like a real external dependency: it can raise
`PaymentProviderTimeout` to simulate the provider taking too long to
respond — the scenario used by the payment-reliability benchmark task
(evaluation/tasks/task_011.json) and the Resilience Lab's "Dependency
unavailable" / "HTTP timeout" chaos experiments.
"""
from __future__ import annotations

from dataclasses import dataclass


class PaymentProviderTimeout(Exception):
    """Raised when the external payment provider does not respond in time."""


@dataclass
class ProviderChargeResult:
    provider_charge_id: str
    amount: float
    status: str  # "succeeded" | "failed"


class PaymentProviderClient:
    """Real interface to an external payment provider. `should_timeout` is
    an injected test/simulation hook standing in for a real network
    timeout — production code would never take this parameter."""

    def charge(self, amount: float, *, should_timeout: bool = False) -> ProviderChargeResult:
        if should_timeout:
            raise PaymentProviderTimeout("Payment provider did not respond within the configured timeout.")
        charge_id = f"prov_{id(self)}_{amount}"
        return ProviderChargeResult(provider_charge_id=charge_id, amount=amount, status="succeeded")
