"""Authentication service: registration, login, and session tokens.

NOTE: password hashing here (SHA-256 + per-user salt) is intentionally
simple for a teaching/demo fixture; it is not a production-grade KDF
(a real system should use bcrypt/argon2 — see README "Development
limitations").

There is currently no password-reset flow and no session-token expiry —
both are left as realistic gaps for Intent2Deploy to close (see
evaluation/tasks/task_001.json and task_006.json).
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from src.shopflow.exceptions import ConflictError, UnauthenticatedError
from src.shopflow.models.enums import UserRole
from src.shopflow.models.user import User


class AuthService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    def register(self, username: str, email: str, password: str, role: UserRole = UserRole.CUSTOMER) -> User:
        existing = self.conn.execute(
            "SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()
        if existing is not None:
            raise ConflictError(f"A user with username '{username}' or email '{email}' already exists")

        salt = secrets.token_hex(8)
        password_hash = self._hash_password(password, salt)
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO users (username, email, password_hash, salt, role, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (username, email, password_hash, salt, role.value, now, now),
        )
        self.conn.commit()
        return self._get_by_id(cur.lastrowid)

    def login(self, username: str, password: str) -> str:
        """Authenticate a user and return a session token.

        Raises UnauthenticatedError if the username is unknown, the
        password does not match, or the account is disabled.
        """
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise UnauthenticatedError("Invalid username or password")
        user = User.from_row(row)
        expected = self._hash_password(password, user.salt)
        if expected != user.password_hash:
            raise UnauthenticatedError("Invalid username or password")
        if not user.is_active:
            raise UnauthenticatedError("This account has been deactivated")

        token = secrets.token_urlsafe(24)
        self.conn.execute(
            "INSERT INTO sessions (token, user_id, issued_at) VALUES (?, ?, ?)", (token, user.id, time.time())
        )
        self.conn.commit()
        return token

    def validate_token(self, token: str) -> User | None:
        """Resolve a session token to its user, or None if the token is
        unknown.

        BUG (evaluation/tasks/task_007.json): does not check whether the
        user has since been deactivated, so a token issued before
        deactivation remains valid until it is explicitly logged out.
        """
        session_row = self.conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        if session_row is None:
            return None
        return self._get_by_id(session_row["user_id"])

    def logout(self, token: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.conn.commit()

    def revoke_all_sessions_for_user(self, user_id: int) -> None:
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def _get_by_id(self, user_id: int) -> User:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User.from_row(row)
