"""User model and an in-memory user repository.

The demo application uses an in-memory store rather than a real database
so the fixture repository has no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    id: int
    username: str
    email: str
    password_hash: str
    salt: str
    is_active: bool = True


class UserRepository:
    """A minimal in-memory user store keyed by username."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._next_id = 1

    def create(self, username: str, email: str, password_hash: str, salt: str) -> User:
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        user = User(
            id=self._next_id,
            username=username,
            email=email,
            password_hash=password_hash,
            salt=salt,
        )
        self._users[username] = user
        self._next_id += 1
        return user

    def get_by_username(self, username: str) -> User | None:
        return self._users.get(username)

    def get_by_id(self, user_id: int) -> User | None:
        for user in self._users.values():
            if user.id == user_id:
                return user
        return None

    def update_password(self, username: str, password_hash: str, salt: str) -> None:
        user = self._users.get(username)
        if user is None:
            raise KeyError(f"User '{username}' does not exist")
        user.password_hash = password_hash
        user.salt = salt

    def all(self) -> list[User]:
        return list(self._users.values())
