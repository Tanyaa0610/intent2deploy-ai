"""Reusable input-validation helpers used by the API/service layer."""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


def validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def validate_password_strength(password: str) -> bool:
    if len(password) < 8:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit


def validate_sku(sku: str) -> bool:
    return bool(_SKU_RE.match(sku))


def validate_price(price: float) -> bool:
    return price > 0


def validate_quantity(quantity: int) -> bool:
    return isinstance(quantity, int) and quantity > 0
