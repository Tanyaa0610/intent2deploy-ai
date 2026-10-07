from __future__ import annotations


def test_create_order_from_cart(client, register_user, make_product):
    _user_id, headers = register_user("sam")
    product = make_product(price=10.0, inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 3}, headers=headers)
    resp = client.post("/orders", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["total"] == 30.0
    assert body["items"][0]["quantity"] == 3


def test_create_order_from_empty_cart_rejected(client, register_user):
    _user_id, headers = register_user("tara")
    resp = client.post("/orders", headers=headers)
    assert resp.status_code == 400


def test_create_order_reserves_inventory(client, register_user, make_product):
    _user_id, headers = register_user("uma")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 4}, headers=headers)
    client.post("/orders", headers=headers)
    check = client.get(f"/inventory/{product['id']}")
    assert check.json()["inventory_quantity"] == 1


def test_create_order_clears_cart(client, register_user, make_product):
    _user_id, headers = register_user("victor")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 2}, headers=headers)
    client.post("/orders", headers=headers)
    cart = client.get("/cart", headers=headers)
    assert cart.json()["items"] == []


def test_get_order_by_owner(client, register_user, make_product):
    _user_id, headers = register_user("wendy")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    resp = client.get(f"/orders/{order['id']}", headers=headers)
    assert resp.status_code == 200


def test_get_order_forbidden_for_other_user(client, register_user, make_product):
    _id1, headers1 = register_user("xena")
    _id2, headers2 = register_user("yusuf")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers1)
    order = client.post("/orders", headers=headers1).json()
    resp = client.get(f"/orders/{order['id']}", headers=headers2)
    assert resp.status_code == 403


def test_my_orders_lists_created_order(client, register_user, make_product):
    _user_id, headers = register_user("zane")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    resp = client.get("/users/me/orders", headers=headers)
    assert resp.status_code == 200
    assert order["id"] in [o["id"] for o in resp.json()]


def test_cancel_pending_order(client, register_user, make_product):
    _user_id, headers = register_user("abel")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    resp = client.post(f"/orders/{order['id']}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


def test_cancel_already_cancelled_order_rejected(client, register_user, make_product):
    _user_id, headers = register_user("bianca")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    client.post(f"/orders/{order['id']}/cancel", headers=headers)
    resp = client.post(f"/orders/{order['id']}/cancel", headers=headers)
    assert resp.status_code == 409


def test_cancel_delivered_order_rejected(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("caleb")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    order_id = order["id"]
    # Walk the order through to CONFIRMED via a successful payment, then
    # admin-advance it to DELIVERED.
    client.post("/payments", json={"order_id": order_id, "amount": order["total"]}, headers=headers)
    client.patch(f"/orders/{order_id}/status", json={"status": "PROCESSING"}, headers=admin_headers)
    client.patch(f"/orders/{order_id}/status", json={"status": "SHIPPED"}, headers=admin_headers)
    client.patch(f"/orders/{order_id}/status", json={"status": "DELIVERED"}, headers=admin_headers)
    resp = client.post(f"/orders/{order_id}/cancel", headers=headers)
    assert resp.status_code == 409


def test_cancel_unknown_order_returns_404(client, register_user):
    _user_id, headers = register_user("delia")
    resp = client.post("/orders/99999/cancel", headers=headers)
    assert resp.status_code == 404


def test_invalid_status_transition_rejected(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("eli")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    # Order is still PENDING; jumping straight to SHIPPED is not allowed.
    resp = client.patch(f"/orders/{order['id']}/status", json={"status": "SHIPPED"}, headers=admin_headers)
    assert resp.status_code == 409


def test_customer_cannot_advance_order_status(client, register_user, make_product):
    _user_id, headers = register_user("faye")
    product = make_product(inventory_quantity=5)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    resp = client.patch(f"/orders/{order['id']}/status", json={"status": "PROCESSING"}, headers=headers)
    assert resp.status_code == 403
