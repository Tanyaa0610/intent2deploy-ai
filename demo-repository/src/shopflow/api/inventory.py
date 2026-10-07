"""Inventory read + adjust endpoints.

BUG (task_015.json): `adjust_inventory` is authorized with
`get_current_user` (any authenticated user) instead of `require_admin`,
unlike every other write operation in this module/`products.py`.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user
from src.shopflow.models.user import User
from src.shopflow.schemas.product import InventoryAdjustRequest, ProductResponse, product_to_response
from src.shopflow.services.audit_service import AuditService
from src.shopflow.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/{product_id}", response_model=ProductResponse)
def get_inventory(product_id: int, conn: sqlite3.Connection = Depends(get_connection)) -> ProductResponse:
    return product_to_response(InventoryService(conn).get_product_or_404(product_id))


@router.post("/{product_id}/adjust", response_model=ProductResponse)
def adjust_inventory(
    product_id: int,
    payload: InventoryAdjustRequest,
    user: User = Depends(get_current_user),  # see module docstring — should be require_admin
    conn: sqlite3.Connection = Depends(get_connection),
) -> ProductResponse:
    service = InventoryService(conn)
    if payload.delta >= 0:
        product = service.increase_stock(product_id, payload.delta)
    else:
        product = service.decrease_stock(product_id, -payload.delta)
    AuditService(conn).record(user.id, "inventory.adjust", {"product_id": product_id, "delta": payload.delta})
    return product_to_response(product)
