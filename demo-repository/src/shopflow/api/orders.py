from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user, require_admin
from src.shopflow.exceptions import ForbiddenError
from src.shopflow.models.enums import OrderStatus
from src.shopflow.models.order import Order
from src.shopflow.models.user import User
from src.shopflow.schemas.order import OrderItemResponse, OrderResponse, OrderStatusUpdateRequest
from src.shopflow.services.audit_service import AuditService
from src.shopflow.services.notification_service import NotificationService
from src.shopflow.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_response(order: Order) -> OrderResponse:
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


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(
    user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> OrderResponse:
    order = OrderService(conn).create_order_from_cart(user.id)
    NotificationService(conn).notify_order_created(order.id, user.id, order.total)
    AuditService(conn).record(user.id, "order.create", {"order_id": order.id, "total": order.total})
    return _to_response(order)


@router.get("", response_model=list[OrderResponse])
def list_all_orders(
    _admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)
) -> list[OrderResponse]:
    rows = conn.execute("SELECT id FROM orders ORDER BY id DESC").fetchall()
    service = OrderService(conn)
    return [_to_response(service.get_order_or_404(r["id"])) for r in rows]


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int, user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> OrderResponse:
    order = OrderService(conn).get_order_or_404(order_id)
    if not user.is_admin and order.user_id != user.id:
        raise ForbiddenError("Cannot view an order that does not belong to you")
    return _to_response(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int, user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> OrderResponse:
    order = OrderService(conn).cancel_order(order_id, requesting_user_id=user.id, is_admin=user.is_admin)
    AuditService(conn).record(user.id, "order.cancel", {"order_id": order_id})
    return _to_response(order)


@router.patch("/{order_id}/status", response_model=OrderResponse)
def advance_order_status(
    order_id: int,
    payload: OrderStatusUpdateRequest,
    admin: User = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_connection),
) -> OrderResponse:
    order = OrderService(conn).advance_status(order_id, OrderStatus(payload.status))
    AuditService(conn).record(admin.id, "order.status_change", {"order_id": order_id, "new_status": payload.status})
    return _to_response(order)
