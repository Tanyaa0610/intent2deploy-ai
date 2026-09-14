from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)


def test_register_endpoint() -> None:
    resp = client.post(
        "/register",
        json={"username": "eve", "email": "eve@example.com", "password": "secretpass1"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "eve"


def test_login_endpoint() -> None:
    client.post(
        "/register",
        json={"username": "frank", "email": "frank@example.com", "password": "secretpass1"},
    )
    resp = client.post("/login", json={"username": "frank", "password": "secretpass1"})
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_endpoint_wrong_password() -> None:
    client.post(
        "/register",
        json={"username": "grace", "email": "grace@example.com", "password": "secretpass1"},
    )
    resp = client.post("/login", json={"username": "grace", "password": "wrong"})
    assert resp.status_code == 401
