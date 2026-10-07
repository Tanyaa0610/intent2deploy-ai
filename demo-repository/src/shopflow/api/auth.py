"""Registration and login.

GAP (task_005.json): registration does not yet call
`utils.validation.validate_email` / `validate_password_strength` — both
exist and work, but are not wired in here.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection
from src.shopflow.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from src.shopflow.services.audit_service import AuditService
from src.shopflow.services.auth_service import AuthService
from src.shopflow.services.notification_service import NotificationService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, conn: sqlite3.Connection = Depends(get_connection)) -> UserResponse:
    # NOTE: does not currently call validate_email / validate_password_strength
    # from src/shopflow/utils/validation.py — see module docstring.
    user = AuthService(conn).register(payload.username, payload.email, payload.password)
    NotificationService(conn).notify_user_registered(user.id, user.username)
    AuditService(conn).record(user.id, "user.register", {"username": user.username})
    return UserResponse(id=user.id, username=user.username, email=user.email, role=user.role, is_active=user.is_active)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, conn: sqlite3.Connection = Depends(get_connection)) -> TokenResponse:
    token = AuthService(conn).login(payload.username, payload.password)
    user = AuthService(conn).validate_token(token)
    AuditService(conn).record(user.id if user else None, "user.login", {"username": payload.username})
    return TokenResponse(token=token)
