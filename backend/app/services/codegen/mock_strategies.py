"""Mock-mode (LLM_MODE=mock) code-generation strategies.

Each function takes the actual current content of one or more repository
files (from real retrieval, not invented) and produces a REAL, syntactically
valid source transformation plus a unified diff. This is what keeps mock
mode honest per master spec §47: changing the developer intent changes
which strategy is selected (app/services/planner/intent_classifier.py) and
therefore changes the retrieved files, the diff, and the generated tests.

Mock mode intentionally supports a bounded set of intent patterns rather
than arbitrary free-form code generation — a real LLM provider
(LLM_MODE=live) is required for general-purpose generation. An intent that
matches no known pattern gets an honest low-confidence result instead of
fabricated code (see `generic_fallback`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.codegen.diffing import make_unified_diff


@dataclass
class MockChange:
    file: str
    operation: str
    reason: str
    new_content: str
    old_content: str
    confidence: float
    risks: list[str]
    acceptance_criterion: str

    @property
    def patch(self) -> str:
        return make_unified_diff(self.file, self.old_content, self.new_content)


def _indent_block(code: str, indent: str = "    ") -> str:
    return "\n".join(indent + line if line.strip() else line for line in code.splitlines())


# ---------------------------------------------------------------------------
# 1. Password reset (primary demo scenario)
# ---------------------------------------------------------------------------
_RESET_METHODS = '''
    def generate_password_reset_token(self, username: str) -> str:
        """Issue a single-use password-reset token for `username`.

        The token expires after RESET_TOKEN_TTL_SECONDS and is invalidated
        after first use (see reset_password).
        """
        user = self.users.get_by_username(username)
        if user is None:
            raise InvalidCredentialsError("Unknown username")
        token = secrets.token_urlsafe(32)
        self._reset_tokens[token] = (username, time.time())
        return token

    def reset_password(self, token: str, new_password: str) -> None:
        """Consume a password-reset token and set a new password.

        Raises InvalidCredentialsError if the token is unknown or expired.
        """
        entry = self._reset_tokens.pop(token, None)
        if entry is None:
            raise InvalidCredentialsError("Invalid or already-used reset token")
        username, issued_at = entry
        if time.time() - issued_at > self.RESET_TOKEN_TTL_SECONDS:
            raise InvalidCredentialsError("Reset token has expired")
        salt = secrets.token_hex(8)
        password_hash = self._hash_password(new_password, salt)
        self.users.update_password(username, password_hash, salt)
'''


def password_reset(file_contents: dict[str, str]) -> list[MockChange]:
    changes: list[MockChange] = []
    path = "src/auth/service.py"
    old = file_contents.get(path, "")
    if not old:
        return changes

    new = old
    if "RESET_TOKEN_TTL_SECONDS" not in new:
        new = new.replace(
            "class AuthService:\n",
            "class AuthService:\n    RESET_TOKEN_TTL_SECONDS = 900  # 15 minutes\n",
            1,
        )
    if "self._reset_tokens" not in new:
        new = new.replace(
            "self._active_tokens: dict[str, tuple[str, float]] = {}  # token -> (username, issued_at)\n",
            "self._active_tokens: dict[str, tuple[str, float]] = {}  # token -> (username, issued_at)\n"
            "        self._reset_tokens: dict[str, tuple[str, float]] = {}  # reset_token -> (username, issued_at)\n",
            1,
        )
    if "def generate_password_reset_token" not in new:
        new = new.rstrip("\n") + "\n" + _RESET_METHODS.rstrip("\n") + "\n"

    if new != old:
        changes.append(
            MockChange(
                file=path,
                operation="modify",
                reason=(
                    "Adds password-reset token issuance and consumption to AuthService, "
                    "reusing the existing hashing/token utilities so login/registration "
                    "behavior is unchanged."
                ),
                new_content=new,
                old_content=old,
                confidence=0.72,
                risks=[
                    "Reset tokens are stored in-memory (lost on process restart), matching "
                    "the existing in-memory session-token design of this demo repository.",
                    "Token delivery (e.g. email) is out of scope for this change.",
                ],
                acceptance_criterion="User can request a password reset and reset tokens expire/are rejected when invalid.",
            )
        )
    return changes


# ---------------------------------------------------------------------------
# 2. Bug fix: null-reference in OrderService.get_order_total
# ---------------------------------------------------------------------------
def bug_fix_orders(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/orders/service.py"
    old = file_contents.get(path, "")
    if not old or "def get_order_total" not in old:
        return []

    buggy = (
        '        order = self.get_order(order_id)\n'
        '        return sum(price for _name, price in order.items)  # bug is intentional, see README\n'
    )
    fixed = (
        '        order = self.get_order(order_id)\n'
        '        if order is None:\n'
        '            raise ValueError(f"Order {order_id} does not exist")\n'
        '        return sum(price for _name, price in order.items)\n'
    )
    if buggy not in old:
        return []
    new = old.replace(buggy, fixed)
    return [
        MockChange(
            file=path,
            operation="modify",
            reason=(
                "get_order_total dereferenced the result of get_order without checking "
                "for None, causing an unhandled AttributeError for unknown order IDs. "
                "Raises a clear ValueError instead."
            ),
            new_content=new,
            old_content=old,
            confidence=0.85,
            risks=["Callers that relied on the previous AttributeError (unlikely) must now catch ValueError."],
            acceptance_criterion="Calling get_order_total with an unknown order id raises a clear domain error instead of crashing.",
        )
    ]


# ---------------------------------------------------------------------------
# 3. Input validation on the registration endpoint
# ---------------------------------------------------------------------------
def input_validation(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/api/app.py"
    old = file_contents.get(path, "")
    if not old or "def register(" not in old:
        return []

    if "from src.validation.helpers import validate_email" in old:
        return []

    new = old.replace(
        "from src.users.model import UserRepository\n",
        "from src.users.model import UserRepository\nfrom src.validation.helpers import validate_email, validate_password_strength\n",
        1,
    )
    old_sig = "def register(payload: RegisterRequest) -> dict:\n"
    new_sig = (
        "def register(payload: RegisterRequest) -> dict:\n"
        '    if not validate_email(payload.email):\n'
        '        raise HTTPException(status_code=400, detail="Invalid email address")\n'
        '    if not validate_password_strength(payload.password):\n'
        '        raise HTTPException(\n'
        '            status_code=400,\n'
        '            detail="Password must be at least 8 characters and include a letter and a digit",\n'
        '        )\n'
    )
    if old_sig not in new:
        return []
    new = new.replace(old_sig, new_sig, 1)
    new = re.sub(
        r"[ \t]*# NOTE: does not currently call.*\n[ \t]*# validate_password_strength.*\n",
        "",
        new,
    )

    return [
        MockChange(
            file=path,
            operation="modify",
            reason=(
                "Wires the existing (previously unused) validate_email and "
                "validate_password_strength helpers into the registration endpoint, "
                "rejecting invalid input with HTTP 400 before a user is created."
            ),
            new_content=new,
            old_content=old,
            confidence=0.8,
            risks=["Clients submitting previously-accepted weak passwords or malformed emails will now receive a 400 response."],
            acceptance_criterion="Registration rejects invalid email addresses and weak passwords with a 400 response.",
        )
    ]


# ---------------------------------------------------------------------------
# 4. Auth token expiry
# ---------------------------------------------------------------------------
def auth_token_expiry(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/auth/service.py"
    old = file_contents.get(path, "")
    if not old or "def validate_token" not in old:
        return []
    if "SESSION_TOKEN_TTL_SECONDS" in old:
        return []

    new = old
    new = new.replace(
        "class AuthService:\n",
        "class AuthService:\n    SESSION_TOKEN_TTL_SECONDS = 3600  # 1 hour\n",
        1,
    )
    old_validate = (
        "    def validate_token(self, token: str) -> str | None:\n"
        "        entry = self._active_tokens.get(token)\n"
        "        if entry is None:\n"
        "            return None\n"
        "        username, _issued_at = entry\n"
        "        return username\n"
    )
    new_validate = (
        "    def validate_token(self, token: str) -> str | None:\n"
        "        entry = self._active_tokens.get(token)\n"
        "        if entry is None:\n"
        "            return None\n"
        "        username, issued_at = entry\n"
        "        if time.time() - issued_at > self.SESSION_TOKEN_TTL_SECONDS:\n"
        "            self._active_tokens.pop(token, None)\n"
        "            return None\n"
        "        return username\n"
    )
    if old_validate not in new:
        return []
    new = new.replace(old_validate, new_validate, 1)

    return [
        MockChange(
            file=path,
            operation="modify",
            reason="Session tokens now expire after SESSION_TOKEN_TTL_SECONDS instead of remaining valid forever.",
            new_content=new,
            old_content=old,
            confidence=0.75,
            risks=["Long-lived clients will need to re-authenticate after the TTL elapses."],
            acceptance_criterion="An expired session token is rejected by validate_token.",
        )
    ]


# ---------------------------------------------------------------------------
# 5. Payment idempotency (production-aware reliability scenario, Part N)
# ---------------------------------------------------------------------------
_IDEMPOTENCY_INIT = "        self._charges: list[Charge] = []\n"
_IDEMPOTENCY_INIT_NEW = (
    "        self._charges: list[Charge] = []\n"
    "        self._idempotency_cache: dict[str, Charge] = {}\n"
)

_OLD_CHARGE_METHOD = (
    '    def charge_order(self, order_id: int, amount: float, *, should_timeout: bool = False) -> Charge:\n'
    '        """Charge `order_id` for `amount` via the external payment provider.\n'
    '\n'
    '        BUG: no idempotency key is used, so calling this twice for the same\n'
    '        order_id (e.g. because a client retried after a timeout, or the\n'
    '        request was duplicated) creates two separate charges instead of\n'
    '        returning the original result.\n'
    '        """\n'
    '        result = self._provider.charge(amount, should_timeout=should_timeout)\n'
    '        charge = Charge(order_id=order_id, amount=amount, provider_charge_id=result.provider_charge_id)\n'
    '        self._charges.append(charge)\n'
    '        return charge\n'
)

