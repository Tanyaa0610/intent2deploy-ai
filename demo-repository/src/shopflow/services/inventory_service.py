"""Inventory management: stock increases/decreases with protection
against overselling.

Low-stock notifications are NOT yet wired in here — `NotificationService
.notify_low_inventory` exists and works, but nothing currently calls it
when a decrease crosses the configured threshold. See
evaluation/tasks/task_013.json.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import NotFoundError, ValidationFailedError
from src.shopflow.models.product import Product


class InsufficientInventoryError(ValidationFailedError):
    status_code = 409  # a conflict with current stock, not a malformed request


class InventoryService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_product_or_404(self, product_id: int) -> Product:
        row = self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Product {product_id} not found")
        return Product.from_row(row)

    def is_low_stock(self, product_id: int, threshold: int) -> bool:
        product = self.get_product_or_404(product_id)
        return product.inventory_quantity <= threshold

    def increase_stock(self, product_id: int, quantity: int) -> Product:
        if quantity <= 0:
            raise ValidationFailedError("Quantity to add must be positive")
        self.get_product_or_404(product_id)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE products SET inventory_quantity = inventory_quantity + ?, updated_at = ? WHERE id = ?",
            (quantity, now, product_id),
        )
        self.conn.commit()
        return self.get_product_or_404(product_id)

    def decrease_stock(self, product_id: int, quantity: int) -> Product:
        """Decrease stock, never allowing it to go negative."""
        if quantity <= 0:
            raise ValidationFailedError("Quantity to remove must be positive")
        product = self.get_product_or_404(product_id)
        if product.inventory_quantity < quantity:
            raise InsufficientInventoryError(
                f"Insufficient inventory for product {product_id}: have {product.inventory_quantity}, need {quantity}"
            )
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE products SET inventory_quantity = inventory_quantity - ?, updated_at = ? WHERE id = ?",
            (quantity, now, product_id),
        )
        self.conn.commit()
        return self.get_product_or_404(product_id)

    def check_sufficient_stock(self, product_id: int, quantity: int) -> bool:
        product = self.get_product_or_404(product_id)
        return product.inventory_quantity >= quantity
