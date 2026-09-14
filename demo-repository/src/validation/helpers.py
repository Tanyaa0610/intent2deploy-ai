"""Input validation helpers.

These exist but are deliberately NOT called from the registration endpoint
yet (`src/api/app.py`) — used by the "add input validation to the
registration endpoint" benchmark task (evaluation/tasks/task_005.json).
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def validate_password_strength(password: str) -> bool:
    if len(password) < 8:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit
