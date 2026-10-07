from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.shopflow.api.deps import get_connection, get_current_user
from src.shopflow.models.cart import Cart
from src.shopflow.models.user import User
from src.shopflow.schemas.cart import CartItemAddRequest, CartItemResponse, CartItemUpdateRequest, CartResponse
from src.shopflow.services.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["cart"])


def _to_response(cart: Cart, subtotal: float) -> CartResponse:
    return CartResponse(
        id=cart.id,
        user_id=cart.user_id,
        items=[CartItemResponse(product_id=i.product_id, quantity=i.quantity) for i in cart.items],
        subtotal=subtotal,
    )


@router.get("", response_model=CartResponse)
def get_cart(user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)) -> CartResponse:
    service = CartService(conn)
    cart = service.get_or_create_cart(user.id)
    return _to_response(cart, service.calculate_subtotal(user.id))


@router.post("/items", response_model=CartResponse)
def add_item(
    payload: CartItemAddRequest,
    user: User = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_connection),
) -> CartResponse:
    service = CartService(conn)
    cart = service.add_item(user.id, payload.product_id, payload.quantity)
    return _to_response(cart, service.calculate_subtotal(user.id))


@router.patch("/items/{product_id}", response_model=CartResponse)
def update_item(
    product_id: int,
    payload: CartItemUpdateRequest,
    user: User = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_connection),
) -> CartResponse:
    service = CartService(conn)
    cart = service.update_item_quantity(user.id, product_id, payload.quantity)
    return _to_response(cart, service.calculate_subtotal(user.id))


@router.delete("/items/{product_id}", response_model=CartResponse)
def remove_item(
    product_id: int, user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> CartResponse:
    service = CartService(conn)
    cart = service.remove_item(user.id, product_id)
    return _to_response(cart, service.calculate_subtotal(user.id))


@router.delete("", response_model=CartResponse)
def clear_cart(
    user: User = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_connection)
) -> CartResponse:
    service = CartService(conn)
    cart = service.clear_cart(user.id)
    return _to_response(cart, 0.0)
