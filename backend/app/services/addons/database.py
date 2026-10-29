"""Add-on: save data permanently in a SQLite database (a proper backend).

Replaces the in-memory store of a generated project with a SQLite-backed one
that has exactly the same interface, so the API, pages and existing tests
keep working. The database lives at DATABASE_PATH (default data/app.db); in
Docker it is kept in a named volume so it survives container restarts and
redeploys. Tests use an in-memory database.
"""
from __future__ import annotations

USERS_PY = r'''"""User accounts stored in a SQLite database (DATABASE_PATH, default
data/app.db): salted PBKDF2 password hashing, sessions and single-use
password-reset codes. Data survives restarts."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
RESET_CODE_TTL_SECONDS = 15 * 60
RESET_MAX_ATTEMPTS = 5
_ITERATIONS = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reset_codes (
    email TEXT PRIMARY KEY REFERENCES users(email) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""


class AccountExistsError(Exception):
    pass


class InvalidAccountError(ValueError):
    pass


class InvalidResetCodeError(ValueError):
    pass


@dataclass
class User:
    email: str
    salt: bytes
    password_hash: bytes


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    return db


class UserStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("DATABASE_PATH", "data/app.db")
        self._db = connect(self.path)
        self._lock = threading.Lock()

    @staticmethod
    def normalize(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidAccountError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    def register(self, email: str, password: str) -> User:
        email = self.normalize(email)
        if not EMAIL_RE.match(email):
            raise InvalidAccountError("Enter a valid email address.")
        self._check_password(password)
        user = User(email=email, salt=secrets.token_bytes(16), password_hash=b"")
        user.password_hash = _hash(password, user.salt)
        with self._lock:
            try:
                with self._db:
                    self._db.execute(
                        "INSERT INTO users (email, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                        (email, user.salt, user.password_hash, time.time()),
                    )
            except sqlite3.IntegrityError as exc:
                raise AccountExistsError("An account with this email already exists.") from exc
        return user

    def _user(self, email: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM users WHERE email = ?", (self.normalize(email),)).fetchone()

    def authenticate(self, email: str, password: str) -> str | None:
        """Return a new session token, or None if the credentials are wrong."""
        with self._lock:
            row = self._user(email)
        if row is None:
            # Hash anyway so response time does not reveal whether the email exists.
            _hash(password, secrets.token_bytes(16))
            return None
        if not hmac.compare_digest(_hash(password, row["salt"]), row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock, self._db:
            # Only a hash of the token is stored: a leaked database can't be used to sign in.
            self._db.execute("INSERT INTO sessions (token_hash, email, created_at) VALUES (?, ?, ?)",
                             (_sha256(token), row["email"], time.time()))
        return token

    def user_for_token(self, token: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT email FROM sessions WHERE token_hash = ?", (_sha256(token),)).fetchone()
        return row["email"] if row else None

    # -- password reset ------------------------------------------------------
    def request_reset(self, email: str, now: float | None = None) -> str | None:
        """A new 6-digit reset code for the account, or None if there is no such
        account. Callers must answer the same way in both cases."""
        email = self.normalize(email)
        with self._lock:
            if self._user(email) is None:
                return None
            code = f"{secrets.randbelow(1_000_000):06d}"
            with self._db:
                self._db.execute(
                    "INSERT OR REPLACE INTO reset_codes (email, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0)",
                    (email, _sha256(code), (now or time.time()) + RESET_CODE_TTL_SECONDS),
                )
        return code

    def reset_password(self, email: str, code: str, new_password: str, now: float | None = None) -> None:
        email = self.normalize(email)
        self._check_password(new_password)
        with self._lock, self._db:
            pending = self._db.execute("SELECT * FROM reset_codes WHERE email = ?", (email,)).fetchone()
            expired = pending is None or (now or time.time()) > pending["expires_at"]
            if expired or pending["attempts"] >= RESET_MAX_ATTEMPTS:
                self._db.execute("DELETE FROM reset_codes WHERE email = ?", (email,))
                raise InvalidResetCodeError("This reset code is invalid or has expired. Request a new one.")
            if not hmac.compare_digest(pending["code_hash"], _sha256(code.strip())):
                self._db.execute("UPDATE reset_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
                self._db.commit()
                raise InvalidResetCodeError("That code is not correct.")
            salt = secrets.token_bytes(16)
            self._db.execute("UPDATE users SET salt = ?, password_hash = ? WHERE email = ?",
                             (salt, _hash(new_password, salt), email))
            self._db.execute("DELETE FROM reset_codes WHERE email = ?", (email,))  # single use
            # Sign out everywhere: a reset usually means the old password is compromised.
            self._db.execute("DELETE FROM sessions WHERE email = ?", (email,))
'''

