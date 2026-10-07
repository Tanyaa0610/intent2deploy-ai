from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, require_admin
from src.shopflow.models.product import Product
from src.shopflow.schemas.product import ProductCreateRequest, ProductResponse, ProductUpdateRequest
from src.shopflow.services.audit_service import AuditService
from src.shopflow.services.product_service import ProductService
from src.shopflow.models.user import User

router = APIRouter(prefix="/products", tags=["products"])


def _to_response(product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        price=product.price,
        category=product.category,
        inventory_quantity=product.inventory_quantity,
        is_active=product.is_active,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreateRequest, admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)
) -> ProductResponse:
    product = ProductService(conn).create_product(
        payload.sku, payload.name, payload.description, payload.price, payload.category, payload.inventory_quantity
    )
    AuditService(conn).record(admin.id, "product.create", {"sku": product.sku, "product_id": product.id})
    return _to_response(product)


@router.get("", response_model=list[ProductResponse])
def list_products(
    category: str | None = None,
    search: str | None = None,
    include_inactive: bool = False,
    conn: sqlite3.Connection = Depends(get_connection),
) -> list[ProductResponse]:
    products = ProductService(conn).list_products(category=category, active_only=not include_inactive, search=search)
    return [_to_response(p) for p in products]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, conn: sqlite3.Connection = Depends(get_connection)) -> ProductResponse:
    return _to_response(ProductService(conn).get_by_id(product_id))


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    admin: User = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_connection),
) -> ProductResponse:
    product = ProductService(conn).update_product(
        product_id, name=payload.name, description=payload.description, price=payload.price, category=payload.category
    )
    AuditService(conn).record(admin.id, "product.update", {"product_id": product_id})
    return _to_response(product)


@router.post("/{product_id}/deactivate", response_model=ProductResponse)
def deactivate_product(
    product_id: int, admin: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_connection)
) -> ProductResponse:
    product = ProductService(conn).deactivate_product(product_id)
    AuditService(conn).record(admin.id, "product.deactivate", {"product_id": product_id})
    return _to_response(product)
