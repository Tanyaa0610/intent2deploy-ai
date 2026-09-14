"""Authentication service: registration, login, and session tokens.

NOTE: password hashing here (SHA-256 + per-user salt) is intentionally
simple for a teaching fixture; it is not a production-grade KDF.

There is currently no password-reset flow — that is the primary feature
added by the Intent2Deploy AI demo workflow.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from src.users.model import User, UserRepository


class InvalidCredentialsError(Exception):
    pass


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
        self.users = user_repository
        self._active_tokens: dict[str, tuple[str, float]] = {}  # token -> (username, issued_at)

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    def register(self, username: str, email: str, password: str) -> User:
        salt = secrets.token_hex(8)
        password_hash = self._hash_password(password, salt)
        return self.users.create(username, email, password_hash, salt)

    def login(self, username: str, password: str) -> str:
        """Authenticate a user and return a session token.

        Raises InvalidCredentialsError if the username does not exist or
        the password does not match.
        """
        user = self.users.get_by_username(username)
        if user is None:
            raise InvalidCredentialsError("Unknown username or password")
        expected = self._hash_password(password, user.salt)
        if expected != user.password_hash:
            raise InvalidCredentialsError("Unknown username or password")
        if not user.is_active:
            raise InvalidCredentialsError("Account is disabled")
        token = secrets.token_urlsafe(24)
        self._active_tokens[token] = (username, time.time())
        return token

    def validate_token(self, token: str) -> str | None:
        entry = self._active_tokens.get(token)
        if entry is None:
            return None
        username, _issued_at = entry
        return username

    def logout(self, token: str) -> None:
        self._active_tokens.pop(token, None)
