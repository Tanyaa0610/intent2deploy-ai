"""Mock-mode test generation strategies, paired 1:1 with
app/services/codegen/mock_strategies.py so the generated tests actually
exercise the code the same mock run just proposed."""
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
                "def test_request_and_consume_password_reset_token(auth_service: AuthService) -> None:\n"
                "    auth_service.register(\"heidi\", \"heidi@example.com\", \"oldpassw0rd\")\n"
                "    token = auth_service.generate_password_reset_token(\"heidi\")\n"
                "    auth_service.reset_password(token, \"newpassw0rd1\")\n"
                "    new_token = auth_service.login(\"heidi\", \"newpassw0rd1\")\n"
                "    assert isinstance(new_token, str)\n"
                "\n\n"
                "def test_reset_password_invalid_token_raises(auth_service: AuthService) -> None:\n"
                "    with pytest.raises(InvalidCredentialsError):\n"
                "        auth_service.reset_password(\"not-a-real-token\", \"whatever123\")\n"
                "\n\n"
                "def test_reset_password_expired_token_raises(auth_service: AuthService) -> None:\n"
                "    auth_service.register(\"ivan\", \"ivan@example.com\", \"oldpassw0rd\")\n"
                "    token = auth_service.generate_password_reset_token(\"ivan\")\n"
                "    username, issued_at = auth_service._reset_tokens[token]\n"
                "    auth_service._reset_tokens[token] = (username, issued_at - auth_service.RESET_TOKEN_TTL_SECONDS - 1)\n"
                "    with pytest.raises(InvalidCredentialsError):\n"
                "        auth_service.reset_password(token, \"newpassw0rd1\")\n"
                "\n\n"
                "def test_existing_login_unaffected_by_reset_feature(auth_service: AuthService) -> None:\n"
                "    auth_service.register(\"judy\", \"judy@example.com\", \"passw0rd1\")\n"
                "    token = auth_service.login(\"judy\", \"passw0rd1\")\n"
                "    assert auth_service.validate_token(token) == \"judy\"\n"
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
                "def test_get_order_total_unknown_id_raises_value_error() -> None:\n"
                "    service = OrderService()\n"
                "    with pytest.raises(ValueError):\n"
                "        service.get_order_total(999)\n"
            ),
            rationale="Reproduces the previously-unhandled null-reference case and verifies the fix raises a clear ValueError.",
            category="edge_case",
        )
    ]


def input_validation_tests() -> list[MockGeneratedTest]:
    return [
        MockGeneratedTest(
            file="tests/test_api.py",
            content=(
                "\n\n"
                "def test_register_rejects_invalid_email() -> None:\n"
                "    resp = client.post(\n"
                "        \"/register\",\n"
                "        json={\"username\": \"badmail\", \"email\": \"not-an-email\", \"password\": \"secretpass1\"},\n"
                "    )\n"
                "    assert resp.status_code == 400\n"
                "\n\n"
                "def test_register_rejects_weak_password() -> None:\n"
                "    resp = client.post(\n"
                "        \"/register\",\n"
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
                "def test_validate_token_expired_returns_none(auth_service: AuthService) -> None:\n"
                "    auth_service.register(\"karl\", \"karl@example.com\", \"passw0rd1\")\n"
                "    token = auth_service.login(\"karl\", \"passw0rd1\")\n"
                "    username, issued_at = auth_service._active_tokens[token]\n"
                "    auth_service._active_tokens[token] = (username, issued_at - auth_service.SESSION_TOKEN_TTL_SECONDS - 1)\n"
                "    assert auth_service.validate_token(token) is None\n"
            ),
            rationale="Verifies session tokens are rejected once their TTL has elapsed.",
            category="edge_case",
        )
    ]


STRATEGIES = {
    "password_reset": password_reset_tests,
    "bug_fix_orders": bug_fix_orders_tests,
    "input_validation": input_validation_tests,
    "auth_token_expiry": auth_token_expiry_tests,
}
