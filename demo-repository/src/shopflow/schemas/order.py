from __future__ import annotations

from pydantic import BaseModel


class OrderItemResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    total: float
    items: list[OrderItemResponse]
    created_at: str
    updated_at: str


class OrderStatusUpdateRequest(BaseModel):
    status: str