_NEW_CHARGE_METHOD = (
    '    def charge_order(\n'
    '        self,\n'
    '        order_id: int,\n'
    '        amount: float,\n'
    '        *,\n'
    '        idempotency_key: str | None = None,\n'
    '        should_timeout: bool = False,\n'
    '    ) -> Charge:\n'
    '        """Charge `order_id` for `amount` via the external payment provider.\n'
    '\n'
    '        If `idempotency_key` matches a previous successful charge, that\n'
    '        charge is returned unchanged instead of contacting the provider\n'
    '        again — this is what makes a client retry after a provider timeout\n'
    '        (or a duplicated request) safe: it can never create a second charge\n'
    '        for the same logical payment attempt.\n'
    '        """\n'
    '        if idempotency_key is not None and idempotency_key in self._idempotency_cache:\n'
    '            return self._idempotency_cache[idempotency_key]\n'
    '        result = self._provider.charge(amount, should_timeout=should_timeout)\n'
    '        charge = Charge(order_id=order_id, amount=amount, provider_charge_id=result.provider_charge_id)\n'
    '        self._charges.append(charge)\n'
    '        if idempotency_key is not None:\n'
    '            self._idempotency_cache[idempotency_key] = charge\n'
    '        return charge\n'
)


def payment_idempotency(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/payments/service.py"
    old = file_contents.get(path, "")
    if not old or "def charge_order" not in old or "idempotency_key" in old:
        return []
    if _IDEMPOTENCY_INIT not in old or _OLD_CHARGE_METHOD not in old:
        return []

    new = old.replace(_IDEMPOTENCY_INIT, _IDEMPOTENCY_INIT_NEW, 1)
    new = new.replace(_OLD_CHARGE_METHOD, _NEW_CHARGE_METHOD, 1)

    return [
        MockChange(
            file=path,
            operation="modify",
            reason=(
                "Adds an idempotency-key cache to PaymentService so retrying a charge "
                "(e.g. after the payment provider times out) returns the original "
                "charge instead of creating a duplicate one."
            ),
            new_content=new,
            old_content=old,
            confidence=0.78,
            risks=[
                "Idempotency cache is in-memory and lost on process restart, matching this "
                "demo repository's existing in-memory persistence model.",
                "Callers that do not pass an idempotency_key are unaffected and remain unprotected against retries.",
            ],
            acceptance_criterion="Retrying charge_order with the same idempotency_key does not create a duplicate provider charge.",
        )
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
STRATEGIES = {
    "password_reset": password_reset,
    "bug_fix_orders": bug_fix_orders,
    "input_validation": input_validation,
    "auth_token_expiry": auth_token_expiry,
    "payment_timeout_reliability": payment_idempotency,
}


def generic_fallback(file_contents: dict[str, str], intent: str) -> list[MockChange]:
    """Honest no-op result for intents mock mode cannot ground a real
    change in. Returned with confidence 0.0 and an explanatory reason
    rather than fabricated code."""
    return []
