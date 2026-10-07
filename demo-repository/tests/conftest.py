from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.shopflow.database import Database
from src.shopflow.main import app
from src.shopflow.models.enums import UserRole
from src.shopflow.services.auth_service import AuthService


@pytest.fixture
def client(tmp_path):
    """A TestClient backed by a fresh, unseeded, isolated SQLite database
    per test. Setting `app.state.db` before the TestClient triggers the
    startup event makes `on_startup` skip creating (and seeding) its own."""
    database = Database(str(tmp_path / "test.db"))
    app.state.db = database
    with TestClient(app) as test_client:
        yield test_client
    if hasattr(app.state, "db"):
        del app.state.db
    database.close()


@pytest.fixture
def db_conn(client) -> sqlite3.Connection:
    return app.state.db.conn


@pytest.fixture
def register_user(client):
    """Register + log in a CUSTOMER, returning (user_id, auth_headers)."""

    def _do(username: str = "alice", email: str | None = None, password: str = "StrongPass123"):
        email = email or f"{username}@example.com"
        resp = client.post("/auth/register", json={"username": username, "email": email, "password": password})
        assert resp.status_code == 201, resp.text
        user_id = resp.json()["id"]
        login_resp = client.post("/auth/login", json={"username": username, "password": password})
        assert login_resp.status_code == 200, login_resp.text
        token = login_resp.json()["token"]
        return user_id, {"Authorization": f"Bearer {token}"}

    return _do


@pytest.fixture
def admin_headers(db_conn, client):
    AuthService(db_conn).register("admin_test", "admin_test@example.com", "AdminPass123", role=UserRole.ADMIN)
    resp = client.post("/auth/login", json={"username": "admin_test", "password": "AdminPass123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_product(client, admin_headers):
    """Create a product as admin, returning its JSON body."""
    counter = {"n": 0}

    def _do(**overrides):
        counter["n"] += 1
        payload = {
            "sku": overrides.pop("sku", f"TESTSKU-{counter['n']:03d}"),
            "name": overrides.pop("name", f"Test Product {counter['n']}"),
            "description": overrides.pop("description", "A product used in tests."),
            "price": overrides.pop("price", 9.99),
            "category": overrides.pop("category", "test"),
            "inventory_quantity": overrides.pop("inventory_quantity", 50),
        }
        payload.update(overrides)
        resp = client.post("/products", json=payload, headers=admin_headers)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _do
