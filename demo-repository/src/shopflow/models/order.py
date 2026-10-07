from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class OrderItem:
    id: int
    order_id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderItem":
        return cls(
            id=row["id"],
            order_id=row["order_id"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            quantity=row["quantity"],
            unit_price=row["unit_price"],
        )


@dataclass
class Order:
    id: int
    user_id: int
    status: str
    total: float
    created_at: str
    updated_at: str
    items: list[OrderItem]

    @classmethod
    def from_row(cls, row: sqlite3.Row, items: list[OrderItem]) -> "Order":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            total=row["total"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            items=items,
        )
