"""Mock-mode test generation strategies, paired 1:1 with
app/services/codegen/mock_strategies.py so the generated tests actually
exercise the code the same mock run just proposed.

Generated test bodies use ShopFlow's real pytest fixtures
(demo-repository/tests/conftest.py: `client`, `db_conn`, `register_user`,
`admin_headers`, `make_product`) and import any service/exception class
they need locally within the function body, so the appended content is
self-contained regardless of what the target file already imports.

Deliberately avoids `pytest.raises` (manual try/except instead): this
content is appended to an EXISTING test file (app/services/orchestrator.py's
run_test_generation opens the target in append mode), and the orchestrator's
"prepend `import pytest` if the content uses it" logic prepends it to the
*appended block*, not the top of the file — which trips ruff's E402
("module level import not at top of file") in the validation pipeline's
lint stage. Avoiding `pytest.raises` sidesteps that without needing to
change the orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockGeneratedTest:
    file: str
    content: str  # function source to append (or full file if new)
    rationale: str
    category: str


def password_reset_tests() -> list[MockGeneratedTest]:
    return [
        MockGeneratedTest(
            file="tests/test_auth.py",
            content=(
                "\n\n"
                "def test_request_and_consume_password_reset_token(client, db_conn):\n"
                "    from src.shopflow.services.auth_service import AuthService\n"
                "    client.post(\"/auth/register\", json={\"username\": \"heidi\", \"email\": \"heidi@example.com\", \"password\": \"OldPassw0rd1\"})\n"
                "    auth_service = AuthService(db_conn)\n"
                "    token = auth_service.generate_password_reset_token(\"heidi\")\n"
                "    auth_service.reset_password(token, \"NewPassw0rd1\")\n"
                "    resp = client.post(\"/auth/login\", json={\"username\": \"heidi\", \"password\": \"NewPassw0rd1\"})\n"
                "    assert resp.status_code == 200\n"
                "\n\n"
                "def test_reset_password_invalid_token_raises(client, db_conn):\n"
                "    from src.shopflow.exceptions import UnauthenticatedError\n"
                "    from src.shopflow.services.auth_service import AuthService\n"
                "    auth_service = AuthService(db_conn)\n"
                "    raised = False\n"
                "    try:\n"
                "        auth_service.reset_password(\"not-a-real-token\", \"Whatever123\")\n"
                "    except UnauthenticatedError:\n"
                "        raised = True\n"
                "    assert raised\n"
                "\n\n"
                "def test_reset_password_expired_token_raises(client, db_conn):\n"
                "    from src.shopflow.exceptions import UnauthenticatedError\n"
                "    from src.shopflow.services.auth_service import AuthService\n"
                "    client.post(\"/auth/register\", json={\"username\": \"ivan\", \"email\": \"ivan@example.com\", \"password\": \"OldPassw0rd1\"})\n"
                "    auth_service = AuthService(db_conn)\n"
                "    token = auth_service.generate_password_reset_token(\"ivan\")\n"
                "    user_id, issued_at = auth_service._reset_tokens[token]\n"
                "    auth_service._reset_tokens[token] = (user_id, issued_at - auth_service.RESET_TOKEN_TTL_SECONDS - 1)\n"
                "    raised = False\n"
                "    try:\n"
                "        auth_service.reset_password(token, \"NewPassw0rd1\")\n"
                "    except UnauthenticatedError:\n"
                "        raised = True\n"
                "    assert raised\n"
                "\n\n"
                "def test_existing_login_unaffected_by_reset_feature(client):\n"
                "    client.post(\"/auth/register\", json={\"username\": \"judy\", \"email\": \"judy@example.com\", \"password\": \"Passw0rd1\"})\n"
                "    resp = client.post(\"/auth/login\", json={\"username\": \"judy\", \"password\": \"Passw0rd1\"})\n"
                "    assert resp.status_code == 200\n"
            ),
            rationale=(
                "Covers the happy path (request + consume a reset token), an invalid "
                "token, an expired token, and a regression check that ordinary login "
                "is unaffected by the new feature."
            ),
            category="happy_path",
        )
    ]


def bug_fix_orders_tests() -> list[MockGeneratedTest]:
    return [
        MockGeneratedTest(
            file="tests/test_orders.py",
            content=(
                "\n\n"
                "def test_get_order_total_unknown_id_raises_not_found(db_conn):\n"
                "    from src.shopflow.exceptions import NotFoundError\n"
                "    from src.shopflow.services.order_service import OrderService\n"
                "    service = OrderService(db_conn)\n"
                "    raised = False\n"
                "    try:\n"
                "        service.get_order_total(999)\n"
                "    except NotFoundError:\n"
                "        raised = True\n"
                "    assert raised\n"
            ),
            rationale="Reproduces the previously-unhandled null-reference case and verifies the fix raises a clear NotFoundError.",
            category="edge_case",
        )
    ]


def input_validation_tests() -> list[MockGeneratedTest]:
    return [
        MockGeneratedTest(
            file="tests/test_auth.py",
            content=(
                "\n\n"
                "def test_register_rejects_invalid_email(client):\n"
                "    resp = client.post(\n"
                "        \"/auth/register\",\n"
                "        json={\"username\": \"badmail\", \"email\": \"not-an-email\", \"password\": \"SecretPass1\"},\n"
                "    )\n"
                "    assert resp.status_code == 400\n"
                "\n\n"
                "def test_register_rejects_weak_password(client):\n"
                "    resp = client.post(\n"
                "        \"/auth/register\",\n"
                "        json={\"username\": \"weakpw\", \"email\": \"weakpw@example.com\", \"password\": \"weak\"},\n"
                "    )\n"
                "    assert resp.status_code == 400\n"
            ),
            rationale="Covers the two new invalid-input rejection paths added to the registration endpoint.",
            category="invalid_input",
        )
    ]


def auth_token_expiry_tests() -> list[MockGeneratedTest]:
    return [
        MockGeneratedTest(
            file="tests/test_auth.py",
            content=(
                "\n\n"
                "def test_validate_token_expired_returns_none(client, db_conn):\n"
                "    from src.shopflow.services.auth_service import AuthService\n"
                "    client.post(\"/auth/register\", json={\"username\": \"karl\", \"email\": \"karl@example.com\", \"password\": \"Passw0rd1\"})\n"
                "    token = client.post(\"/auth/login\", json={\"username\": \"karl\", \"password\": \"Passw0rd1\"}).json()[\"token\"]\n"
                "    auth_service = AuthService(db_conn)\n"
                "    db_conn.execute(\n"
                "        \"UPDATE sessions SET issued_at = issued_at - ? WHERE token = ?\",\n"
                "        (auth_service.SESSION_TOKEN_TTL_SECONDS + 1, token),\n"
                "    )\n"
                "    db_conn.commit()\n"
                "    assert auth_service.validate_token(token) is None\n"
            ),
            rationale="Verifies session tokens are rejected once their TTL has elapsed.",
            category="edge_case",
        )
    ]


def payment_idempotency_tests() -> list[MockGeneratedTest]:
    """Exercises PaymentService directly (not through the HTTP layer):
    retrieval for this intent reliably surfaces and patches
    payment_service.py, but not always schemas/payment.py or
    api/payments.py too (an honest retrieval-precision limitation, not a
    bug — see docs/EXPERIMENTAL_EVALUATION.md). Testing the service
    layer directly exercises exactly what this strategy guarantees."""
    return [
        MockGeneratedTest(
            file="tests/test_payments.py",
            content=(
                "\n\n"
                "def test_retry_with_same_idempotency_key_does_not_duplicate_charge(client, db_conn, register_user, make_product):\n"
                "    from src.shopflow.services.payment_service import PaymentService\n"
                "    _user_id, headers = register_user(\"retryuser\")\n"
                "    product = make_product(price=50.0, inventory_quantity=10)\n"
                "    client.post(\"/cart/items\", json={\"product_id\": product[\"id\"], \"quantity\": 1}, headers=headers)\n"
                "    order = client.post(\"/orders\", headers=headers).json()\n"
                "    service = PaymentService(db_conn)\n"
                "    first = service.charge_order(order[\"id\"], 50.0, idempotency_key=\"attempt-1\")\n"
                "    retried = service.charge_order(order[\"id\"], 50.0, idempotency_key=\"attempt-1\")\n"
                "    assert first.id == retried.id\n"
                "\n\n"
                "def test_new_idempotency_key_creates_separate_charge(client, db_conn, register_user, make_product):\n"
                "    from src.shopflow.services.payment_service import PaymentService\n"
                "    _user_id, headers = register_user(\"newkeyuser\")\n"
                "    product = make_product(price=20.0, inventory_quantity=10)\n"
                "    client.post(\"/cart/items\", json={\"product_id\": product[\"id\"], \"quantity\": 1}, headers=headers)\n"
                "    order = client.post(\"/orders\", headers=headers).json()\n"
                "    service = PaymentService(db_conn)\n"
                "    first = service.charge_order(order[\"id\"], 20.0, idempotency_key=\"key-a\")\n"
                "    second = service.charge_order(order[\"id\"], 20.0, idempotency_key=\"key-b\")\n"
                "    assert first.id != second.id\n"
                "\n\n"
                "def test_charge_without_idempotency_key_still_succeeds(client, db_conn, register_user, make_product):\n"
                "    from src.shopflow.services.payment_service import PaymentService\n"
                "    _user_id, headers = register_user(\"nokeyuser\")\n"
                "    product = make_product(price=15.0, inventory_quantity=10)\n"
                "    client.post(\"/cart/items\", json={\"product_id\": product[\"id\"], \"quantity\": 1}, headers=headers)\n"
                "    order = client.post(\"/orders\", headers=headers).json()\n"
                "    service = PaymentService(db_conn)\n"
                "    payment = service.charge_order(order[\"id\"], 15.0)\n"
                "    assert payment.amount == 15.0\n"
            ),
            rationale=(
                "Proves a retried request with the same idempotency key is deduplicated "
                "(the production bug this task fixes), that a genuinely new payment attempt "
                "still charges, and that unprotected callers keep working (regression)."
            ),
            category="edge_case",
        )
    ]


STRATEGIES = {
    "password_reset": password_reset_tests,
    "bug_fix_orders": bug_fix_orders_tests,
    "input_validation": input_validation_tests,
    "auth_token_expiry": auth_token_expiry_tests,
    "payment_timeout_reliability": payment_idempotency_tests,
}
