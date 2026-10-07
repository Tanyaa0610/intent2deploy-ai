from __future__ import annotations


def _captured_payment(client, headers, make_product, price=20.0):
    product = make_product(price=price, inventory_quantity=20)
    client.post("/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=headers)
    order = client.post("/orders", headers=headers).json()
    return client.post("/payments", json={"order_id": order["id"], "amount": order["total"]}, headers=headers).json()


def test_admin_can_issue_valid_refund(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("oscar")
    payment = _captured_payment(client, headers, make_product, price=20.0)
    resp = client.post(
        "/refunds", json={"payment_id": payment["id"], "amount": 20.0, "reason": "customer request"}, headers=admin_headers
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "COMPLETED"


def test_customer_cannot_issue_refund(client, register_user, make_product):
    _user_id, headers = register_user("penny")
    payment = _captured_payment(client, headers, make_product)
    resp = client.post("/refunds", json={"payment_id": payment["id"], "amount": 20.0}, headers=headers)
    assert resp.status_code == 403


def test_refund_exceeding_payment_amount_rejected(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("quincy")
    payment = _captured_payment(client, headers, make_product, price=20.0)
    resp = client.post("/refunds", json={"payment_id": payment["id"], "amount": 999.0}, headers=admin_headers)
    assert resp.status_code == 409


def test_duplicate_full_refund_rejected(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("rosa")
    payment = _captured_payment(client, headers, make_product, price=20.0)
    first = client.post("/refunds", json={"payment_id": payment["id"], "amount": 20.0}, headers=admin_headers)
    assert first.status_code == 201
    second = client.post("/refunds", json={"payment_id": payment["id"], "amount": 20.0}, headers=admin_headers)
    assert second.status_code == 409


def test_refund_for_unknown_payment_returns_404(client, admin_headers):
    resp = client.post("/refunds", json={"payment_id": 99999, "amount": 5.0}, headers=admin_headers)
    assert resp.status_code == 404


def test_negative_refund_amount_rejected(client, register_user, make_product, admin_headers):
    _user_id, headers = register_user("stan")
    payment = _captured_payment(client, headers, make_product)
    resp = client.post("/refunds", json={"payment_id": payment["id"], "amount": -5.0}, headers=admin_headers)
    assert resp.status_code == 400
