from __future__ import annotations


def test_unauthorized_request_rejected_with_no_token(client):
    assert client.get("/users/me").status_code == 401
    assert client.get("/cart").status_code == 401
    assert client.post("/orders").status_code == 401


def test_malformed_authorization_header_rejected(client):
    resp = client.get("/users/me", headers={"Authorization": "NotBearer sometoken"})
    assert resp.status_code == 401


def test_unknown_token_rejected(client):
    resp = client.get("/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_forbidden_admin_operation_for_customer(client, register_user):
    _user_id, headers = register_user("yara")
    resp = client.post(
        "/products", json={"sku": "SEC-001", "name": "X", "price": 1.0, "inventory_quantity": 1}, headers=headers
    )
    assert resp.status_code == 403
    assert "stack" not in resp.text.lower()
    assert "traceback" not in resp.text.lower()


def test_password_hash_and_salt_never_exposed_via_api(client, register_user):
    _user_id, headers = register_user("zach")
    resp = client.get("/users/me", headers=headers)
    body_text = resp.text.lower()
    assert "password_hash" not in body_text
    assert "salt" not in body_text
    assert "password" not in body_text


def test_internal_errors_do_not_leak_stack_traces(client, register_user):
    _user_id, headers = register_user("yolanda")
    # An unknown order id triggers normal domain error handling (404),
    # never a raw traceback.
    resp = client.get("/orders/99999", headers=headers)
    assert resp.status_code == 404
    assert "Traceback" not in resp.text
