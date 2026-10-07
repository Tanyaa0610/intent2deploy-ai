from __future__ import annotations


def _order_with_product(client, headers, make_product, quantity=1, price=10.0):
    product = make_product(price=price, inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": quantity}, headers=headers)
    return client.post("/orders", headers=headers).json()


def test_successful_payment_confirms_order(client, register_user, make_product):
    _user_id, headers = register_user("gabe")
    order = _order_with_product(client, headers, make_product)
    resp = client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "CAPTURED"
    order_after = client.get(f"/orders/{order['id']}", headers=headers).json()
    assert order_after["status"] == "CONFIRMED"


def test_declined_payment_is_recorded_as_failed(client, register_user, make_product):
    _user_id, headers = register_user("holly")
    order = _order_with_product(client, headers, make_product)
    resp = client.post(
        "/payments", json={"order_id": order["id"], "amount": order["total"], "should_decline": True}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "FAILED"


def test_timeout_payment_is_recorded_as_failed(client, register_user, make_product):
    _user_id, headers = register_user("ivan")
    order = _order_with_product(client, headers, make_product)
    resp = client.post(
        "/payments", json={"order_id": order["id"], "amount": order["total"], "should_timeout": True}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "FAILED"


def test_can_retry_payment_after_a_failure(client, register_user, make_product):
    """A client can attempt payment again after a failed attempt — the
    system does not get stuck. (Whether the retried attempt is
    deduplicated against the first is a separate concern — see
    evaluation/tasks/task_011.json / task_012.json.)"""
    _user_id, headers = register_user("jill")
    order = _order_with_product(client, headers, make_product)
    first = client.post(
        "/payments", json={"order_id": order["id"], "amount": order["total"], "should_timeout": True}, headers=headers
    )
    assert first.json()["status"] == "FAILED"
    second = client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers)
    assert second.status_code == 201
    assert second.json()["status"] == "CAPTURED"


def test_get_payment_by_id(client, register_user, make_product):
    _user_id, headers = register_user("ken")
    order = _order_with_product(client, headers, make_product)
    created = client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers).json()
    resp = client.get(f"/payments/{created['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_cannot_pay_for_someone_elses_order(client, register_user, make_product):
    _id1, headers1 = register_user("liam")
    _id2, headers2 = register_user("maria")
    order = _order_with_product(client, headers1, make_product)
    resp = client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers2)
    assert resp.status_code == 403


def test_pay_for_unknown_order_returns_404(client, register_user):
    _user_id, headers = register_user("noah")
    resp = client.post("/payments", json={"order_id": 99999, "amount": 10.0}, headers=headers)
    assert resp.status_code == 404
