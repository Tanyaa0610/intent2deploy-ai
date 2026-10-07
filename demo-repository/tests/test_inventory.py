from __future__ import annotations

from src.shopflow.services.inventory_service import InventoryService


def test_increase_stock(client, make_product, admin_headers):
    product = make_product(inventory_quantity=5)
    resp = client.post(f"/inventory/{product['id']}/adjust", json={"delta": 10}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["inventory_quantity"] == 15


def test_decrease_stock(client, make_product, admin_headers):
    product = make_product(inventory_quantity=10)
    resp = client.post(f"/inventory/{product['id']}/adjust", json={"delta": -4}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["inventory_quantity"] == 6


def test_decrease_below_zero_rejected(client, make_product, admin_headers):
    product = make_product(inventory_quantity=2)
    resp = client.post(f"/inventory/{product['id']}/adjust", json={"delta": -5}, headers=admin_headers)
    assert resp.status_code == 409
    # Stock must be unchanged after a rejected decrease.
    check = client.get(f"/inventory/{product['id']}")
    assert check.json()["inventory_quantity"] == 2


def test_low_stock_detection(db_conn, make_product):
    product = make_product(inventory_quantity=3)
    service = InventoryService(db_conn)
    assert service.is_low_stock(product["id"], threshold=5) is True
    assert service.is_low_stock(product["id"], threshold=2) is False


def test_get_inventory_for_unknown_product_returns_404(client):
    resp = client.get("/inventory/99999")
    assert resp.status_code == 404
