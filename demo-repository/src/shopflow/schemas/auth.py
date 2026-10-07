from __future__ import annotations

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type label, not a secret


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
