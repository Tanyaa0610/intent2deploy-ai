from __future__ import annotations

from pydantic import BaseModel


class RefundCreateRequest(BaseModel):
    payment_id: int
    amount: float
    reason: str = ""


class RefundResponse(BaseModel):
    id: int
    payment_id: int
    amount: float
    status: str
    reason: str
    created_at: str
