# ShopFlow API

A small, production-style e-commerce backend — the target repository
used by Intent2Deploy AI's demos and evaluation benchmark
(`evaluation/tasks/`). It is a genuinely working FastAPI + SQLite
application: it runs locally, its test suite passes, and it has real
(if deliberately incomplete in a few documented places — see
[Development limitations](#development-limitations)) business logic.

## 1. Project overview

ShopFlow manages the core of a small online store: users and
authentication, a product catalog, inventory, shopping carts, orders,
payments (against a mock external provider), refunds, notifications,
and an audit trail. It is intentionally scoped to be understandable in
one sitting, while still being realistic enough that a change in one
module (e.g. the payment provider) has real, traceable consequences in
another (e.g. order status).

## 2. Architecture

```
                         ┌─────────────────────┐
                         │   FastAPI app        │
                         │   (main.py)           │
                         └──────────┬────────────┘
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                  │
            api/*.py           api/deps.py        exceptions.py
        (routers, request/      (auth, DB            (-> HTTP
         response schemas)       connection)           status codes)
                 │
                 ▼
            services/*.py   <── business logic, one class per domain
                 │
        ┌────────┼─────────────────────┐
        ▼        ▼                     ▼
   database.py  integrations/      utils/
   (SQLite,     payment_provider.py validation.py
    schema)     (mock external      logging.py
                 payment SDK)        (structured, redacting)
```

Request flow: `api/*.py` (FastAPI routers) parse/validate the HTTP
request via `schemas/*.py` (Pydantic), resolve the caller via
`api/deps.py` (bearer token -> `User`), and delegate to a `services/*.py`
class, which executes real SQL against `database.py`'s SQLite
connection and returns a dataclass from `models/*.py`. Domain errors are
`exceptions.py` subclasses, mapped to HTTP status codes by one
exception handler in `main.py` — API responses are always a clean JSON
body, never a raw stack trace.

## 3. Repository structure

```
src/shopflow/
  main.py            FastAPI app, routers, exception handlers, startup
  config.py          Settings (env vars, with safe local defaults)
  database.py         SQLite schema + connection
  exceptions.py       Domain errors -> HTTP status codes
  seed.py              Idempotent demo-data seeding
  api/                 HTTP layer: one router per resource + deps.py
  schemas/              Pydantic request/response models
  models/                Dataclasses mapped from SQLite rows
  services/                Business logic, one class per domain
  integrations/              payment_provider.py (mock external SDK)
  utils/                       validation.py, logging.py
tests/                 pytest suite (one file per domain)
```

## 4. Business workflows

- **Auth**: register (CUSTOMER only — there is no self-service admin
  signup) -> login -> bearer session token -> every protected endpoint
  resolves the caller from that token.
- **Shopping**: browse `/products` -> add to `/cart` -> `/orders` creates
  an order from the cart (reserving inventory, snapshotting prices) ->
  `/payments` charges it -> admin advances `/orders/{id}/status` through
  fulfillment -> `/refunds` (admin) can refund a captured payment.

## 5. Setup

```bash
cd demo-repository
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional — safe defaults apply without this
```

## 6. Environment variables

See `.env.example` for the full list (all optional, all with safe
local-development defaults): `SHOPFLOW_DB_PATH`,
`SHOPFLOW_SESSION_TTL_SECONDS`, `SHOPFLOW_RESET_TOKEN_TTL_SECONDS`,
`SHOPFLOW_LOW_STOCK_THRESHOLD`, `SHOPFLOW_MAX_QUANTITY_PER_PRODUCT`,
`SHOPFLOW_SEED_ON_STARTUP`.

## 7. Running the API

```bash
uvicorn src.shopflow.main:app --reload --port 8001
```

Then `curl http://127.0.0.1:8001/health` should return
`{"status": "ok", "service": "shopflow"}`. With seeding enabled (the
default), an admin and a customer account already exist — see
[Seed / demo credentials](#seed--demo-credentials) below.

## 8. Running tests

```bash
python3 -m pytest -q
```

Every test runs against its own isolated, unseeded, temporary SQLite
database (see `tests/conftest.py`) — tests never touch
`shopflow.db` or each other's data.

## 9. API examples

```bash
# Register + log in
curl -X POST localhost:8001/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"StrongPass123"}'
TOKEN=$(curl -s -X POST localhost:8001/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"StrongPass123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Browse products, add to cart, place an order
curl localhost:8001/products
curl -X POST localhost:8001/cart/items -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"product_id": 1, "quantity": 2}'
curl -X POST localhost:8001/orders -H "Authorization: Bearer $TOKEN"

# Pay for order 1
curl -X POST localhost:8001/payments -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"order_id": 1, "amount": 39.98}'
```

## 10. Authentication

Bearer session tokens (`Authorization: Bearer <token>`), issued on
login and resolved to a `User` on every protected request (see
`api/deps.py`). Passwords are hashed with SHA-256 + a per-user salt —
intentionally simple for a demo fixture (see
[Development limitations](#development-limitations)). Roles are
`CUSTOMER` and `ADMIN`; admin-only endpoints are enforced via the
`require_admin` dependency (with one deliberate exception — see below).

## 11. Order lifecycle

```
PENDING --(pay)--> PAYMENT_PENDING --(captured)--> CONFIRMED
                                    \-(failed)----> FAILED

CONFIRMED --(admin)--> PROCESSING --(admin)--> SHIPPED --(admin)--> DELIVERED

PENDING / PAYMENT_PENDING / CONFIRMED / PROCESSING --(cancel)--> CANCELLED
```

Creating an order reserves (decrements) inventory immediately.
Cancelling a `DELIVERED`, `CANCELLED`, or `FAILED` order is rejected.

## 12. Payment lifecycle

`PaymentService.charge_order` calls `integrations/payment_provider.py`'s
`PaymentProviderClient` (a self-contained mock — no real network calls).
A charge either succeeds (`CAPTURED`), is declined
(`PaymentProviderDeclined`), or times out (`PaymentProviderTimeout`,
injectable via `should_timeout=True` for tests/demos) — both failure
modes are recorded as a `FAILED` payment and a `payment_failed`
notification.

## 13. Seed / demo credentials

On startup (when `SHOPFLOW_SEED_ON_STARTUP=true`, the default), ShopFlow
seeds, idempotently:

| Username | Password | Role |
|---|---|---|
| `admin` | `AdminPass123` | ADMIN |
| `customer1` | `CustomerPass123` | CUSTOMER |

...plus 5 products at varying inventory levels (including one at 3
units — below the default low-stock threshold of 5 — and one at 0).

**These are local-only development credentials for a SQLite fixture
database, not real secrets.** Never reuse them anywhere else.

## 14. Development limitations

Intentional, documented gaps — each is the target of a specific
evaluation task (`evaluation/tasks/task_*.json`), not an oversight:

- Password hashing is SHA-256 + per-user salt, not a production KDF
  (bcrypt/argon2) — a teaching/demo simplification.
- There is no password-reset flow yet (`task_001.json`).
- Session tokens never expire (`task_006.json`).
- `OrderService.get_order_total` does not guard against an unknown
  order id (`task_002.json`, `task_003.json`).
- Deactivating a user does not revoke their already-issued session
  tokens (`task_007.json`).
- Registration does not call the existing `validate_email` /
  `validate_password_strength` helpers (`task_005.json`).
- `PaymentService.charge_order` has no idempotency-key protection, so a
  client retry after a provider timeout can create a duplicate charge
  (`task_011.json`, `task_012.json`).
- A provider timeout is not automatically retried (`task_016.json`).
- Payment failures are not yet logged through the structured,
  redacting logger in `utils/logging.py` (`task_017.json`).
- There is no maximum per-product quantity limit in the cart/order flow
  (`task_018.json`).
- Cancelling a `SHIPPED` order is not blocked, unlike `DELIVERED`
  (`task_014.json`).
- Cancelling an order does not restore the inventory it reserved
  (`task_019.json`).
- `OrderService.apply_payment_result` checks the charged amount rather
  than the payment's actual status, so a declined/timed-out payment can
  still confirm the order (`task_021.json`).
- `RefundService.create_refund` does not check that the payment reached
  `CAPTURED` status (`task_020.json`).
- `POST /inventory/{id}/adjust` is authorized with `get_current_user`
  instead of `require_admin`, unlike every other write endpoint
  (`task_015.json`).

None of these are placeholders or stubs — every endpoint above is
real, callable, and covered by passing tests for its *current* (if
incomplete) behavior; the gaps are specific, narrow, and exist so that
Intent2Deploy has genuine multi-file changes to reason about.
