"""A minimal stand-in for an external payment provider's SDK client.

No real network I/O, so the repository stays self-contained — but shaped
like a real external dependency: `charge()` can raise
`PaymentProviderTimeout` to simulate the provider taking too long to
respond, which is the scenario `PaymentService.charge_order` (and the
Resilience Lab's "dependency unavailable" / "HTTP timeout" chaos
experiments) reason about. `should_timeout` is a simulation hook —
production code calling a real provider would never pass this.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass


class PaymentProviderTimeout(Exception):
    """Raised when the external payment provider does not respond in time."""


class PaymentProviderDeclined(Exception):
    """Raised when the provider actively declines the charge (not a
    timeout) — e.g. the simulated card is rejected."""


@dataclass
class ProviderChargeResult:
    provider_charge_id: str
    amount: float
    status: str  # "succeeded" | "failed"


class PaymentProviderClient:
    """Real interface to an external payment provider."""

    def charge(self, amount: float, *, should_timeout: bool = False, should_decline: bool = False) -> ProviderChargeResult:
        if should_timeout:
            raise PaymentProviderTimeout("Payment provider did not respond within the configured timeout.")
        if should_decline:
            raise PaymentProviderDeclined("Payment provider declined the charge.")
        charge_id = f"prov_{uuid.uuid4().hex[:16]}"
        return ProviderChargeResult(provider_charge_id=charge_id, amount=amount, status="succeeded")
