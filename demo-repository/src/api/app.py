"""FastAPI HTTP layer wiring the auth/users/orders services together."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.auth.service import AuthService, InvalidCredentialsError
from src.orders.service import OrderService
from src.users.model import UserRepository

app = FastAPI(title="Demo Repository API")

user_repository = UserRepository()
auth_service = AuthService(user_repository)
order_service = OrderService()


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/register")
def register(payload: RegisterRequest) -> dict:
    # NOTE: does not currently call validation.helpers.validate_email or
    # validate_password_strength — see demo-repository/README.md.
    try:
        user = auth_service.register(payload.username, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": user.id, "username": user.username, "email": user.email}


@app.post("/login")
def login(payload: LoginRequest) -> dict:
    try:
        token = auth_service.login(payload.username, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"token": token}


@app.get("/orders/{order_id}/total")
def order_total(order_id: int) -> dict:
    total = order_service.get_order_total(order_id)
    return {"order_id": order_id, "total": total}
