"""Deterministic intent classification used ONLY by mock-mode (LocalProvider).

This is documented and intentionally narrow: a real LLM (LLM_MODE=live)
does not need this — it reads the intent directly. Mock mode uses this
classifier so it can apply one of a bounded set of *real* code-generation
strategies (see app/services/codegen/mock_strategies.py) instead of
fabricating a generic answer. Intents that match no known strategy fall
back to a low-confidence, honestly-labeled result rather than invented
code — see docs/responsible-ai.md and docs/ai-testing-tools.md.
"""
from __future__ import annotations

import re

CATEGORIES = [
    "password_reset",
    "bug_fix_orders",
    "input_validation",
    "auth_token_expiry",
    "user_deactivate",
    "order_cancel_endpoint",
    "refactor_password_hash",
    "add_docstrings",
    "test_generation_orders",
    "payment_timeout_reliability",
    "generic",
]

_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "payment_timeout_reliability",
        [
            "duplicate order", "duplicate orders", "payment provider times out", "payment provider timeout",
            "payment timeout", "idempotent", "idempotency", "payment reliability", "reliable under payment",
        ],
    ),
    ("password_reset", ["password reset", "reset password", "forgot password"]),
    ("bug_fix_orders", ["null-reference", "null reference", "order service", "order total", "nullpointer", "none error"]),
    ("input_validation", ["input validation", "validate registration", "registration endpoint", "validate email", "validate input"]),
    ("auth_token_expiry", ["token expire", "token expiry", "expire session", "session timeout", "expiring token"]),
    ("user_deactivate", ["deactivate", "disable user", "soft delete", "suspend account"]),
    ("order_cancel_endpoint", ["cancel order", "delete order", "remove order", "order cancellation"]),
    ("refactor_password_hash", ["refactor", "hashing", "extract", "without changing"]),
    ("add_docstrings", ["docstring", "documentation", "code quality", "add comments", "add type hints"]),
    ("test_generation_orders", ["add tests for the order", "test coverage for order", "tests for orders", "add tests for order"]),
]


def classify_intent(intent: str) -> str:
    lowered = intent.lower()
    for category, phrases in _PATTERNS:
        if any(phrase in lowered for phrase in phrases):
            return category
    return "generic"


def extract_key_terms(intent: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", intent.lower())
    stop = {
        "the", "and", "for", "add", "make", "sure", "that", "with", "this",
        "are", "not", "does", "existing", "feature", "create", "appropriate",
    }
    return [w for w in words if w not in stop]
