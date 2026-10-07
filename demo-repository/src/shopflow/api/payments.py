from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user
from src.shopflow.exceptions import ForbiddenError
from src.shopflow.models.payment import Payment
from src.shopflow.models.user import User
from src.shopflow.schemas.payment import PaymentChargeRequest, PaymentResponse
from src.shopflow.services.order_service import OrderService
from src.shopflow.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def _to_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        order_id=payment.order_id,
        amount=payment.amount,
        status=payment.status,
        provider_charge_id=payment.provider_charge_id,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


@router.post("", response_model=PaymentResponse, status_code=201)
def charge(
    payload: PaymentChargeRequest,
    user: User = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_connection),
) -> PaymentResponse:
    order = OrderService(conn).get_order_or_404(payload.order_id)
    if not user.is_admin and order.user_id != user.id:
        raise ForbiddenError("Cannot pay for an order that does not belong to you")
    payment = PaymentService(conn).charge_order(
        payload.order_id, payload.amount, should_timeout=payload.should_timeout, should_decline=payload.should_decline
    )
    return _to_response(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: int, user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> PaymentResponse:
    payment = PaymentService(conn).get_by_id(payment_id)
    order = OrderService(conn).get_order_or_404(payment.order_id)
    if not user.is_admin and order.user_id != user.id:
        raise ForbiddenError("Cannot view a payment for an order that does not belong to you")
    return _to_response(payment)
