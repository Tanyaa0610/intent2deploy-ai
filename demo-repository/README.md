# Demo Repository

A small, intentionally-designed Python service used as the fixture
repository for Intent2Deploy AI demos and the evaluation benchmark
(`evaluation/tasks/`).

## Structure

```
src/
  auth/        authentication: register, login, token issuance
  users/       user model + in-memory repository
  orders/      order service (contains a deliberate bug for the bug-fix demo task)
  validation/  input validation helpers (deliberately under-used, for the
               "add input validation" demo task)
  api/         FastAPI HTTP layer wiring the above together
tests/         pytest test suite (regression baseline)
```

## Running

```bash
pip install -r requirements.txt
pytest
```

## Known limitations (intentional, for demo purposes)

- Password hashing uses SHA-256 + per-user salt for simplicity. This is
  **not** production-grade (a real system should use bcrypt/argon2) — the
  demo repository is a teaching fixture, not a security reference.
- `OrderService.get_order_total` does not guard against a missing order
  (deliberate bug used by the "fix the null-reference bug" benchmark task).
- The registration endpoint does not call `validation.helpers.validate_email`
  or `validate_password_strength` (deliberate gap used by the "add input
  validation" benchmark task).
- There is no password-reset flow yet (used by the primary "add a
  password-reset feature" demo task).
