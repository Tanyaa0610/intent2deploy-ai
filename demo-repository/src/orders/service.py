"""Order service: a minimal in-memory order store.

Contains a deliberate null-reference bug in `get_order_total`, used by the
"fix the null-reference bug in the order service" benchmark task
(evaluation/tasks/task_004.json).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Order:
    id: int
    owner_username: str
    items: list[tuple[str, float]] = field(default_factory=list)  # (name, price)


class OrderService:
    def __init__(self) -> None:
        self._orders: dict[int, Order] = {}
        self._next_id = 1

    def create_order(self, owner_username: str, items: list[tuple[str, float]]) -> Order:
        order = Order(id=self._next_id, owner_username=owner_username, items=items)
        self._orders[order.id] = order
        self._next_id += 1
        return order

    def get_order(self, order_id: int) -> Order | None:
        return self._orders.get(order_id)

    def get_order_total(self, order_id: int) -> float:
        """Return the total price of an order.

        BUG: this does not check whether `get_order` returned None before
        accessing `.items`, so calling this with an unknown order_id raises
        an unhandled AttributeError instead of a clear domain error.
        """
        order = self.get_order(order_id)
        return sum(price for _name, price in order.items)  # bug is intentional, see README
