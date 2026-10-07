from __future__ import annotations


def test_register_creates_customer(client):
    resp = client.post("/auth/register", json={"username": "bob", "email": "bob@example.com", "password": "StrongPass123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "bob"
    assert body["role"] == "CUSTOMER"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


def test_duplicate_registration_rejected(client):
    payload = {"username": "bob", "email": "bob@example.com", "password": "StrongPass123"}
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = client.post("/auth/register", json=payload)
    assert second.status_code == 409


def test_login_succeeds_with_correct_credentials(client):
    client.post("/auth/register", json={"username": "bob", "email": "bob@example.com", "password": "StrongPass123"})
    resp = client.post("/auth/login", json={"username": "bob", "password": "StrongPass123"})
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_login_rejects_wrong_password(client):
    client.post("/auth/register", json={"username": "bob", "email": "bob@example.com", "password": "StrongPass123"})
    resp = client.post("/auth/login", json={"username": "bob", "password": "WrongPassword1"})
    assert resp.status_code == 401


def test_login_rejects_unknown_user(client):
    resp = client.post("/auth/login", json={"username": "nobody", "password": "WhateverPass1"})
    assert resp.status_code == 401


def test_protected_endpoint_requires_token(client):
    resp = client.get("/users/me")
    assert resp.status_code == 401


def test_protected_endpoint_works_with_valid_token(client, register_user):
    _user_id, headers = register_user("carol")
    resp = client.get("/users/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "carol"


def test_admin_only_endpoint_rejects_customer(client, register_user):
    _user_id, headers = register_user("dave")
    resp = client.get("/users", headers=headers)
    assert resp.status_code == 403


def test_admin_only_endpoint_allows_admin(client, admin_headers):
    resp = client.get("/users", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
