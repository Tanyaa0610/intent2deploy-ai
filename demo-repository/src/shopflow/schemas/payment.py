from __future__ import annotations

from pydantic import BaseModel


class PaymentChargeRequest(BaseModel):
    order_id: int
    amount: float
    should_timeout: bool = False
    should_decline: bool = False


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    amount: float
    status: str
    provider_charge_id: str | None
    created_at: str
    updated_at: str
