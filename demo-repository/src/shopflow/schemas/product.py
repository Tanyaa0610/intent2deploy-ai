from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from src.shopflow.models.product import Product


class ProductCreateRequest(BaseModel):
    sku: str
    name: str
    description: str = ""
    price: float
    category: str = ""
    inventory_quantity: int = 0


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    category: str | None = None


class ProductResponse(BaseModel):
    id: int
    sku: str
    name: str
    description: str
    price: float
    category: str
    inventory_quantity: int
    is_active: bool
    created_at: str
    updated_at: str


class InventoryAdjustRequest(BaseModel):
    delta: int  # positive to increase, negative to decrease


def product_to_response(product: "Product") -> ProductResponse:
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
