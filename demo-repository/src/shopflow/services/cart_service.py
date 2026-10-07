"""Shopping cart management.

NOTE: `config.max_quantity_per_product` is not yet enforced here — only
available inventory bounds the quantity a customer can add. See
evaluation/tasks/task_018.json.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import NotFoundError, ValidationFailedError
from src.shopflow.models.cart import Cart, CartItem
from src.shopflow.services.inventory_service import InventoryService
from src.shopflow.services.product_service import ProductService
from src.shopflow.utils.validation import validate_quantity


class CartService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.products = ProductService(conn)
        self.inventory = InventoryService(conn)

    def get_or_create_cart(self, user_id: int) -> Cart:
        row = self.conn.execute("SELECT * FROM carts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            now = datetime.now(timezone.utc).isoformat()
            cur = self.conn.execute(
                "INSERT INTO carts (user_id, created_at, updated_at) VALUES (?, ?, ?)", (user_id, now, now)
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM carts WHERE id = ?", (cur.lastrowid,)).fetchone()
        items = self._items_for_cart(row["id"])
        return Cart.from_row(row, items)

    def _items_for_cart(self, cart_id: int) -> list[CartItem]:
        rows = self.conn.execute("SELECT * FROM cart_items WHERE cart_id = ? ORDER BY id", (cart_id,)).fetchall()
        return [CartItem.from_row(r) for r in rows]

    def add_item(self, user_id: int, product_id: int, quantity: int) -> Cart:
        if not validate_quantity(quantity):
            raise ValidationFailedError("Quantity must be a positive integer")

        product = self.products.get_by_id(product_id)
        if not product.is_active:
            raise ValidationFailedError(f"Product {product_id} is not available")

        cart = self.get_or_create_cart(user_id)
        existing = next((i for i in cart.items if i.product_id == product_id), None)
        total_requested = quantity + (existing.quantity if existing else 0)

        if not self.inventory.check_sufficient_stock(product_id, total_requested):
            raise ValidationFailedError(f"Insufficient inventory for product {product_id}")

        now = datetime.now(timezone.utc).isoformat()
        if existing:
            self.conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (total_requested, existing.id))
        else:
            self.conn.execute(
                "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)",
                (cart.id, product_id, quantity),
            )
        self.conn.execute("UPDATE carts SET updated_at = ? WHERE id = ?", (now, cart.id))
        self.conn.commit()
        return self.get_or_create_cart(user_id)

    def update_item_quantity(self, user_id: int, product_id: int, quantity: int) -> Cart:
        if not validate_quantity(quantity):
            raise ValidationFailedError("Quantity must be a positive integer")
        cart = self.get_or_create_cart(user_id)
        existing = next((i for i in cart.items if i.product_id == product_id), None)
        if existing is None:
            raise NotFoundError(f"Product {product_id} is not in the cart")
        if not self.inventory.check_sufficient_stock(product_id, quantity):
            raise ValidationFailedError(f"Insufficient inventory for product {product_id}")
        self.conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (quantity, existing.id))
        self.conn.commit()
        return self.get_or_create_cart(user_id)

    def remove_item(self, user_id: int, product_id: int) -> Cart:
        cart = self.get_or_create_cart(user_id)
        self.conn.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart.id, product_id))
        self.conn.commit()
        return self.get_or_create_cart(user_id)

    def clear_cart(self, user_id: int) -> Cart:
        cart = self.get_or_create_cart(user_id)
        self.conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart.id,))
        self.conn.commit()
        return self.get_or_create_cart(user_id)

    def calculate_subtotal(self, user_id: int) -> float:
        cart = self.get_or_create_cart(user_id)
        total = 0.0
        for item in cart.items:
            product = self.products.get_by_id(item.product_id)
            total += product.price * item.quantity
        return round(total, 2)
