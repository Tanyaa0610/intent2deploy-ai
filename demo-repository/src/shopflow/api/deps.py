"""Shared FastAPI dependencies: database connection and authentication."""
from __future__ import annotations

import sqlite3

from fastapi import Depends, Header, Request

from src.shopflow.exceptions import ForbiddenError, UnauthenticatedError
from src.shopflow.models.user import User
from src.shopflow.services.auth_service import AuthService


def get_connection(request: Request) -> sqlite3.Connection:
    return request.app.state.db.conn


def get_current_user(
    authorization: str | None = Header(default=None), conn: sqlite3.Connection = Depends(get_connection)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthenticatedError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    user = AuthService(conn).validate_token(token)
    if user is None:
        raise UnauthenticatedError("Invalid or expired session token")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise ForbiddenError("This operation requires administrator privileges")
    return user
