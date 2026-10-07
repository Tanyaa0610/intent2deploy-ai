from __future__ import annotations

from src.shopflow.models.enums import NotificationType
from src.shopflow.services.notification_service import NotificationService


def test_order_created_emits_notification(client, register_user, make_product, db_conn):
    _user_id, headers = register_user("tina")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    client.post("/orders", headers=headers)

    notifications = NotificationService(db_conn).list_notifications(NotificationType.ORDER_CREATED)
    assert len(notifications) == 1


def test_payment_succeeded_emits_notification(client, register_user, make_product, db_conn):
    _user_id, headers = register_user("ulysses")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers)

    notifications = NotificationService(db_conn).list_notifications(NotificationType.PAYMENT_SUCCEEDED)
    assert len(notifications) == 1


def test_payment_failed_emits_notification(client, register_user, make_product, db_conn):
    _user_id, headers = register_user("vera")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    client.post("/payments", json={"order_id": order["id"], "amount": order["total"], "should_decline": True}, headers=headers)

    notifications = NotificationService(db_conn).list_notifications(NotificationType.PAYMENT_FAILED)
    assert len(notifications) == 1


def test_low_inventory_notification_can_be_emitted(db_conn, make_product):
    """NotificationService's low-inventory event is real and working —
    see evaluation/tasks/task_013.json for the gap in automatically
    triggering it from InventoryService."""
    product = make_product(inventory_quantity=3)
    notification = NotificationService(db_conn).notify_low_inventory(product["id"], product["sku"], 3, threshold=5)
    assert notification.event_type == NotificationType.LOW_INVENTORY.value


def test_user_registered_emits_notification(client, db_conn):
    client.post("/auth/register", json={"username": "wade", "email": "wade@example.com", "password": "StrongPass123"})
    notifications = NotificationService(db_conn).list_notifications(NotificationType.USER_REGISTERED)
    assert any("wade" in n.payload for n in notifications)
