from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.shopflow.models.enums import UserRole


@dataclass
class User:
    id: int
    username: str
    email: str
    password_hash: str
    salt: str
    role: str
    is_active: bool
    created_at: str
    updated_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "User":
        return cls(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            role=row["role"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
