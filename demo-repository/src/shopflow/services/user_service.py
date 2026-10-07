"""User lookup and account-status management."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.shopflow.exceptions import NotFoundError
from src.shopflow.models.user import User


class UserService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_id(self, user_id: int) -> User:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"User {user_id} not found")
        return User.from_row(row)

    def list_users(self) -> list[User]:
        rows = self.conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [User.from_row(r) for r in rows]

    def deactivate_user(self, user_id: int) -> User:
        """Mark a user inactive. Does NOT revoke that user's currently
        active session tokens — see AuthService.validate_token and
        evaluation/tasks/task_007.json, which closes that gap by also
        calling AuthService.revoke_all_sessions_for_user here."""
        self.get_by_id(user_id)  # raises NotFoundError if missing
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?", (now, user_id))
        self.conn.commit()
        return self.get_by_id(user_id)

    def activate_user(self, user_id: int) -> User:
        self.get_by_id(user_id)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE users SET is_active = 1, updated_at = ? WHERE id = ?", (now, user_id))
        self.conn.commit()
        return self.get_by_id(user_id)