RECORDS_PY = r'''"""Records stored in a SQLite database (DATABASE_PATH, default data/app.db)
with search, filtering, sorting and stats. Data survives restarts."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
from pathlib import Path

from app.models import STATUSES, Record, RecordIn

SORTS = ("newest", "oldest", "name", "date")
_ORDER = {
    "oldest": "id ASC",
    "name": "lower(name) ASC, id ASC",
    "date": "date IS NULL, date ASC, id ASC",
    "newest": "id DESC",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS records_status ON records (status);
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    if path != ":memory:":
        db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    return db


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _record(row: sqlite3.Row) -> Record:
    return Record(**dict(row))


class RecordStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("DATABASE_PATH", "data/app.db")
        self._db = connect(self.path)
        self._lock = threading.Lock()

    def create(self, data: RecordIn) -> Record:
        now = _now()
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO records (name, description, status, date, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (data.name, data.description, data.status, _iso(data.date), now, now),
            )
            row = self._db.execute("SELECT * FROM records WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _record(row)

    def get(self, record_id: int) -> Record | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return _record(row) if row else None

    def update(self, record_id: int, data: RecordIn) -> Record | None:
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE records SET name = ?, description = ?, status = ?, date = ?, updated_at = ? WHERE id = ?",
                (data.name, data.description, data.status, _iso(data.date), _now(), record_id),
            )
        return self.get(record_id) if cur.rowcount else None

    def delete(self, record_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM records WHERE id = ?", (record_id,)).rowcount > 0

    def list(self, q: str = "", status: str = "", sort: str = "newest") -> list[Record]:
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(status)
        term = q.strip().lower()
        if term:
            where.append("(instr(lower(name), ?) > 0 OR instr(lower(description), ?) > 0)")
            args += [term, term]
        # Only fixed, allow-listed fragments are joined; every value is a "?" parameter.
        sql = "SELECT * FROM records" + (" WHERE " + " AND ".join(where) if where else "")  # noqa: S608
        sql += " ORDER BY " + _ORDER.get(sort, _ORDER["newest"])
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [_record(r) for r in rows]

    def stats(self) -> dict:
        counts = {s: 0 for s in STATUSES}
        with self._lock:
            for row in self._db.execute("SELECT status, COUNT(*) AS n FROM records GROUP BY status"):
                counts[row["status"]] = row["n"]
        return {"total": sum(counts.values()), **counts}
'''

TESTS_CONFTEST = '''"""Tests use a fresh in-memory database (set before the app is imported)."""
import os

os.environ.setdefault("DATABASE_PATH", ":memory:")
'''

TEST_USERS_PERSISTENCE = r'''import sqlite3

from app.users import UserStore


def test_accounts_and_sessions_survive_a_restart(tmp_path):
    path = str(tmp_path / "app.db")
    first = UserStore(path)
    first.register("ana@example.com", "correct-horse")
    token = first.authenticate("ana@example.com", "correct-horse")
    restarted = UserStore(path)  # a new server process opening the same database
    assert restarted.authenticate("ana@example.com", "correct-horse")
    assert restarted.user_for_token(token) == "ana@example.com"


def test_reset_codes_survive_a_restart(tmp_path):
    path = str(tmp_path / "app.db")
    first = UserStore(path)
    first.register("ana@example.com", "correct-horse")
    code = first.request_reset("ana@example.com")
    UserStore(path).reset_password("ana@example.com", code, "brand-new-pass")
    assert UserStore(path).authenticate("ana@example.com", "brand-new-pass")


def test_secrets_are_not_stored_in_plain_text(tmp_path):
    path = str(tmp_path / "app.db")
    store = UserStore(path)
    store.register("ana@example.com", "correct-horse")
    token = store.authenticate("ana@example.com", "correct-horse")
    code = store.request_reset("ana@example.com")
    dump = "\n".join(sqlite3.connect(path).iterdump())
    assert "correct-horse" not in dump and token not in dump and code not in dump
'''

