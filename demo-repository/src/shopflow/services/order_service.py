"""Order lifecycle management.

Lifecycle: PENDING -> PAYMENT_PENDING -> CONFIRMED -> PROCESSING ->
SHIPPED -> DELIVERED, with CANCELLED/FAILED as side branches. See
`_ALLOWED_ADVANCE` for the forward-only admin status-advance transitions.

This module intentionally contains two realistic, narrow gaps used by
the evaluation benchmark — both are documented inline and in
evaluation/tasks/:

- `cancel_order` blocks cancelling a DELIVERED or already-CANCELLED
  order, but not a SHIPPED one (task_014.json).
- `cancel_order` does not restore the inventory that was reserved when
  the order was created (task_019.json).
- `apply_payment_result` checks the charged amount rather than the
  payment's actual status, so a failed/declined payment can still
  confirm the order (task_021.json).
- `get_order_total` does not guard against an unknown order id
  (task_002.json / task_003.json).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import ConflictError, NotFoundError, ValidationFailedError
from src.shopflow.models.enums import OrderStatus
from src.shopflow.models.order import Order, OrderItem
from src.shopflow.models.payment import Payment
from src.shopflow.services.cart_service import CartService
from src.shopflow.services.inventory_service import InventoryService
from src.shopflow.services.product_service import ProductService

# Orders in these states can never be cancelled again.
# NOTE: SHIPPED is deliberately absent here — see module docstring and
# evaluation/tasks/task_014.json.
_CANNOT_CANCEL = {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.FAILED}

_ALLOWED_ADVANCE: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
}


class OrderService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.carts = CartService(conn)
        self.products = ProductService(conn)
        self.inventory = InventoryService(conn)

    def create_order_from_cart(self, user_id: int) -> Order:
        """Create a PENDING order from the user's current cart: validates
        every line, reserves inventory for each, snapshots item prices,
        and clears the cart."""
        cart = self.carts.get_or_create_cart(user_id)
        if not cart.items:
            raise ValidationFailedError("Cannot create an order from an empty cart")

        line_items: list[tuple[int, str, int, float]] = []  # (product_id, name, qty, unit_price)
        total = 0.0
        for item in cart.items:
            product = self.products.get_by_id(item.product_id)
            if not product.is_active:
                raise ValidationFailedError(f"Product {product.id} is no longer available")
            if not self.inventory.check_sufficient_stock(product.id, item.quantity):
                raise ValidationFailedError(f"Insufficient inventory for product {product.id}")
            line_items.append((product.id, product.name, item.quantity, product.price))
            total += product.price * item.quantity

        # Reserve inventory for every line before committing the order.
        for product_id, _name, qty, _price in line_items:
            self.inventory.decrease_stock(product_id, qty)

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO orders (user_id, status, total, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, OrderStatus.PENDING.value, round(total, 2), now, now),
        )
        order_id = cur.lastrowid
        for product_id, name, qty, price in line_items:
            self.conn.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price) VALUES (?, ?, ?, ?, ?)",
                (order_id, product_id, name, qty, price),
            )
        self.conn.commit()
        self.carts.clear_cart(user_id)
        return self.get_order_or_404(order_id)

    def get_order(self, order_id: int) -> Order | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        items = self._items_for_order(order_id)
        return Order.from_row(row, items)

    def get_order_or_404(self, order_id: int) -> Order:
        order = self.get_order(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")
        return order

    def get_order_total(self, order_id: int) -> float:
        """Return the total price of an order.

        BUG: does not check whether `get_order` returned None before
        accessing `.total`, so calling this with an unknown order_id
        raises an unhandled AttributeError instead of a clear domain
        error. See evaluation/tasks/task_002.json.
        """
        order = self.get_order(order_id)
        return order.total  # bug is intentional, see module docstring

    def list_orders_for_user(self, user_id: int) -> list[Order]:
        rows = self.conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        return [Order.from_row(r, self._items_for_order(r["id"])) for r in rows]

    def _items_for_order(self, order_id: int) -> list[OrderItem]:
        rows = self.conn.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
        return [OrderItem.from_row(r) for r in rows]

    def cancel_order(self, order_id: int, *, requesting_user_id: int, is_admin: bool) -> Order:
        order = self.get_order_or_404(order_id)
        if not is_admin and order.user_id != requesting_user_id:
            raise ConflictError("Cannot cancel an order that does not belong to you")
        if OrderStatus(order.status) in _CANNOT_CANCEL:
            raise ConflictError(f"Order {order_id} cannot be cancelled from status {order.status}")

        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (OrderStatus.CANCELLED.value, now, order_id)
        )
        self.conn.commit()
        # NOTE: reserved inventory is not restored here — see module
        # docstring and evaluation/tasks/task_019.json.
        return self.get_order_or_404(order_id)

    def advance_status(self, order_id: int, new_status: OrderStatus) -> Order:
        """Admin-only forward progression (e.g. CONFIRMED -> PROCESSING
        -> SHIPPED -> DELIVERED). Authorization is enforced at the API
        layer; this only enforces that the transition itself is valid."""
        order = self.get_order_or_404(order_id)
        current = OrderStatus(order.status)
        allowed = _ALLOWED_ADVANCE.get(current, set())
        if new_status not in allowed:
            raise ConflictError(f"Cannot move order {order_id} from {current.value} to {new_status.value}")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (new_status.value, now, order_id))
        self.conn.commit()
        return self.get_order_or_404(order_id)

    def mark_payment_pending(self, order_id: int) -> Order:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (OrderStatus.PAYMENT_PENDING.value, now, order_id),
        )
        self.conn.commit()
        return self.get_order_or_404(order_id)

    def apply_payment_result(self, order_id: int, payment: Payment) -> Order:
        """Move the order to CONFIRMED or FAILED based on the outcome of
        a payment attempt.

        BUG: checks `payment.amount > 0` (always true — you never charge
        a zero amount) instead of `payment.status == CAPTURED`, so a
        declined or timed-out payment (which is still recorded with a
        nonzero `amount`, just status FAILED) incorrectly confirms the
        order. See evaluation/tasks/task_021.json.
        """
        now = datetime.now(timezone.utc).isoformat()
        new_status = OrderStatus.CONFIRMED if payment.amount > 0 else OrderStatus.FAILED  # bug is intentional
        self.conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (new_status.value, now, order_id))
        self.conn.commit()
        return self.get_order_or_404(order_id)
