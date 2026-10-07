"""Per-category planning templates used by LocalProvider (mock mode) to
build a grounded PlanOutput. Keeping this alongside intent_classifier.py
so plan, diff and tests stay consistent for a given classified intent."""
from __future__ import annotations

CATEGORY_METADATA: dict[str, dict] = {
    "password_reset": {
        "summary": "Add a password-reset feature to the authentication service.",
        "acceptance_criteria": [
            "User can request a password-reset token",
            "Reset tokens expire after a fixed TTL",
            "Invalid or already-used reset tokens are rejected",
            "Existing login/registration behavior is unaffected",
        ],
        "test_strategy": [
            "valid reset flow (request token, reset password, log in with new password)",
            "expired reset token is rejected",
            "invalid/unknown reset token is rejected",
            "existing authentication regression tests continue to pass",
        ],
        "risks": ["Authentication regression", "Reset-token security (expiry/single-use) issues"],
        "primary_file": "src/shopflow/services/auth_service.py",
    },
    "bug_fix_orders": {
        "summary": "Fix the null-reference bug in the order service's total calculation.",
        "acceptance_criteria": [
            "Requesting the total for an unknown order id raises a clear domain error instead of crashing",
            "Existing order-total calculation for valid orders is unaffected",
        ],
        "test_strategy": [
            "regression: existing valid-order total calculation still passes",
            "edge case: unknown order id raises ValueError instead of AttributeError",
        ],
        "risks": ["Callers depending on the previous crash behavior (unlikely) would need to adjust"],
        "primary_file": "src/shopflow/services/order_service.py",
    },
    "input_validation": {
        "summary": "Add input validation to the registration endpoint.",
        "acceptance_criteria": [
            "Registration rejects malformed email addresses with HTTP 400",
            "Registration rejects weak passwords with HTTP 400",
            "Valid registrations continue to succeed",
        ],
        "test_strategy": [
            "invalid input: malformed email is rejected",
            "invalid input: weak password is rejected",
            "regression: valid registration still succeeds",
        ],
        "risks": ["Clients previously able to submit invalid data will now receive 400 responses"],
        "primary_file": "src/shopflow/api/auth.py",
    },
    "auth_token_expiry": {
        "summary": "Add session-token expiry to the authentication service.",
        "acceptance_criteria": [
            "Session tokens are rejected once their TTL has elapsed",
            "Freshly-issued tokens remain valid",
        ],
        "test_strategy": [
            "edge case: expired token is rejected",
            "regression: newly issued token remains valid",
        ],
        "risks": ["Long-lived sessions will require re-authentication after the TTL"],
        "primary_file": "src/shopflow/services/auth_service.py",
    },
    "payment_timeout_reliability": {
        "summary": (
            "Make order payment reliable under payment-provider failures by adding idempotency-key "
            "protection to PaymentService.charge_order, so a client retry after a provider timeout "
            "does not create a duplicate charge."
        ),
        "acceptance_criteria": [
            "Retrying a charge for the same order with the same idempotency key returns the original charge instead of creating a new one",
            "A charge for a different order or a new idempotency key still creates a new charge",
            "Existing (non-retried) payment behavior is unaffected",
        ],
        "test_strategy": [
            "regression: a normal single charge still succeeds and is recorded once",
            "edge case: retrying the same idempotency key after a simulated provider timeout does not duplicate the charge",
            "edge case: a new idempotency key for the same order creates a separate, legitimate charge",
        ],
        "risks": [
            "Duplicate charges on payment-provider timeout are a direct financial and trust risk",
            "Idempotency lookup is keyed on (order_id, idempotency_key) within this SQLite database, matching this demo repository's existing persistence model (unlike an in-memory cache, this survives a process restart)",
            "Retry storms from a flaky provider could still exhaust request capacity without additional backoff (out of scope for this change)",
            "Rollback strategy: this change is additive (a new idempotency_key parameter with a safe default of None) and requires no data migration, so it can be reverted by rolling back the commit with no data-compatibility impact",
        ],
        "primary_file": "src/shopflow/services/payment_service.py",
    },
    "generic": {
        "summary": "Analyze the requested change against retrieved repository evidence.",
        "acceptance_criteria": [
            "Behavior requested by the developer intent is implemented",
            "No regression in existing test suite",
        ],
        "test_strategy": ["regression: existing test suite continues to pass"],
        "risks": [
            "Mock mode (LLM_MODE=mock) does not have a specific grounded code-generation "
            "strategy for this intent; a live LLM provider is required to generate a "
            "concrete implementation.",
        ],
        "primary_file": "",
    },
}
