from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user, require_admin
from src.shopflow.models.order import Order
from src.shopflow.models.user import User
from src.shopflow.schemas.auth import UserResponse
from src.shopflow.schemas.order import OrderItemResponse, OrderResponse
from src.shopflow.services.audit_service import AuditService
from src.shopflow.services.order_service import OrderService
from src.shopflow.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _to_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, email=user.email, role=user.role, is_active=user.is_active)


def _order_to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        status=order.status,
        total=order.total,
        items=[
            OrderItemResponse(product_id=i.product_id, product_name=i.product_name, quantity=i.quantity, unit_price=i.unit_price)
            for i in order.items
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return _to_response(user)


@router.get("/me/orders", response_model=list[OrderResponse])
def get_my_orders(
    user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> list[OrderResponse]:
    orders = OrderService(conn).list_orders_for_user(user.id)
    return [_order_to_response(o) for o in orders]


@router.get("", response_model=list[UserResponse])
def list_users(_admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)) -> list[UserResponse]:
    return [_to_response(u) for u in UserService(conn).list_users()]


@router.post("/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: int, admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)
) -> UserResponse:
    user = UserService(conn).deactivate_user(user_id)
    AuditService(conn).record(admin.id, "user.deactivate", {"target_user_id": user_id})
    return _to_response(user)