TEST_RECORDS_PERSISTENCE = r'''import datetime as dt

from app.models import RecordIn
from app.store import RecordStore


def test_records_survive_a_restart(tmp_path):
    path = str(tmp_path / "app.db")
    first = RecordStore(path)
    created = first.create(RecordIn(name="Kept", description="saved", status="confirmed", date=dt.date(2030, 1, 2)))
    restarted = RecordStore(path)  # a new server process opening the same database
    again = restarted.get(created.id)
    assert again == created and again.date == dt.date(2030, 1, 2)
    assert restarted.stats()["confirmed"] == 1


def test_search_is_not_confused_by_sql_characters(tmp_path):
    store = RecordStore(str(tmp_path / "app.db"))
    store.create(RecordIn(name="100% done_now"))
    store.create(RecordIn(name="Other"))
    assert [r.name for r in store.list(q="%")] == ["100% done_now"]
    assert [r.name for r in store.list(q="_now")] == ["100% done_now"]
    assert store.list(q="' OR '1'='1") == []
'''


def _dockerfile(text: str) -> str:
    """The app runs as a non-root user: give it a writable data folder."""
    if "/app/data" in text or "USER appuser" not in text:
        return text
    return text.replace("USER appuser", "RUN mkdir -p /app/data && chown appuser /app/data\nUSER appuser", 1)


def _compose(text: str) -> str:
    """Keep the database in a named volume, so it survives restarts and redeploys."""
    if "app-data:" in text or "restart: unless-stopped" not in text:
        return text
    return (text.replace("    restart: unless-stopped", "    restart: unless-stopped\n    volumes:\n      - app-data:/app/data", 1)
            .rstrip("\n") + "\n\nvolumes:\n  app-data:\n")


def _ignore(text: str, entry: str) -> str:
    lines = text.splitlines()
    return text if entry in lines else (text.rstrip("\n") + ("\n" if text.strip() else "") + entry + "\n")


def _readme(text: str) -> str:
    if "## Database" in text:
        return text
    return text.rstrip("\n") + "\n\n## Database\n\nData is saved in SQLite at `DATABASE_PATH` (default `data/app.db`), so it survives restarts.\n" \
        "With Docker Compose it is kept in the `app-data` volume. Back it up by copying the file while the app is stopped.\n"


def kind(files: dict[str, str]) -> str:
    users = files.get("app/users.py", "")
    store = files.get("app/store.py", "")
    if "class UserStore" in users and "In-memory user accounts" in users:
        return "users"
    if "class RecordStore" in store and "In-memory storage with search" in store:
        return "records"
    return ""


def applied(files: dict[str, str]) -> bool:
    return "sqlite3" in files.get("app/users.py", "") or "sqlite3" in files.get("app/store.py", "")


def apply(files: dict[str, str]) -> dict[str, str]:
    which = kind(files)
    out: dict[str, str] = {}
    if which == "users":
        out["app/users.py"] = USERS_PY
        out["tests/test_persistence.py"] = TEST_USERS_PERSISTENCE
    else:
        out["app/store.py"] = RECORDS_PY
        out["tests/test_persistence.py"] = TEST_RECORDS_PERSISTENCE
    if "tests/conftest.py" not in files:
        out["tests/conftest.py"] = TESTS_CONFTEST
    for path, fix in (("Dockerfile", _dockerfile), ("docker-compose.yml", _compose), ("README.md", _readme)):
        if path in files and fix(files[path]) != files[path]:
            out[path] = fix(files[path])
    out[".gitignore"] = _ignore(_ignore(files.get(".gitignore", ""), "data/"), "*.db")
    if ".dockerignore" in files and "data/" not in files[".dockerignore"].splitlines():
        out[".dockerignore"] = _ignore(files[".dockerignore"], "data/")
    return out
