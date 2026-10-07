from __future__ import annotations

from pydantic import BaseModel


class CartItemAddRequest(BaseModel):
    product_id: int
    quantity: int


class CartItemUpdateRequest(BaseModel):
    quantity: int


class CartItemResponse(BaseModel):
    product_id: int
    quantity: int


class CartResponse(BaseModel):
    id: int
    user_id: int
    items: list[CartItemResponse]
    subtotal: float
