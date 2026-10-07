"""Product catalog management."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import ConflictError, NotFoundError, ValidationFailedError
from src.shopflow.models.product import Product
from src.shopflow.utils.validation import validate_price, validate_sku


class ProductService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_product(
        self, sku: str, name: str, description: str, price: float, category: str, inventory_quantity: int
    ) -> Product:
        if not validate_sku(sku):
            raise ValidationFailedError(
                "SKU must be 3-32 uppercase letters/digits (and '-'/'_'), starting with a letter or digit"
            )
        if not validate_price(price):
            raise ValidationFailedError("Price must be greater than zero")
        if inventory_quantity < 0:
            raise ValidationFailedError("Inventory quantity cannot be negative")
        if self.conn.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone() is not None:
            raise ConflictError(f"A product with SKU '{sku}' already exists")

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO products "
            "(sku, name, description, price, category, inventory_quantity, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (sku, name, description, price, category, inventory_quantity, now, now),
        )
        self.conn.commit()
        return self.get_by_id(cur.lastrowid)

    def get_by_id(self, product_id: int) -> Product:
        row = self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Product {product_id} not found")
        return Product.from_row(row)

    def list_products(
        self, category: str | None = None, active_only: bool = True, search: str | None = None
    ) -> list[Product]:
        query = "SELECT * FROM products WHERE 1=1"
        params: list = []
        if active_only:
            query += " AND is_active = 1"
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (name LIKE ? OR description LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like])
        query += " ORDER BY id"
        rows = self.conn.execute(query, params).fetchall()
        return [Product.from_row(r) for r in rows]

    def update_product(
        self,
        product_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        price: float | None = None,
        category: str | None = None,
    ) -> Product:
        product = self.get_by_id(product_id)
        if price is not None and not validate_price(price):
            raise ValidationFailedError("Price must be greater than zero")

        new_name = name if name is not None else product.name
        new_description = description if description is not None else product.description
        new_price = price if price is not None else product.price
        new_category = category if category is not None else product.category
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE products SET name = ?, description = ?, price = ?, category = ?, updated_at = ? WHERE id = ?",
            (new_name, new_description, new_price, new_category, now, product_id),
        )
        self.conn.commit()
        return self.get_by_id(product_id)

    def deactivate_product(self, product_id: int) -> Product:
        self.get_by_id(product_id)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?", (now, product_id))
        self.conn.commit()
        return self.get_by_id(product_id)
