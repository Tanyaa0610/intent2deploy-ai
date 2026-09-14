from src.orders.service import OrderService


def test_create_order_and_get_total() -> None:
    service = OrderService()
    service.create_order("alice", [("widget", 9.99), ("gadget", 4.50)])
    total = service.get_order_total(1)
    assert round(total, 2) == 14.49


def test_get_order_returns_none_for_unknown_id() -> None:
    service = OrderService()
    assert service.get_order(999) is None


# NOTE: There is intentionally no regression test here for
# `get_order_total(unknown_id)` — that gap is what the "fix the
# null-reference bug in the order service" benchmark task (task_004) is
# expected to close by generating a test that first reproduces the bug
# and then verifies the fix.
