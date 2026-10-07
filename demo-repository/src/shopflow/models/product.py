from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Product:
    id: int
    sku: str
    name: str
    description: str
    price: float
    category: str
    inventory_quantity: int
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Product":
        return cls(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            description=row["description"],
            price=row["price"],
            category=row["category"],
            inventory_quantity=row["inventory_quantity"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
