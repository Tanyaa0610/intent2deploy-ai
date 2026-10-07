"""Development seed data: an admin user, a customer user, and a handful
of products at different inventory levels. Idempotent — safe to call on
every startup (it only inserts rows that don't already exist by
username/SKU).

Local-only demo credentials, never real secrets — see README.md.
"""
from __future__ import annotations

import sqlite3

from src.shopflow.models.enums import UserRole
from src.shopflow.services.auth_service import AuthService
from src.shopflow.services.product_service import ProductService

SEED_ADMIN_USERNAME = "admin"
SEED_ADMIN_PASSWORD = "AdminPass123"  # noqa: S105 — local-only seed credential, not a real secret (see README)
SEED_CUSTOMER_USERNAME = "customer1"
SEED_CUSTOMER_PASSWORD = "CustomerPass123"  # noqa: S105 — local-only seed credential, not a real secret (see README)

_SEED_PRODUCTS = [
    # sku, name, description, price, category, inventory_quantity
    ("WMOUSE-01", "Wireless Mouse", "A 2.4GHz wireless mouse with USB receiver.", 19.99, "electronics", 40),
    ("MECHKEY-01", "Mechanical Keyboard", "Tactile mechanical keyboard, blue switches.", 69.99, "electronics", 15),
    ("USBC-HUB-01", "USB-C Hub", "7-in-1 USB-C hub with HDMI and SD card reader.", 34.50, "electronics", 3),
    ("NOTEBOOK-A5", "A5 Notebook", "Dot-grid notebook, 120 pages.", 6.99, "office", 100),
    ("DESKLAMP-01", "LED Desk Lamp", "Adjustable LED desk lamp with USB charging port.", 24.99, "home", 0),
]


def seed_demo_data(conn: sqlite3.Connection) -> None:
    auth = AuthService(conn)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (SEED_ADMIN_USERNAME,)).fetchone() is None:
        auth.register(SEED_ADMIN_USERNAME, "admin@shopflow.local", SEED_ADMIN_PASSWORD, role=UserRole.ADMIN)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (SEED_CUSTOMER_USERNAME,)).fetchone() is None:
        auth.register(SEED_CUSTOMER_USERNAME, "customer1@shopflow.local", SEED_CUSTOMER_PASSWORD, role=UserRole.CUSTOMER)

    products = ProductService(conn)
    for sku, name, description, price, category, quantity in _SEED_PRODUCTS:
        if conn.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone() is None:
            products.create_product(sku, name, description, price, category, quantity)
