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

These 5 strategies target the ShopFlow API fixture repository
(demo-repository/src/shopflow/) — see
docs/EXPERIMENTAL_EVALUATION.md and demo-repository/README.md
("Development limitations") for the gap each one closes.
"""
from __future__ import annotations

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

        Raises UnauthenticatedError if the username is unknown.
        """
        row = self.conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise UnauthenticatedError("Unknown username")
        token = secrets.token_urlsafe(32)
        self._reset_tokens[token] = (row["id"], time.time())
        return token

    def reset_password(self, token: str, new_password: str) -> None:
        """Consume a password-reset token and set a new password.

        Raises UnauthenticatedError if the token is unknown, already
        used, or expired.
        """
        entry = self._reset_tokens.pop(token, None)
        if entry is None:
            raise UnauthenticatedError("Invalid or already-used reset token")
        user_id, issued_at = entry
        if time.time() - issued_at > self.RESET_TOKEN_TTL_SECONDS:
            raise UnauthenticatedError("Reset token has expired")
        salt = secrets.token_hex(8)
        password_hash = self._hash_password(new_password, salt)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE users SET password_hash = ?, salt = ?, updated_at = ? WHERE id = ?",
            (password_hash, salt, now, user_id),
        )
        self.conn.commit()
'''


def password_reset(file_contents: dict[str, str]) -> list[MockChange]:
    changes: list[MockChange] = []
    path = "src/shopflow/services/auth_service.py"
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
            "        self.conn = conn\n",
            "        self.conn = conn\n"
            "        self._reset_tokens: dict[str, tuple[int, float]] = {}  # token -> (user_id, issued_at)\n",
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
                    "reusing the existing hashing utilities so login/registration behavior "
                    "is unchanged."
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
    path = "src/shopflow/services/order_service.py"
    old = file_contents.get(path, "")
    if not old or "def get_order_total" not in old:
        return []

    buggy = (
        "        order = self.get_order(order_id)\n"
        "        return order.total  # bug is intentional, see module docstring\n"
    )
    fixed = (
        "        order = self.get_order(order_id)\n"
        "        if order is None:\n"
        '            raise NotFoundError(f"Order {order_id} not found")\n'
        "        return order.total\n"
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
                "Raises a clear NotFoundError instead."
            ),
            new_content=new,
            old_content=old,
            confidence=0.85,
            risks=["Callers that relied on the previous AttributeError (unlikely) must now catch NotFoundError."],
            acceptance_criterion="Calling get_order_total with an unknown order id raises a clear domain error instead of crashing.",
        )
    ]


# ---------------------------------------------------------------------------
# 3. Input validation on the registration endpoint
# ---------------------------------------------------------------------------
def input_validation(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/shopflow/api/auth.py"
    old = file_contents.get(path, "")
    if not old or "def register(" not in old:
        return []
    if "validate_email" in old and "validate_password_strength" in old and "utils.validation" not in old:
        # Already wired in a prior run of this strategy.
        if "from src.shopflow.utils.validation import validate_email" in old:
            return []

    new = old
    if "from src.shopflow.utils.validation import validate_email" not in new:
        new = new.replace(
            "from src.shopflow.services.notification_service import NotificationService\n",
            "from src.shopflow.services.notification_service import NotificationService\n"
            "from src.shopflow.utils.validation import validate_email, validate_password_strength\n",
            1,
        )
    if "from src.shopflow.exceptions import ValidationFailedError" not in new:
        new = new.replace(
            "from src.shopflow.api.deps import get_connection\n",
            "from src.shopflow.api.deps import get_connection\nfrom src.shopflow.exceptions import ValidationFailedError\n",
            1,
        )

    old_body = (
        "    # NOTE: does not currently call validate_email / validate_password_strength\n"
        "    # from src/shopflow/utils/validation.py — see module docstring.\n"
        "    user = AuthService(conn).register(payload.username, payload.email, payload.password)\n"
    )
    if old_body not in new:
        return []
    new_body = (
        "    if not validate_email(payload.email):\n"
        '        raise ValidationFailedError("Invalid email address")\n'
        "    if not validate_password_strength(payload.password):\n"
        "        raise ValidationFailedError(\n"
        '            "Password must be at least 8 characters and include a letter and a digit"\n'
        "        )\n"
        "    user = AuthService(conn).register(payload.username, payload.email, payload.password)\n"
    )
    new = new.replace(old_body, new_body, 1)

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
# 4. Session-token expiry
# ---------------------------------------------------------------------------
def auth_token_expiry(file_contents: dict[str, str]) -> list[MockChange]:
    path = "src/shopflow/services/auth_service.py"
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
        '        session_row = self.conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()\n'
        "        if session_row is None:\n"
        "            return None\n"
        '        return self._get_by_id(session_row["user_id"])\n'
    )
    new_validate = (
        '        session_row = self.conn.execute(\n'
        '            "SELECT user_id, issued_at FROM sessions WHERE token = ?", (token,)\n'
        "        ).fetchone()\n"
        "        if session_row is None:\n"
        "            return None\n"
        '        if time.time() - session_row["issued_at"] > self.SESSION_TOKEN_TTL_SECONDS:\n'
        '            self.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))\n'
        "            self.conn.commit()\n"
        "            return None\n"
        '        return self._get_by_id(session_row["user_id"])\n'
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
# 5. Payment idempotency (production-aware reliability scenario)
# ---------------------------------------------------------------------------
_OLD_CHARGE_SIGNATURE = (
    "    def charge_order(\n"
    "        self, order_id: int, amount: float, *, should_timeout: bool = False, should_decline: bool = False\n"
    "    ) -> Payment:\n"
    '        """Charge `order_id` for `amount` via the external payment\n'
    "        provider and move the order to CONFIRMED or FAILED accordingly.\n"
    '        See module docstring for the known gaps this method has."""\n'
    "        self.orders.mark_payment_pending(order_id)\n"
)
_NEW_CHARGE_SIGNATURE = (
    "    def charge_order(\n"
    "        self,\n"
    "        order_id: int,\n"
    "        amount: float,\n"
    "        *,\n"
    "        idempotency_key: str | None = None,\n"
    "        should_timeout: bool = False,\n"
    "        should_decline: bool = False,\n"
    "    ) -> Payment:\n"
    '        """Charge `order_id` for `amount` via the external payment\n'
    "        provider and move the order to CONFIRMED or FAILED accordingly.\n"
    "\n"
    "        If `idempotency_key` matches a previous payment for this order,\n"
    "        that payment is returned unchanged instead of contacting the\n"
    "        provider again — this is what makes a client retry after a\n"
    "        provider timeout (or a duplicated request) safe: it can never\n"
    "        create a second charge for the same logical payment attempt.\n"
    '        """\n'
    "        if idempotency_key is not None:\n"
    "            existing = self.conn.execute(\n"
    '                "SELECT * FROM payments WHERE order_id = ? AND idempotency_key = ?",\n'
    "                (order_id, idempotency_key),\n"
    "            ).fetchone()\n"
    "            if existing is not None:\n"
    "                return Payment.from_row(existing)\n"
    "\n"
    "        self.orders.mark_payment_pending(order_id)\n"
)

_OLD_FAILED_RECORD = (
    "            payment = self._record_payment(order_id, amount, PaymentStatus.FAILED, provider_charge_id=None)\n"
)
_NEW_FAILED_RECORD = (
    "            payment = self._record_payment(\n"
    "                order_id, amount, PaymentStatus.FAILED, provider_charge_id=None, idempotency_key=idempotency_key\n"
    "            )\n"
)

_OLD_CAPTURED_RECORD = (
    "        payment = self._record_payment(order_id, amount, PaymentStatus.CAPTURED, provider_charge_id=result.provider_charge_id)\n"
)
_NEW_CAPTURED_RECORD = (
    "        payment = self._record_payment(\n"
    "            order_id, amount, PaymentStatus.CAPTURED,\n"
    "            provider_charge_id=result.provider_charge_id, idempotency_key=idempotency_key,\n"
    "        )\n"
)

_OLD_RECORD_METHOD = (
    "    def _record_payment(\n"
    "        self, order_id: int, amount: float, status: PaymentStatus, provider_charge_id: str | None\n"
    "    ) -> Payment:\n"
    "        now = datetime.now(timezone.utc).isoformat()\n"
    "        cur = self.conn.execute(\n"
    '            "INSERT INTO payments (order_id, amount, status, provider_charge_id, idempotency_key, created_at, updated_at) "\n'
    '            "VALUES (?, ?, ?, ?, NULL, ?, ?)",\n'
    "            (order_id, amount, status.value, provider_charge_id, now, now),\n"
    "        )\n"
)
_NEW_RECORD_METHOD = (
    "    def _record_payment(\n"
    "        self,\n"
    "        order_id: int,\n"
    "        amount: float,\n"
    "        status: PaymentStatus,\n"
    "        provider_charge_id: str | None,\n"
    "        idempotency_key: str | None = None,\n"
    "    ) -> Payment:\n"
    "        now = datetime.now(timezone.utc).isoformat()\n"
    "        cur = self.conn.execute(\n"
    '            "INSERT INTO payments (order_id, amount, status, provider_charge_id, idempotency_key, created_at, updated_at) "\n'
    '            "VALUES (?, ?, ?, ?, ?, ?, ?)",\n'
    "            (order_id, amount, status.value, provider_charge_id, idempotency_key, now, now),\n"
    "        )\n"
)


_OLD_SCHEMA_BLOCK = (
    "class PaymentChargeRequest(BaseModel):\n"
    "    order_id: int\n"
    "    amount: float\n"
    "    should_timeout: bool = False\n"
    "    should_decline: bool = False\n"
)
_NEW_SCHEMA_BLOCK = (
    "class PaymentChargeRequest(BaseModel):\n"
    "    order_id: int\n"
    "    amount: float\n"
    "    idempotency_key: str | None = None\n"
    "    should_timeout: bool = False\n"
    "    should_decline: bool = False\n"
)

_OLD_API_CALL = (
    "    payment = PaymentService(conn).charge_order(\n"
    "        payload.order_id, payload.amount, should_timeout=payload.should_timeout, should_decline=payload.should_decline\n"
    "    )\n"
)
_NEW_API_CALL = (
    "    payment = PaymentService(conn).charge_order(\n"
    "        payload.order_id,\n"
    "        payload.amount,\n"
    "        idempotency_key=payload.idempotency_key,\n"
    "        should_timeout=payload.should_timeout,\n"
    "        should_decline=payload.should_decline,\n"
    "    )\n"
)


def payment_idempotency(file_contents: dict[str, str]) -> list[MockChange]:
    """Adds idempotency-key protection to the payment path. Three files
    cooperate to make the fix actually reachable by a real client rather
    than only by a direct service-layer call: the service method itself,
    the request schema that exposes the field over HTTP, and the API
    route that threads the value through. Each is patched independently
    — if retrieval only surfaces a subset of these files, this strategy
    changes only that subset (an honest, partial result) rather than
    requiring all three to be present."""
    changes: list[MockChange] = []

    service_path = "src/shopflow/services/payment_service.py"
    service_old = file_contents.get(service_path, "")
    if (
        service_old
        and "def charge_order" in service_old
        and _OLD_CHARGE_SIGNATURE in service_old
        and _OLD_RECORD_METHOD in service_old
    ):
        new = service_old
        new = new.replace(_OLD_CHARGE_SIGNATURE, _NEW_CHARGE_SIGNATURE, 1)
        new = new.replace(_OLD_FAILED_RECORD, _NEW_FAILED_RECORD, 1)
        new = new.replace(_OLD_CAPTURED_RECORD, _NEW_CAPTURED_RECORD, 1)
        new = new.replace(_OLD_RECORD_METHOD, _NEW_RECORD_METHOD, 1)
        changes.append(
            MockChange(
                file=service_path,
                operation="modify",
                reason=(
                    "Adds an idempotency-key lookup to PaymentService.charge_order so retrying a "
                    "charge (e.g. after the payment provider times out) returns the original "
                    "payment instead of creating a duplicate one."
                ),
                new_content=new,
                old_content=service_old,
                confidence=0.78,
                risks=[
                    "Idempotency lookup is keyed on (order_id, idempotency_key) within this SQLite "
                    "database, matching this demo repository's existing persistence model.",
                    "Callers that do not pass an idempotency_key are unaffected and remain unprotected against retries.",
                    "Rollback strategy: this change is additive (a new idempotency_key parameter with "
                    "a safe default of None) and requires no data migration, so it can be reverted by "
                    "rolling back the commit with no data-compatibility impact.",
                ],
                acceptance_criterion="Retrying charge_order with the same idempotency_key does not create a duplicate provider charge.",
            )
        )

    schema_path = "src/shopflow/schemas/payment.py"
    schema_old = file_contents.get(schema_path, "")
    if schema_old and _OLD_SCHEMA_BLOCK in schema_old:
        new = schema_old.replace(_OLD_SCHEMA_BLOCK, _NEW_SCHEMA_BLOCK, 1)
        changes.append(
            MockChange(
                file=schema_path,
                operation="modify",
                reason="Exposes idempotency_key on the payment-charge request schema so API clients can supply it.",
                new_content=new,
                old_content=schema_old,
                confidence=0.78,
                risks=["Optional field with a safe default — existing clients that omit it are unaffected."],
                acceptance_criterion="Clients can pass idempotency_key when charging a payment via the API.",
            )
        )

    api_path = "src/shopflow/api/payments.py"
    api_old = file_contents.get(api_path, "")
    if api_old and _OLD_API_CALL in api_old:
        new = api_old.replace(_OLD_API_CALL, _NEW_API_CALL, 1)
        changes.append(
            MockChange(
                file=api_path,
                operation="modify",
                reason="Threads the request's idempotency_key through to PaymentService.charge_order.",
                new_content=new,
                old_content=api_old,
                confidence=0.78,
                risks=["Depends on PaymentChargeRequest already exposing idempotency_key (schemas/payment.py)."],
                acceptance_criterion="POST /payments with a repeated idempotency_key does not create a duplicate payment.",
            )
        )

    return changes


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
