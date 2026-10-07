from __future__ import annotations


def test_admin_can_create_product(client, admin_headers):
    resp = client.post(
        "/products",
        json={
            "sku": "ABC-123", "name": "Widget", "description": "A widget.",
            "price": 9.99, "category": "misc", "inventory_quantity": 10,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sku"] == "ABC-123"
    assert body["is_active"] is True


def test_customer_cannot_create_product(client, register_user):
    _user_id, headers = register_user("jane")
    resp = client.post(
        "/products",
        json={"sku": "ABC-124", "name": "Widget", "price": 9.99, "inventory_quantity": 10},
        headers=headers,
    )
    assert resp.status_code == 403


def test_get_product_by_id(client, make_product):
    product = make_product()
    resp = client.get(f"/products/{product['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == product["id"]


def test_get_unknown_product_returns_404(client):
    resp = client.get("/products/99999")
    assert resp.status_code == 404


def test_list_products_filters_by_category(client, make_product):
    make_product(category="books")
    make_product(category="toys")
    resp = client.get("/products", params={"category": "books"})
    assert resp.status_code == 200
    assert all(p["category"] == "books" for p in resp.json())


def test_update_product(client, make_product, admin_headers):
    product = make_product(price=10.0)
    resp = client.patch(f"/products/{product['id']}", json={"price": 15.0}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["price"] == 15.0


def test_duplicate_sku_rejected(client, admin_headers):
    payload = {"sku": "DUP-001", "name": "First", "price": 5.0, "inventory_quantity": 1}
    assert client.post("/products", json=payload, headers=admin_headers).status_code == 201
    resp = client.post("/products", json={**payload, "name": "Second"}, headers=admin_headers)
    assert resp.status_code == 409


def test_negative_price_rejected(client, admin_headers):
    resp = client.post(
        "/products", json={"sku": "NEG-001", "name": "Bad", "price": -5.0, "inventory_quantity": 1}, headers=admin_headers
    )
    assert resp.status_code == 400


def test_invalid_sku_rejected(client, admin_headers):
    resp = client.post(
        "/products", json={"sku": "bad sku!", "name": "Bad", "price": 5.0, "inventory_quantity": 1}, headers=admin_headers
    )
    assert resp.status_code == 400


def test_deactivated_product_excluded_from_default_listing(client, make_product, admin_headers):
    product = make_product()
    client.post(f"/products/{product['id']}/deactivate", headers=admin_headers)
    resp = client.get("/products")
    assert product["id"] not in [p["id"] for p in resp.json()]
