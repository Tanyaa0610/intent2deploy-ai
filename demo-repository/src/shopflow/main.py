"""FastAPI application entry point: wires routers, exception handling,
and startup (database + optional demo-data seeding)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.shopflow.api import auth, cart, inventory, orders, payments, products, refunds, users
from src.shopflow.config import get_settings
from src.shopflow.database import Database
from src.shopflow.exceptions import ShopFlowError
from src.shopflow.seed import seed_demo_data

app = FastAPI(title="ShopFlow API", version="1.0.0")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(refunds.router)


@app.exception_handler(ShopFlowError)
def handle_shopflow_error(_request: Request, exc: ShopFlowError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
def handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    # Never leak internal stack traces / exception text through the API.
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.on_event("startup")
def on_startup() -> None:
    if not hasattr(app.state, "db"):
        settings = get_settings()
        app.state.db = Database(settings.db_path)
        if settings.seed_on_startup:
            seed_demo_data(app.state.db.conn)


@app.on_event("shutdown")
def on_shutdown() -> None:
    if hasattr(app.state, "db"):
        app.state.db.close()
        del app.state.db


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "shopflow"}
