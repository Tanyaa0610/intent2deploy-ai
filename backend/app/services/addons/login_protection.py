"""Add-on: protect sign-in against password guessing (rate limiting).

After 5 wrong passwords for an email within 15 minutes, further sign-in
attempts for it are refused with 429 until the window passes (a correct
password does not get through while blocked). Password-reset codes can be
requested at most 3 times per email per 15 minutes.
"""
from __future__ import annotations

RATELIMIT_PY = r'''"""Sliding-window rate limiting (in memory, per process)."""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, window: float) -> deque[float]:
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= window:
            hits.popleft()
        return hits

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until `key` may try again (0 = allowed now)."""
        with self._lock:
            hits = self._recent(key, window)
            return 0 if len(hits) < limit else max(1, int(window - (self._clock() - hits[0])) + 1)

    def hit(self, key: str) -> None:
        with self._lock:
            self._hits.setdefault(key, deque()).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
'''

LOGIN_LIMIT, RESET_LIMIT, WINDOW = 5, 3, 15 * 60

SETTINGS = f'''limiter = RateLimiter()
LOGIN_ATTEMPTS, RESET_REQUESTS, LIMIT_WINDOW = {LOGIN_LIMIT}, {RESET_LIMIT}, {WINDOW}  # per email, per 15 minutes


def _too_many(seconds: int, what: str) -> HTTPException:
    minutes = max(1, (seconds + 59) // 60)
    return HTTPException(status_code=429, detail=f"Too many {{what}}. Try again in {{minutes}} minute(s).",
                         headers={{"Retry-After": str(seconds)}})
'''

LOGIN_OLD = '''    token = store.authenticate(body.email, body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
'''
LOGIN_NEW = '''    key = f"login:{store.normalize(body.email)}"
    wait = limiter.retry_after(key, LOGIN_ATTEMPTS, LIMIT_WINDOW)
    if wait:
        raise _too_many(wait, "sign-in attempts")
    token = store.authenticate(body.email, body.password)
    if token is None:
        limiter.hit(key)
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    limiter.reset(key)
'''
RESET_OLD = '''    code = store.request_reset(body.email)
'''
RESET_NEW = '''    key = f"reset:{store.normalize(body.email)}"
    wait = limiter.retry_after(key, RESET_REQUESTS, LIMIT_WINDOW)
    if wait:
        raise _too_many(wait, "reset code requests")
    limiter.hit(key)
    code = store.request_reset(body.email)
'''

TEST = r'''from fastapi.testclient import TestClient

from app import main
from app.ratelimit import RateLimiter


def client() -> TestClient:
    main.store = main.UserStore()
    main.limiter = main.RateLimiter()
    return TestClient(main.app)


def test_sign_in_is_blocked_after_repeated_wrong_passwords():
    c = client()
    c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"})
    for _ in range(5):
        assert c.post("/api/login", json={"email": "ana@example.com", "password": "wrong-pass1"}).status_code == 401
    blocked = c.post("/api/login", json={"email": "ana@example.com", "password": "correct-horse"})
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    other = c.post("/api/login", json={"email": "other@example.com", "password": "whatever-1"})
    assert other.status_code == 401  # other accounts are not affected


def test_successful_sign_in_clears_failures():
    c = client()
    c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"})
    for _ in range(4):
        c.post("/api/login", json={"email": "ana@example.com", "password": "wrong-pass1"})
    assert c.post("/api/login", json={"email": "ana@example.com", "password": "correct-horse"}).status_code == 200
    assert c.post("/api/login", json={"email": "ana@example.com", "password": "wrong-pass1"}).status_code == 401


def test_limit_window_expires():
    now = [1000.0]
    limiter = RateLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.hit("k")
    assert limiter.retry_after("k", 5, 900) > 0
    now[0] += 901
    assert limiter.retry_after("k", 5, 900) == 0
'''

TEST_RESET = r'''

def test_reset_code_requests_are_limited():
    c = client()
    for _ in range(3):
        assert c.post("/api/password-reset/request", json={"email": "ana@example.com"}).status_code == 200
    assert c.post("/api/password-reset/request", json={"email": "ana@example.com"}).status_code == 429
'''

IMPORT_ANCHOR = "from app.users import "


def applicable(files: dict[str, str]) -> bool:
    main = files.get("app/main.py", "")
    return LOGIN_OLD in main and "store = UserStore()\n" in main and IMPORT_ANCHOR in main


def applied(files: dict[str, str]) -> bool:
    return "app/ratelimit.py" in files or "RateLimiter" in files.get("app/main.py", "")


def apply(files: dict[str, str]) -> dict[str, str]:
    main = files["app/main.py"]
    line_end = main.index("\n", main.index(IMPORT_ANCHOR)) + 1
    main = main[:line_end] + "from app.ratelimit import RateLimiter\n" + main[line_end:]
    main = main.replace("store = UserStore()\n", "store = UserStore()\n" + SETTINGS, 1)
    main = main.replace(LOGIN_OLD, LOGIN_NEW, 1)
    test = TEST
    if RESET_OLD in main:
        main = main.replace(RESET_OLD, RESET_NEW, 1)
        test += TEST_RESET
    return {"app/main.py": main, "app/ratelimit.py": RATELIMIT_PY, "tests/test_login_protection.py": test}
