from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user, require_admin
from src.shopflow.exceptions import ForbiddenError
from src.shopflow.models.payment import Refund
from src.shopflow.models.user import User
from src.shopflow.schemas.refund import RefundCreateRequest, RefundResponse
from src.shopflow.services.order_service import OrderService
from src.shopflow.services.payment_service import PaymentService
from src.shopflow.services.refund_service import RefundService

router = APIRouter(prefix="/refunds", tags=["refunds"])


def _to_response(refund: Refund) -> RefundResponse:
    return RefundResponse(
        id=refund.id, payment_id=refund.payment_id, amount=refund.amount, status=refund.status, reason=refund.reason,
        created_at=refund.created_at,
    )


@router.post("", response_model=RefundResponse, status_code=201)
def create_refund(
    payload: RefundCreateRequest, _admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)
) -> RefundResponse:
    refund = RefundService(conn).create_refund(payload.payment_id, payload.amount, payload.reason)
    return _to_response(refund)


@router.get("/{refund_id}", response_model=RefundResponse)
def get_refund(
    refund_id: int, user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> RefundResponse:
    refund = RefundService(conn).get_by_id(refund_id)
    if not user.is_admin:
        payment = PaymentService(conn).get_by_id(refund.payment_id)
        order = OrderService(conn).get_order_or_404(payment.order_id)
        if order.user_id != user.id:
            raise ForbiddenError("Cannot view a refund for an order that does not belong to you")
    return _to_response(refund)
