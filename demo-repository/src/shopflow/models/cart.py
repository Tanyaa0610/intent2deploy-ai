from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class CartItem:
    id: int
    cart_id: int
    product_id: int
    quantity: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CartItem":
        return cls(id=row["id"], cart_id=row["cart_id"], product_id=row["product_id"], quantity=row["quantity"])


@dataclass
class Cart:
    id: int
    user_id: int
    created_at: str
    updated_at: str
    items: list[CartItem]

    @classmethod
    def from_row(cls, row: sqlite3.Row, items: list[CartItem]) -> "Cart":
        return cls(id=row["id"], user_id=row["user_id"], created_at=row["created_at"], updated_at=row["updated_at"], items=items)
