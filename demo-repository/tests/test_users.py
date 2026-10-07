from __future__ import annotations


def test_get_me_returns_current_user(client, register_user):
    _user_id, headers = register_user("erin")
    resp = client.get("/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "erin"


def test_my_orders_starts_empty(client, register_user):
    _user_id, headers = register_user("erin")
    resp = client.get("/users/me/orders", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_can_deactivate_user(client, register_user, admin_headers):
    user_id, _headers = register_user("frank")
    resp = client.post(f"/users/{user_id}/deactivate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_customer_cannot_deactivate_user(client, register_user):
    user_id, headers = register_user("gina")
    other_id, _ = register_user("harry")
    resp = client.post(f"/users/{other_id}/deactivate", headers=headers)
    assert resp.status_code == 403


def test_deactivated_user_cannot_log_in_again(client, register_user, admin_headers):
    user_id, _headers = register_user("irene", password="StrongPass123")
    client.post(f"/users/{user_id}/deactivate", headers=admin_headers)
    resp = client.post("/auth/login", json={"username": "irene", "password": "StrongPass123"})
    assert resp.status_code == 401
