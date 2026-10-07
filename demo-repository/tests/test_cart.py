from __future__ import annotations


def test_add_item_to_cart(client, register_user, make_product):
    _user_id, headers = register_user("kyle")
    product = make_product(price=10.0, inventory_quantity=20)
    resp = client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == [{"product_id": product["id"], "quantity": 2}]
    assert body["subtotal"] == 20.0


def test_update_item_quantity(client, register_user, make_product):
    _user_id, headers = register_user("laura")
    product = make_product(inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers)
    resp = client.patch(f"/cart/items/{product['id']}", json={"quantity": 5}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"][0]["quantity"] == 5


def test_remove_item_from_cart(client, register_user, make_product):
    _user_id, headers = register_user("mike")
    product = make_product(inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers)
    resp = client.delete(f"/cart/items/{product['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_add_unknown_product_returns_404(client, register_user):
    _user_id, headers = register_user("nina")
    resp = client.post("/cart/items", json={"product_id": 99999, "quantity": 1}, headers=headers)
    assert resp.status_code == 404


def test_add_more_than_available_inventory_rejected(client, register_user, make_product):
    _user_id, headers = register_user("omar")
    product = make_product(inventory_quantity=3)
    resp = client.post("/cart/items", json={"product_id": product["id"], "quantity": 10}, headers=headers)
    assert resp.status_code == 400


def test_clear_cart(client, register_user, make_product):
    _user_id, headers = register_user("paula")
    product = make_product(inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers)
    resp = client.delete("/cart", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_cart_is_isolated_per_user(client, register_user, make_product):
    _id1, headers1 = register_user("quinn")
    _id2, headers2 = register_user("rachel")
    product = make_product(inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers1)
    resp = client.get("/cart", headers=headers2)
    assert resp.json()["items"] == []
