"""Built-in "food delivery app" project template (mock mode).

A complete Zomato/Swiggy-style ordering app: restaurant discovery with
search and filters, menus, a single-restaurant cart priced on the server
(fees, GST, coupons), checkout with address validation, live order
tracking and order history. FastAPI backend + vanilla HTML/CSS/JS
frontend, with tests and CI. See templates.py for how templates are used.
"""
from __future__ import annotations

FOOD_KEYWORDS = r"\b(food[\s-]?delivery|zomato|swiggy|restaurants?|order(ing)? food|food[\s-]?(ordering|app|order))\b"


def design(title: str) -> dict:
    return {
        "project_name": "food-delivery-app",
        "summary": f"{title}: a Zomato/Swiggy-style food ordering app — browse and search restaurants, view menus, "
        "build a cart priced on the server (delivery fee, platform fee, GST, coupons), check out with an address "
        "and payment choice, and track the order live.",
        "requirements": [
            "Home page lists restaurants with rating, cuisines, delivery time, cost for two and offers.",
            "Search restaurants and dishes; filter by cuisine, pure veg and rating; sort by rating, time or cost.",
            "Restaurant page shows the menu by category with veg/non-veg markers and bestsellers.",
            "Cart holds items from one restaurant, with quantity controls that persist across page reloads.",
            "Bill is computed on the server: item total, delivery fee (free above ₹299), platform fee, 5% GST, coupons.",
            "Checkout validates name, 10-digit mobile number, address and 6-digit PIN code, and a payment method.",
            "After ordering, a tracking page shows Placed → Preparing → Out for delivery → Delivered with an ETA.",
            "Order history lists previous orders.",
        ],
        "non_functional": [
            "Prices are never trusted from the browser: totals are recalculated on the server for every quote and order.",
            "Responsive layout that works on mobile widths.",
            "No external services, images or API keys are needed to run or test the app.",
        ],
        "acceptance_criteria": [
            "GET /api/restaurants supports q, cuisine, veg, min_rating and sort parameters.",
            "POST /api/cart/quote rejects items from another restaurant and unknown coupons are reported, not applied.",
            "POST /api/orders returns 201 with an order id; invalid phone numbers or PIN codes return 422.",
            "GET /api/orders/{id} reports the status advancing over time.",
            "The automated test suite passes.",
        ],
        "stack": "Python 3 · FastAPI · vanilla HTML/CSS/JavaScript (hash-routed single page) · pytest",
        "components": [
            {"name": "Storefront UI", "responsibility": "Home, restaurant, cart/checkout, tracking and order-history views.",
             "files": ["static/index.html", "static/styles.css", "static/app.js"]},
            {"name": "API", "responsibility": "Restaurant discovery, cart quotes, orders and tracking endpoints.",
             "files": ["app/__init__.py", "app/main.py", "app/models.py"]},
            {"name": "Catalogue", "responsibility": "Restaurants and menus.", "files": ["app/data.py"]},
            {"name": "Ordering", "responsibility": "Search, pricing, coupons, orders and status progression.",
             "files": ["app/store.py"]},
            {"name": "Tests", "responsibility": "Pricing/ordering unit tests and API tests.",
             "files": ["tests/test_store.py", "tests/test_api.py"]},
            {"name": "Project config", "responsibility": "Dependencies, test and lint configuration, docs.",
             "files": ["requirements.txt", "pytest.ini", "pyproject.toml", "README.md"]},
            {"name": "CI pipeline", "responsibility": "GitHub Actions: lint, security scan and tests.",
             "files": [".github/workflows/ci.yml"]},
        ],
        "files": [
            {"path": "app/__init__.py", "purpose": "Package marker."},
            {"path": "app/data.py", "purpose": "Restaurants and menus."},
            {"path": "app/models.py", "purpose": "Request models with validation (cart lines, address, order)."},
            {"path": "app/store.py", "purpose": "Search, pricing, coupons, orders, tracking."},
            {"path": "app/main.py", "purpose": "FastAPI routes and static frontend."},
            {"path": "static/index.html", "purpose": "Single-page app shell."},
            {"path": "static/styles.css", "purpose": "Styling."},
            {"path": "static/app.js", "purpose": "Views, cart, checkout and live tracking."},
            {"path": "tests/test_store.py", "purpose": "Pricing, coupon, search and status tests."},
            {"path": "tests/test_api.py", "purpose": "Endpoint tests."},
            {"path": "requirements.txt", "purpose": "Runtime and test dependencies."},
            {"path": "pytest.ini", "purpose": "Test discovery configuration."},
            {"path": "pyproject.toml", "purpose": "Ruff lint configuration."},
            {"path": "README.md", "purpose": "How to run and test the app."},
            {"path": ".github/workflows/ci.yml", "purpose": "GitHub Actions CI."},
        ],
        "dependencies": ["fastapi", "uvicorn", "httpx (tests)", "pytest (tests)"],
        "test_command": "python3 -m pytest -q",
        "run_command": "uvicorn app.main:app --reload --port __PORT__",
        "risks": [
            "Orders are kept in memory and are lost on restart; a database is needed before production use.",
            "Payment is only recorded as a choice (COD/UPI/card); no real payment gateway is integrated.",
        ],
        "template": "food_delivery_app",
    }


DATA_PY = r'''"""Restaurant catalogue (prices in rupees)."""
from __future__ import annotations


def _i(item_id: str, name: str, price: int, veg: bool, description: str, bestseller: bool = False) -> dict:
    return {
        "id": item_id, "name": name, "price": price, "veg": veg, "description": description, "bestseller": bestseller,
    }


RESTAURANTS: list[dict] = [
    {
        "id": "spice-route", "name": "Spice Route", "cuisines": ["North Indian", "Mughlai"], "rating": 4.4,
        "rating_count": 2310, "delivery_minutes": 30, "cost_for_two": 500, "veg_only": False,
        "offer": "50% OFF up to ₹100", "emoji": "🍛", "area": "Connaught Place",
        "menu": [
            {"name": "Recommended", "items": [
                _i("sr-butter-chicken", "Butter Chicken", 320, False, "Tandoori chicken in tomato-butter gravy.", True),
                _i("sr-paneer-tikka", "Paneer Tikka Masala", 280, True, "Charred paneer cubes in spiced masala.", True),
            ]},
            {"name": "Breads", "items": [
                _i("sr-butter-naan", "Butter Naan", 55, True, "Soft tandoor-baked naan brushed with butter."),
                _i("sr-garlic-naan", "Garlic Naan", 65, True, "Naan topped with garlic and coriander."),
            ]},
            {"name": "Rice", "items": [
                _i("sr-jeera-rice", "Jeera Rice", 160, True, "Basmati rice tempered with cumin."),
                _i("sr-dal-makhani", "Dal Makhani", 240, True, "Slow-cooked black lentils with cream."),
            ]},
        ],
    },
    {
        "id": "biryani-house", "name": "Biryani House", "cuisines": ["Biryani", "Hyderabadi"], "rating": 4.6,
        "rating_count": 5120, "delivery_minutes": 35, "cost_for_two": 450, "veg_only": False,
        "offer": "Free delivery", "emoji": "🍚", "area": "Karol Bagh",
        "menu": [
            {"name": "Biryani", "items": [
                _i("bh-chicken-dum", "Chicken Dum Biryani", 299, False, "Hyderabadi dum biryani with raita.", True),
                _i("bh-mutton", "Mutton Biryani", 389, False, "Slow-cooked mutton with saffron rice.", True),
                _i("bh-veg", "Veg Biryani", 219, True, "Seasonal vegetables and fragrant basmati."),
            ]},
            {"name": "Sides", "items": [
                _i("bh-salan", "Mirchi ka Salan", 99, True, "Chillies in a tangy peanut-sesame gravy."),
                _i("bh-kebab", "Chicken 65", 229, False, "Crispy spiced chicken bites."),
                _i("bh-double-ka-meetha", "Double ka Meetha", 119, True, "Bread pudding with saffron and nuts."),
            ]},
        ],
    },
    {
        "id": "pizza-piazza", "name": "Pizza Piazza", "cuisines": ["Pizza", "Italian"], "rating": 4.2,
        "rating_count": 1840, "delivery_minutes": 25, "cost_for_two": 600, "veg_only": False,
        "offer": "Buy 1 Get 1 on Tuesdays", "emoji": "🍕", "area": "Hauz Khas",
        "menu": [
            {"name": "Pizzas", "items": [
                _i("pp-margherita", "Margherita", 249, True, "San Marzano tomato, mozzarella, basil.", True),
                _i("pp-farmhouse", "Farmhouse", 329, True, "Capsicum, onion, mushroom, sweet corn."),
                _i("pp-pepperoni", "Pepperoni", 399, False, "Spicy pepperoni and extra cheese.", True),
            ]},
            {"name": "Pasta & Sides", "items": [
                _i("pp-arrabbiata", "Penne Arrabbiata", 279, True, "Penne in a spicy tomato sauce."),
                _i("pp-garlic-bread", "Cheesy Garlic Bread", 159, True, "Garlic butter, mozzarella, herbs."),
                _i("pp-tiramisu", "Tiramisu", 199, True, "Coffee-soaked sponge with mascarpone."),
            ]},
        ],
    },
    {
        "id": "burger-barn", "name": "Burger Barn", "cuisines": ["Burgers", "Fast Food"], "rating": 4.1,
        "rating_count": 3290, "delivery_minutes": 20, "cost_for_two": 400, "veg_only": False,
        "offer": "₹75 OFF above ₹299", "emoji": "🍔", "area": "Rajouri Garden",
        "menu": [
            {"name": "Burgers", "items": [
                _i("bb-classic-chicken", "Classic Chicken Burger", 199, False, "Crispy chicken, lettuce, mayo.", True),
                _i("bb-aloo-tikki", "Aloo Tikki Burger", 129, True, "Spiced potato patty with mint chutney.", True),
                _i("bb-double-cheese", "Double Cheese Smash", 259, False, "Two smashed patties, cheddar, pickles."),
            ]},
            {"name": "Sides & Drinks", "items": [
                _i("bb-fries", "Peri Peri Fries", 119, True, "Crispy fries with peri peri seasoning."),
                _i("bb-shake", "Oreo Shake", 149, True, "Thick shake blended with cookies."),
            ]},
        ],
    },
    {
        "id": "dragon-wok", "name": "Dragon Wok", "cuisines": ["Chinese", "Asian"], "rating": 4.0,
        "rating_count": 1220, "delivery_minutes": 30, "cost_for_two": 450, "veg_only": False,
        "offer": "20% OFF", "emoji": "🥡", "area": "Lajpat Nagar",
        "menu": [
            {"name": "Mains", "items": [
                _i("dw-hakka", "Veg Hakka Noodles", 189, True, "Wok-tossed noodles with vegetables.", True),
                _i("dw-chilli-chicken", "Chilli Chicken", 259, False, "Indo-Chinese chilli chicken, semi-dry.", True),
                _i("dw-fried-rice", "Egg Fried Rice", 199, False, "Fried rice with egg and spring onion."),
            ]},
            {"name": "Starters", "items": [
                _i("dw-momos", "Veg Steamed Momos", 129, True, "Eight momos with spicy red chutney."),
                _i("dw-manchurian", "Gobi Manchurian", 179, True, "Crispy cauliflower in Manchurian sauce."),
            ]},
        ],
    },
    {
        "id": "dosa-plaza", "name": "Dosa Plaza", "cuisines": ["South Indian"], "rating": 4.5,
        "rating_count": 4010, "delivery_minutes": 25, "cost_for_two": 300, "veg_only": True,
        "offer": "Free filter coffee above ₹249", "emoji": "🥞", "area": "Malviya Nagar",
        "menu": [
            {"name": "Dosas", "items": [
                _i("dp-masala", "Masala Dosa", 129, True, "Crisp dosa with potato masala, sambar, chutney.", True),
                _i("dp-mysore", "Mysore Masala Dosa", 149, True, "Spicy red chutney spread inside."),
                _i("dp-rava", "Onion Rava Dosa", 159, True, "Lacy semolina dosa with onions."),
            ]},
            {"name": "Tiffin", "items": [
                _i("dp-idli", "Idli Sambar (2 pcs)", 89, True, "Steamed rice cakes with sambar.", True),
                _i("dp-vada", "Medu Vada (2 pcs)", 99, True, "Crispy lentil doughnuts."),
                _i("dp-coffee", "Filter Coffee", 49, True, "Strong South Indian filter coffee."),
            ]},
        ],
    },
    {
        "id": "green-bowl", "name": "Green Bowl", "cuisines": ["Healthy", "Salads"], "rating": 4.3,
        "rating_count": 860, "delivery_minutes": 20, "cost_for_two": 550, "veg_only": True,
        "offer": "10% OFF on first order", "emoji": "🥗", "area": "Defence Colony",
        "menu": [
            {"name": "Bowls", "items": [
                _i("gb-quinoa", "Quinoa Power Bowl", 299, True, "Quinoa, chickpeas, avocado, tahini.", True),
                _i("gb-paneer", "Grilled Paneer Bowl", 289, True, "Herb paneer, brown rice, greens."),
            ]},
            {"name": "Salads & Juices", "items": [
                _i("gb-greek", "Greek Salad", 239, True, "Feta, olives, cucumber, tomato."),
                _i("gb-detox", "Green Detox Juice", 149, True, "Spinach, apple, cucumber, lemon."),
            ]},
        ],
    },
    {
        "id": "sweet-tooth", "name": "Sweet Tooth", "cuisines": ["Desserts", "Bakery"], "rating": 4.7,
        "rating_count": 2780, "delivery_minutes": 15, "cost_for_two": 350, "veg_only": True,
        "offer": "Buy 2 pastries get 1 free", "emoji": "🍰", "area": "Khan Market",
        "menu": [
            {"name": "Cakes & Pastries", "items": [
                _i("st-truffle", "Chocolate Truffle Pastry", 129, True, "Dark chocolate ganache layers.", True),
                _i("st-red-velvet", "Red Velvet Slice", 139, True, "Cream cheese frosting."),
                _i("st-cheesecake", "Blueberry Cheesecake", 179, True, "Baked cheesecake, blueberry compote."),
            ]},
            {"name": "Indian Sweets", "items": [
                _i("st-gulab", "Gulab Jamun (2 pcs)", 79, True, "Warm, syrup-soaked dumplings.", True),
                _i("st-rasmalai", "Rasmalai (2 pcs)", 109, True, "Cottage cheese discs in saffron milk."),
            ]},
        ],
    },
]
'''

MODELS_PY = r'''"""Request models. All prices come from the server catalogue, never from these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CartLine(BaseModel):
    item_id: str = Field(min_length=1, max_length=60)
    quantity: int = Field(ge=1, le=20)


class QuoteRequest(BaseModel):
    restaurant_id: str = Field(min_length=1, max_length=60)
    items: list[CartLine] = Field(min_length=1, max_length=50)
    coupon: str = Field(default="", max_length=20)


class Address(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(pattern=r"^[6-9]\d{9}$", description="10-digit Indian mobile number")
    line1: str = Field(min_length=5, max_length=200)
    city: str = Field(min_length=2, max_length=60)
    pincode: str = Field(pattern=r"^\d{6}$")


class OrderRequest(QuoteRequest):
    address: Address
    payment: Literal["cod", "upi", "card"]
    instructions: str = Field(default="", max_length=200)
'''

STORE_PY = r'''"""Search, server-side pricing, coupons, orders and live status."""
from __future__ import annotations

import time
from collections.abc import Callable

from app.data import RESTAURANTS
from app.models import CartLine, OrderRequest

DELIVERY_FEE = 40
FREE_DELIVERY_ABOVE = 299
PLATFORM_FEE = 5
GST_RATE = 0.05

COUPONS = {
    "WELCOME50": {"label": "50% off up to ₹100", "percent": 50, "max_discount": 100, "min_order": 149},
    "FREEDEL": {"label": "Free delivery", "free_delivery": True, "min_order": 0},
    "FEAST75": {"label": "₹75 off above ₹399", "flat": 75, "min_order": 399},
}

# (status, seconds after placing) — compressed timings so a demo shows the full journey.
STATUS_FLOW = [("placed", 0), ("preparing", 20), ("out_for_delivery", 60), ("delivered", 120)]
STATUS_LABELS = {
    "placed": "Order placed",
    "preparing": "Restaurant is preparing your food",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
}


class PricingError(ValueError):
    pass


def find_restaurant(restaurant_id: str) -> dict | None:
    return next((r for r in RESTAURANTS if r["id"] == restaurant_id), None)


def summary(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "menu"}


def cuisines() -> list[dict]:
    counts: dict[str, int] = {}
    for r in RESTAURANTS:
        for c in r["cuisines"]:
            counts[c] = counts.get(c, 0) + 1
    return [{"name": c, "restaurants": n} for c, n in sorted(counts.items())]


def search(
    q: str = "", cuisine: str = "", veg: bool = False, min_rating: float = 0.0, sort: str = "relevance"
) -> list[dict]:
    term = q.strip().lower()
    results = []
    for r in RESTAURANTS:
        if cuisine and cuisine not in r["cuisines"]:
            continue
        if veg and not r["veg_only"]:
            continue
        if r["rating"] < min_rating:
            continue
        dishes = [i["name"] for cat in r["menu"] for i in cat["items"]]
        if term:
            haystack = " ".join([r["name"], *r["cuisines"]]).lower()
            matched = [d for d in dishes if term in d.lower()]
            if term not in haystack and not matched:
                continue
            results.append({**summary(r), "matched_dishes": matched[:3]})
        else:
            results.append({**summary(r), "matched_dishes": []})
    keys = {
        "rating": lambda r: -r["rating"],
        "delivery_time": lambda r: r["delivery_minutes"],
        "cost_low": lambda r: r["cost_for_two"],
        "cost_high": lambda r: -r["cost_for_two"],
    }
    if sort in keys:
        results.sort(key=keys[sort])
    return results


def quote(restaurant_id: str, lines: list[CartLine], coupon: str = "") -> dict:
    restaurant = find_restaurant(restaurant_id)
    if restaurant is None:
        raise PricingError("Restaurant not found.")
    menu = {i["id"]: i for cat in restaurant["menu"] for i in cat["items"]}
    priced = []
    for line in lines:
        item = menu.get(line.item_id)
        if item is None:
            raise PricingError(f"'{line.item_id}' is not on {restaurant['name']}'s menu.")
        priced.append({"item_id": item["id"], "name": item["name"], "veg": item["veg"], "price": item["price"],
                       "quantity": line.quantity, "line_total": item["price"] * line.quantity})
    item_total = sum(p["line_total"] for p in priced)
    delivery_fee = 0 if item_total >= FREE_DELIVERY_ABOVE else DELIVERY_FEE
    gst = round(item_total * GST_RATE)
    discount = 0
    code = coupon.strip().upper()
    coupon_message = ""
    applied = ""
    if code:
        rule = COUPONS.get(code)
        if rule is None:
            coupon_message = f"{code} is not a valid coupon."
        elif item_total < rule["min_order"]:
            coupon_message = f"Add ₹{rule['min_order'] - item_total} more to use {code}."
        else:
            applied = code
            if rule.get("free_delivery"):
                discount = delivery_fee
            elif "percent" in rule:
                discount = min(item_total * rule["percent"] // 100, rule["max_discount"])
            else:
                discount = rule["flat"]
            coupon_message = f"{code} applied — you save ₹{discount}."
    total = item_total + delivery_fee + PLATFORM_FEE + gst - discount
    return {
        "restaurant_id": restaurant["id"], "restaurant_name": restaurant["name"], "lines": priced,
        "item_total": item_total, "delivery_fee": delivery_fee, "platform_fee": PLATFORM_FEE, "gst": gst,
        "discount": discount, "coupon": applied, "coupon_message": coupon_message, "total": total,
        "free_delivery_above": FREE_DELIVERY_ABOVE,
    }


class OrderStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._orders: dict[str, dict] = {}
        self._next = 1

    def place(self, req: OrderRequest) -> dict:
        bill = quote(req.restaurant_id, req.items, req.coupon)
        restaurant = find_restaurant(req.restaurant_id)
        order_id = f"FD{self._next:05d}"
        self._next += 1
        order = {
            "id": order_id,
            "placed_at": self._clock(),
            "eta_minutes": restaurant["delivery_minutes"],
            "address": req.address.model_dump(),
            "payment": req.payment,
            "instructions": req.instructions,
            "bill": bill,
        }
        self._orders[order_id] = order
        return self.view(order)

    def get(self, order_id: str) -> dict | None:
        order = self._orders.get(order_id)
        return self.view(order) if order else None

    def list(self) -> list[dict]:
        return [self.view(o) for o in sorted(self._orders.values(), key=lambda o: -o["placed_at"])]

    def view(self, order: dict) -> dict:
        elapsed = self._clock() - order["placed_at"]
        reached = [s for s, at in STATUS_FLOW if elapsed >= at]
        status = reached[-1]
        timeline = [{"status": s, "label": STATUS_LABELS[s], "done": s in reached, "current": s == status}
                    for s, _ in STATUS_FLOW]
        remaining = max(0, round(order["eta_minutes"] * (1 - min(elapsed / STATUS_FLOW[-1][1], 1))))
        return {**order, "status": status, "status_label": STATUS_LABELS[status], "timeline": timeline,
                "minutes_remaining": remaining}
'''

MAIN_PY = r'''"""Food delivery app: API + single-page frontend."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.models import OrderRequest, QuoteRequest
from app.store import OrderStore, PricingError, cuisines, find_restaurant, quote, search

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="__TITLE__")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
orders = OrderStore()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/cuisines")
def list_cuisines() -> list[dict]:
    return cuisines()


@app.get("/api/restaurants")
def list_restaurants(
    q: str = Query(default="", max_length=60),
    cuisine: str = Query(default="", max_length=40),
    veg: bool = False,
    min_rating: float = Query(default=0.0, ge=0, le=5),
    sort: Literal["relevance", "rating", "delivery_time", "cost_low", "cost_high"] = "relevance",
) -> list[dict]:
    return search(q, cuisine, veg, min_rating, sort)


@app.get("/api/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: str) -> dict:
    restaurant = find_restaurant(restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


@app.post("/api/cart/quote")
def cart_quote(body: QuoteRequest) -> dict:
    try:
        return quote(body.restaurant_id, body.items, body.coupon)
    except PricingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/orders", status_code=201)
def place_order(body: OrderRequest) -> dict:
    try:
        return orders.place(body)
    except PricingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/orders")
def list_orders() -> list[dict]:
    return orders.list()


@app.get("/api/orders/{order_id}")
def get_order(order_id: str) -> dict:
    order = orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
'''

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <header class="topbar">
    <a href="#/" class="brand"><span class="brand-mark">🛵</span> __TITLE__</a>
    <div class="location" title="Delivery location">📍 <span id="location">New Delhi</span></div>
    <nav class="nav">
      <a href="#/orders">My orders</a>
      <a href="#/cart" class="cart-link">🛒 Cart <span id="cart-count" class="badge" hidden>0</span></a>
    </nav>
  </header>
  <main id="view" class="container" aria-live="polite"></main>
  <div id="toast" class="toast" role="status" hidden></div>
  <script src="/static/app.js"></script>
</body>
</html>
'''

STYLES_CSS = r''':root {
  --brand: #e23744;
  --brand-dark: #b82431;
  --bg: #f8f8f8;
  --card: #ffffff;
  --text: #1c1c1c;
  --muted: #696969;
  --line: #e8e8e8;
  --green: #267e3e;
  --veg: #0f8a43;
  --nonveg: #c0392b;
  --radius: 14px;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
a { color: inherit; text-decoration: none; }
button { font: inherit; cursor: pointer; }
.container { max-width: 1100px; margin: 0 auto; padding: 18px 16px 80px; }

.topbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 18px; padding: 12px 20px; background: var(--card); box-shadow: 0 1px 6px rgba(0,0,0,.06); }
.brand { font-weight: 800; font-size: 20px; color: var(--brand); display: flex; align-items: center; gap: 6px; }
.location { color: var(--muted); font-size: 14px; }
.nav { margin-left: auto; display: flex; gap: 18px; font-weight: 600; font-size: 14px; }
.badge { display: inline-block; min-width: 20px; padding: 1px 6px; border-radius: 10px; background: var(--brand); color: #fff; font-size: 12px; text-align: center; }

.hero { border-radius: var(--radius); padding: 34px 28px; color: #fff; background: linear-gradient(120deg, var(--brand), #ff7e5f); margin-bottom: 18px; }
.hero h1 { margin: 0 0 6px; font-size: 30px; }
.hero p { margin: 0 0 16px; opacity: .95; }
.search { display: flex; gap: 8px; max-width: 560px; }
.search input { flex: 1; padding: 13px 14px; border-radius: 10px; border: none; font-size: 15px; }

.chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0; }
.chip { border: 1px solid var(--line); background: var(--card); padding: 7px 13px; border-radius: 20px; font-size: 13.5px; }
.chip.active { background: var(--text); color: #fff; border-color: var(--text); }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.toolbar select { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--card); }
.count { color: var(--muted); font-size: 14px; margin-left: auto; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 18px; }
.card { background: var(--card); border-radius: var(--radius); overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.06); transition: transform .12s, box-shadow .12s; }
.card:hover { transform: translateY(-3px); box-shadow: 0 8px 18px rgba(0,0,0,.1); }
.thumb { height: 140px; display: grid; place-items: center; font-size: 64px; position: relative; }
.offer { position: absolute; left: 0; bottom: 10px; background: #2563eb; color: #fff; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 0 6px 6px 0; }
.card-body { padding: 12px 14px 14px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.card h3 { margin: 0; font-size: 17px; }
.rating { background: var(--green); color: #fff; font-weight: 700; font-size: 12.5px; padding: 2px 7px; border-radius: 6px; white-space: nowrap; }
.muted { color: var(--muted); font-size: 13.5px; }
.matches { color: var(--brand); font-size: 12.5px; margin-top: 4px; }

.rest-head { background: var(--card); border-radius: var(--radius); padding: 20px; margin-bottom: 18px; display: flex; gap: 18px; align-items: center; }
.rest-head .emoji { font-size: 56px; }
.rest-head h1 { margin: 0 0 4px; }
.facts { display: flex; gap: 18px; margin-top: 8px; font-size: 14px; flex-wrap: wrap; }
.menu-layout { display: grid; grid-template-columns: 200px 1fr; gap: 20px; }
.menu-nav { position: sticky; top: 80px; align-self: start; display: flex; flex-direction: column; gap: 4px; }
.menu-nav a { padding: 8px 10px; border-radius: 8px; font-size: 14px; }
.menu-nav a:hover { background: var(--card); }
.menu-section h2 { font-size: 19px; margin: 6px 0 10px; }
.dish { background: var(--card); border-radius: 12px; padding: 14px; display: flex; justify-content: space-between; gap: 14px; margin-bottom: 10px; }
.dish h4 { margin: 4px 0; font-size: 16px; }
.dish p { margin: 4px 0 0; }
.marker { display: inline-grid; place-items: center; width: 15px; height: 15px; border: 1.5px solid; border-radius: 3px; vertical-align: -2px; margin-right: 6px; }
.marker::after { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.marker.veg { color: var(--veg); }
.marker.nonveg { color: var(--nonveg); }
.best { color: #e67e22; font-size: 12px; font-weight: 700; }
.qty { display: inline-flex; align-items: center; border: 1px solid var(--brand); border-radius: 8px; overflow: hidden; height: 36px; }
.qty button { border: none; background: var(--card); color: var(--brand); width: 34px; height: 100%; font-size: 18px; font-weight: 700; }
.qty span { min-width: 26px; text-align: center; font-weight: 700; color: var(--brand); }
.add { border: 1px solid var(--brand); color: var(--brand); background: #fff5f6; padding: 8px 22px; border-radius: 8px; font-weight: 800; }

.btn { border: none; background: var(--brand); color: #fff; padding: 12px 18px; border-radius: 10px; font-weight: 700; }
.btn:hover { background: var(--brand-dark); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--brand); border: 1px solid var(--brand); }

.checkout { display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; }
.panel { background: var(--card); border-radius: var(--radius); padding: 18px; margin-bottom: 18px; }
.panel h2 { margin: 0 0 12px; font-size: 18px; }
.line { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px dashed var(--line); }
.bill .line { border: none; padding: 4px 0; font-size: 14px; }
.bill .total { font-weight: 800; font-size: 16px; border-top: 1px solid var(--line); padding-top: 10px; margin-top: 6px; }
.saving { color: var(--green); }
label { display: block; font-size: 13px; font-weight: 600; margin: 10px 0 4px; }
input, textarea { width: 100%; padding: 10px 12px; border: 1px solid #d4d4d4; border-radius: 8px; font: inherit; }
input[aria-invalid="true"] { border-color: var(--nonveg); }
.error { color: var(--nonveg); font-size: 12.5px; min-height: 16px; margin: 3px 0 0; }
.pay { display: flex; gap: 8px; flex-wrap: wrap; }
.pay label { display: flex; align-items: center; gap: 6px; border: 1px solid var(--line); padding: 9px 12px; border-radius: 8px; margin: 0; font-weight: 500; }
.pay input { width: auto; }
.coupon { display: flex; gap: 8px; }

.track { max-width: 640px; margin: 0 auto; }
.status-hero { text-align: center; padding: 26px 18px; }
.status-hero .big { font-size: 54px; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { display: flex; gap: 12px; align-items: center; padding: 10px 0; color: var(--muted); }
.timeline .dot { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--line); background: var(--card); flex: none; }
.timeline li.done { color: var(--text); font-weight: 600; }
.timeline li.done .dot { background: var(--green); border-color: var(--green); }
.timeline li.current .dot { box-shadow: 0 0 0 5px rgba(38,126,62,.18); }
.empty { text-align: center; padding: 60px 20px; color: var(--muted); }
.empty .big { font-size: 56px; }
.toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); background: var(--text); color: #fff; padding: 11px 18px; border-radius: 10px; font-size: 14px; z-index: 20; }
.cart-bar { position: fixed; bottom: 0; left: 0; right: 0; background: var(--green); color: #fff; padding: 13px 20px; display: flex; justify-content: space-between; font-weight: 700; z-index: 9; }

@media (max-width: 760px) {
  .menu-layout, .checkout { grid-template-columns: 1fr; }
  .menu-nav { display: none; }
  .location { display: none; }
  .hero h1 { font-size: 24px; }
}
'''

APP_JS = r'''(() => {
  "use strict";
  const view = document.getElementById("view");
  const CART_KEY = "fd-cart-v1";
  const rupee = (n) => `₹${Number(n).toLocaleString("en-IN")}`;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const COLORS = ["#ffe3e0", "#e0f2fe", "#fef3c7", "#dcfce7", "#ede9fe", "#fce7f3", "#e0e7ff", "#ffedd5"];
  let pollTimer = null;

  async function api(path, options = {}) {
    const resp = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(", ") : body.detail;
      throw new Error(detail || `Request failed (${resp.status})`);
    }
    return body;
  }

  function toast(text) {
    const el = document.getElementById("toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (el.hidden = true), 2600);
  }

  // ---- Cart (one restaurant at a time, persisted in localStorage) --------
  function loadCart() {
    try { return JSON.parse(localStorage.getItem(CART_KEY)) || { restaurantId: null, restaurantName: "", items: {} }; }
    catch { return { restaurantId: null, restaurantName: "", items: {} }; }
  }
  function saveCart(cart) {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    renderCartCount();
  }
  function cartCount(cart = loadCart()) {
    return Object.values(cart.items).reduce((a, b) => a + b, 0);
  }
  function renderCartCount() {
    const n = cartCount();
    const badge = document.getElementById("cart-count");
    badge.textContent = n;
    badge.hidden = n === 0;
  }
  function setQty(restaurant, itemId, qty) {
    let cart = loadCart();
    if (cart.restaurantId && cart.restaurantId !== restaurant.id && cartCount(cart) > 0) {
      if (!confirm(`Your cart has items from ${cart.restaurantName}. Start a new cart from ${restaurant.name}?`)) return false;
      cart = { restaurantId: null, restaurantName: "", items: {} };
    }
    cart.restaurantId = restaurant.id;
    cart.restaurantName = restaurant.name;
    if (qty <= 0) delete cart.items[itemId];
    else cart.items[itemId] = Math.min(qty, 20);
    if (cartCount(cart) === 0) cart = { restaurantId: null, restaurantName: "", items: {} };
    saveCart(cart);
    return true;
  }

  // ---- Home ----------------------------------------------------------------
  const homeState = { q: "", cuisine: "", veg: false, minRating: 0, sort: "relevance" };

  async function renderHome() {
    view.innerHTML = `
      <section class="hero">
        <h1>Hungry? Order from the best restaurants near you</h1>
        <p>Fast delivery · Live order tracking · Great offers</p>
        <div class="search"><input id="q" placeholder="Search for restaurants, cuisines or dishes" value="${esc(homeState.q)}" /></div>
      </section>
      <div class="chips" id="cuisines"></div>
      <div class="toolbar">
        <button class="chip ${homeState.veg ? "active" : ""}" id="veg">🟢 Pure Veg</button>
        <button class="chip ${homeState.minRating ? "active" : ""}" id="rating">⭐ Rating 4.3+</button>
        <select id="sort" aria-label="Sort by">
          <option value="relevance">Sort: Relevance</option>
          <option value="rating">Rating: High to low</option>
          <option value="delivery_time">Delivery time</option>
          <option value="cost_low">Cost: Low to high</option>
          <option value="cost_high">Cost: High to low</option>
        </select>
        <span class="count" id="count"></span>
      </div>
      <div class="grid" id="grid"></div>`;
    document.getElementById("sort").value = homeState.sort;
    let debounce;
    document.getElementById("q").addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        homeState.q = e.target.value;
        // A search looks across every cuisine, like the big food apps do.
        if (homeState.q.trim() && homeState.cuisine) { homeState.cuisine = ""; markCuisineChips(); }
        loadRestaurants();
      }, 250);
    });
    document.getElementById("veg").onclick = () => { homeState.veg = !homeState.veg; renderHome(); };
    document.getElementById("rating").onclick = () => { homeState.minRating = homeState.minRating ? 0 : 4.3; renderHome(); };
    document.getElementById("sort").onchange = (e) => { homeState.sort = e.target.value; loadRestaurants(); };

    const cuisines = await api("/api/cuisines");
    document.getElementById("cuisines").innerHTML = [{ name: "" }, ...cuisines]
      .map((c) => `<button class="chip ${homeState.cuisine === c.name ? "active" : ""}" data-c="${esc(c.name)}">${c.name ? esc(c.name) : "All"}</button>`)
      .join("");
    document.querySelectorAll("#cuisines .chip").forEach((b) => (b.onclick = () => { homeState.cuisine = b.dataset.c; renderHome(); }));
    loadRestaurants();
  }

  function markCuisineChips() {
    document.querySelectorAll("#cuisines .chip").forEach((b) => b.classList.toggle("active", b.dataset.c === homeState.cuisine));
  }

  function activeFilters() {
    return [
      homeState.cuisine,
      homeState.veg ? "Pure Veg" : "",
      homeState.minRating ? `Rating ${homeState.minRating}+` : "",
    ].filter(Boolean);
  }

  async function loadRestaurants() {
    const params = new URLSearchParams({ q: homeState.q, cuisine: homeState.cuisine, veg: homeState.veg, min_rating: homeState.minRating, sort: homeState.sort });
    const list = await api(`/api/restaurants?${params}`);
    const grid = document.getElementById("grid");
    if (!grid) return;
    document.getElementById("count").textContent = `${list.length} restaurant${list.length === 1 ? "" : "s"}`;
    grid.innerHTML = list.length
      ? list.map((r, i) => `
        <a class="card" href="#/r/${esc(r.id)}">
          <div class="thumb" style="background:${COLORS[i % COLORS.length]}">${r.emoji}<span class="offer">${esc(r.offer)}</span></div>
          <div class="card-body">
            <div class="row"><h3>${esc(r.name)}</h3><span class="rating">${r.rating} ★</span></div>
            <div class="row muted"><span>${esc(r.cuisines.join(", "))}</span><span>${rupee(r.cost_for_two)} for two</span></div>
            <div class="muted">${r.delivery_minutes} min · ${esc(r.area)}${r.veg_only ? " · Pure Veg" : ""}</div>
            ${r.matched_dishes.length ? `<div class="matches">Serves ${esc(r.matched_dishes.join(", "))}</div>` : ""}
          </div>
        </a>`).join("")
      : (() => {
          const filters = activeFilters();
          const what = homeState.q.trim() ? `for “${esc(homeState.q.trim())}”` : "";
          return `<div class="empty" style="grid-column:1/-1"><div class="big">🍽️</div>
            <p>No restaurants ${what}${filters.length ? ` with filters: <strong>${esc(filters.join(", "))}</strong>` : ""}.</p>
            ${filters.length ? `<button class="btn" id="clear-filters">Clear filters</button>` : "<p>Try another dish or restaurant name.</p>"}
          </div>`;
        })();
    const clear = document.getElementById("clear-filters");
    if (clear) clear.onclick = () => { homeState.cuisine = ""; homeState.veg = false; homeState.minRating = 0; renderHome(); };
  }

  // ---- Restaurant ------------------------------------------------------------
  async function renderRestaurant(id) {
    const r = await api(`/api/restaurants/${encodeURIComponent(id)}`);
    const draw = () => {
      const cart = loadCart();
      const mine = cart.restaurantId === r.id ? cart.items : {};
      view.innerHTML = `
        <section class="rest-head">
          <div class="emoji">${r.emoji}</div>
          <div>
            <h1>${esc(r.name)}</h1>
            <div class="muted">${esc(r.cuisines.join(", "))} · ${esc(r.area)}</div>
            <div class="facts"><span class="rating">${r.rating} ★</span><span>${r.rating_count.toLocaleString("en-IN")} ratings</span>
              <span>🕒 ${r.delivery_minutes} min</span><span>${rupee(r.cost_for_two)} for two</span><span>🏷️ ${esc(r.offer)}</span></div>
          </div>
        </section>
        <div class="menu-layout">
          <nav class="menu-nav">${r.menu.map((c, i) => `<a href="#/r/${esc(r.id)}" data-sec="sec-${i}">${esc(c.name)} (${c.items.length})</a>`).join("")}</nav>
          <div>${r.menu.map((c, i) => `
            <section class="menu-section" id="sec-${i}"><h2>${esc(c.name)}</h2>
              ${c.items.map((it) => `
                <div class="dish">
                  <div>
                    <span class="marker ${it.veg ? "veg" : "nonveg"}" title="${it.veg ? "Veg" : "Non-veg"}"></span>
                    ${it.bestseller ? `<span class="best">★ Bestseller</span>` : ""}
                    <h4>${esc(it.name)}</h4><div><strong>${rupee(it.price)}</strong></div>
                    <p class="muted">${esc(it.description)}</p>
                  </div>
                  <div>${mine[it.id]
                    ? `<div class="qty"><button data-dec="${it.id}" aria-label="Remove one">−</button><span>${mine[it.id]}</span><button data-inc="${it.id}" aria-label="Add one">+</button></div>`
                    : `<button class="add" data-inc="${it.id}">ADD</button>`}</div>
                </div>`).join("")}
            </section>`).join("")}
          </div>
        </div>
        ${cartCount(cart) && cart.restaurantId === r.id ? `<a class="cart-bar" href="#/cart"><span>${cartCount(cart)} item(s) added</span><span>View cart →</span></a>` : ""}`;
      view.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => { if (setQty(r, b.dataset.inc, (loadCart().items[b.dataset.inc] || 0) + 1)) draw(); }));
      view.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => { setQty(r, b.dataset.dec, (loadCart().items[b.dataset.dec] || 0) - 1); draw(); }));
      view.querySelectorAll("[data-sec]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); document.getElementById(a.dataset.sec).scrollIntoView({ behavior: "smooth" }); }));
    };
    draw();
  }

  // ---- Cart & checkout ---------------------------------------------------------
  const checkoutState = { coupon: "", payment: "cod" };

  async function renderCart() {
    const cart = loadCart();
    if (!cartCount(cart)) {
      view.innerHTML = `<div class="empty"><div class="big">🛒</div><h2>Your cart is empty</h2><p>Add something delicious to get started.</p><a class="btn" href="#/">Browse restaurants</a></div>`;
      return;
    }
    const items = Object.entries(cart.items).map(([item_id, quantity]) => ({ item_id, quantity }));
    let q;
    try {
      q = await api("/api/cart/quote", { method: "POST", body: JSON.stringify({ restaurant_id: cart.restaurantId, items, coupon: checkoutState.coupon }) });
    } catch (e) {
      view.innerHTML = `<div class="empty"><h2>Cart needs attention</h2><p>${esc(e.message)}</p><button class="btn" id="clear">Clear cart</button></div>`;
      document.getElementById("clear").onclick = () => { saveCart({ restaurantId: null, restaurantName: "", items: {} }); renderCart(); };
      return;
    }
    const saved = JSON.parse(localStorage.getItem("fd-address") || "{}");
    view.innerHTML = `
      <div class="checkout">
        <div>
          <section class="panel"><h2>Delivery address</h2>
            <form id="addr" novalidate>
              <label for="name">Full name</label><input id="name" value="${esc(saved.name || "")}" autocomplete="name" /><p class="error" data-for="name"></p>
              <label for="phone">Mobile number</label><input id="phone" inputmode="numeric" maxlength="10" value="${esc(saved.phone || "")}" autocomplete="tel" /><p class="error" data-for="phone"></p>
              <label for="line1">House / street / area</label><input id="line1" value="${esc(saved.line1 || "")}" autocomplete="street-address" /><p class="error" data-for="line1"></p>
              <div class="row"><div style="flex:1"><label for="city">City</label><input id="city" value="${esc(saved.city || "New Delhi")}" /><p class="error" data-for="city"></p></div>
                <div style="flex:1"><label for="pincode">PIN code</label><input id="pincode" inputmode="numeric" maxlength="6" value="${esc(saved.pincode || "")}" /><p class="error" data-for="pincode"></p></div></div>
              <label for="instructions">Instructions for the rider (optional)</label><input id="instructions" maxlength="200" placeholder="e.g. Ring the bell twice" />
            </form>
          </section>
          <section class="panel"><h2>Payment</h2>
            <div class="pay">${[["cod", "💵 Cash on delivery"], ["upi", "📱 UPI"], ["card", "💳 Card"]].map(([v, l]) =>
              `<label><input type="radio" name="pay" value="${v}" ${checkoutState.payment === v ? "checked" : ""} /> ${l}</label>`).join("")}</div>
            <p class="muted" style="margin-bottom:0">Payment is recorded as your choice; no real payment is taken in this demo.</p>
          </section>
        </div>
        <div>
          <section class="panel"><h2>${esc(q.restaurant_name)}</h2>
            ${q.lines.map((l) => `<div class="line"><span><span class="marker ${l.veg ? "veg" : "nonveg"}"></span>${esc(l.name)}</span>
              <span class="qty"><button data-dec="${l.item_id}">−</button><span>${l.quantity}</span><button data-inc="${l.item_id}">+</button></span>
              <span>${rupee(l.line_total)}</span></div>`).join("")}
            <div class="coupon" style="margin-top:12px"><input id="coupon" placeholder="Coupon code (try WELCOME50)" value="${esc(checkoutState.coupon)}" /><button class="btn ghost" id="apply">Apply</button></div>
            ${q.coupon_message ? `<p class="${q.coupon ? "saving" : "error"}" style="margin:6px 0 0">${esc(q.coupon_message)}</p>` : ""}
          </section>
          <section class="panel bill"><h2>Bill details</h2>
            <div class="line"><span>Item total</span><span>${rupee(q.item_total)}</span></div>
            <div class="line"><span>Delivery fee</span><span>${q.delivery_fee ? rupee(q.delivery_fee) : "FREE"}</span></div>
            ${q.delivery_fee ? `<div class="muted">Add ${rupee(q.free_delivery_above - q.item_total)} more for free delivery</div>` : ""}
            <div class="line"><span>Platform fee</span><span>${rupee(q.platform_fee)}</span></div>
            <div class="line"><span>GST (5%)</span><span>${rupee(q.gst)}</span></div>
            ${q.discount ? `<div class="line saving"><span>Coupon ${esc(q.coupon)}</span><span>−${rupee(q.discount)}</span></div>` : ""}
            <div class="line total"><span>To pay</span><span>${rupee(q.total)}</span></div>
            <button class="btn" id="place" style="width:100%;margin-top:12px">Place order · ${rupee(q.total)}</button>
          </section>
        </div>
      </div>`;

    const restaurant = { id: cart.restaurantId, name: cart.restaurantName };
    view.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => { setQty(restaurant, b.dataset.inc, loadCart().items[b.dataset.inc] + 1); renderCart(); }));
    view.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => { setQty(restaurant, b.dataset.dec, loadCart().items[b.dataset.dec] - 1); renderCart(); }));
    document.getElementById("apply").onclick = () => { checkoutState.coupon = document.getElementById("coupon").value.trim(); renderCart(); };
    view.querySelectorAll("input[name=pay]").forEach((r) => (r.onchange = () => (checkoutState.payment = r.value)));
    document.getElementById("place").onclick = () => placeOrder(cart, items);
  }

  function validateAddress() {
    const rules = {
      name: [(v) => v.length >= 2, "Enter your name."],
      phone: [(v) => /^[6-9]\d{9}$/.test(v), "Enter a valid 10-digit mobile number."],
      line1: [(v) => v.length >= 5, "Enter your full address."],
      city: [(v) => v.length >= 2, "Enter your city."],
      pincode: [(v) => /^\d{6}$/.test(v), "Enter a 6-digit PIN code."],
    };
    const values = {};
    let ok = true;
    for (const [field, [test, msg]] of Object.entries(rules)) {
      const input = document.getElementById(field);
      values[field] = input.value.trim();
      const valid = test(values[field]);
      input.setAttribute("aria-invalid", String(!valid));
      document.querySelector(`.error[data-for="${field}"]`).textContent = valid ? "" : msg;
      ok = ok && valid;
    }
    return ok ? values : null;
  }

  async function placeOrder(cart, items) {
    const address = validateAddress();
    if (!address) { toast("Please fix the highlighted fields."); return; }
    localStorage.setItem("fd-address", JSON.stringify(address));
    const btn = document.getElementById("place");
    btn.disabled = true;
    btn.textContent = "Placing order…";
    try {
      const order = await api("/api/orders", {
        method: "POST",
        body: JSON.stringify({ restaurant_id: cart.restaurantId, items, coupon: checkoutState.coupon, address,
          payment: checkoutState.payment, instructions: document.getElementById("instructions").value.trim() }),
      });
      saveCart({ restaurantId: null, restaurantName: "", items: {} });
      checkoutState.coupon = "";
      location.hash = `#/orders/${order.id}`;
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
      btn.textContent = "Place order";
    }
  }

  // ---- Tracking & history ------------------------------------------------------
  const STATUS_EMOJI = { placed: "🧾", preparing: "👨‍🍳", out_for_delivery: "🛵", delivered: "✅" };

  async function renderTracking(id) {
    const o = await api(`/api/orders/${encodeURIComponent(id)}`);
    view.innerHTML = `
      <div class="track">
        <section class="panel status-hero">
          <div class="big">${STATUS_EMOJI[o.status]}</div>
          <h1 style="margin:6px 0">${esc(o.status_label)}</h1>
          <p class="muted">Order ${esc(o.id)} from ${esc(o.bill.restaurant_name)}
            ${o.status === "delivered" ? "· Enjoy your meal!" : `· Arriving in about ${o.minutes_remaining} min`}</p>
        </section>
        <section class="panel"><ul class="timeline">
          ${o.timeline.map((t) => `<li class="${t.done ? "done" : ""} ${t.current ? "current" : ""}"><span class="dot"></span>${esc(t.label)}</li>`).join("")}
        </ul></section>
        <section class="panel bill"><h2>Order summary</h2>
          ${o.bill.lines.map((l) => `<div class="line"><span>${l.quantity} × ${esc(l.name)}</span><span>${rupee(l.line_total)}</span></div>`).join("")}
          <div class="line total"><span>Paid (${o.payment.toUpperCase()})</span><span>${rupee(o.bill.total)}</span></div>
          <p class="muted">Delivering to ${esc(o.address.name)}, ${esc(o.address.line1)}, ${esc(o.address.city)} ${esc(o.address.pincode)}</p>
        </section>
        <a class="btn ghost" href="#/orders">All orders</a>
      </div>`;
    if (o.status !== "delivered") pollTimer = setTimeout(() => route(), 3000);
  }

  async function renderOrders() {
    const list = await api("/api/orders");
    view.innerHTML = list.length
      ? `<h1>My orders</h1>${list.map((o) => `
          <a class="panel row" href="#/orders/${esc(o.id)}">
            <div><strong>${esc(o.bill.restaurant_name)}</strong><div class="muted">${esc(o.id)} · ${o.bill.lines.reduce((a, l) => a + l.quantity, 0)} items · ${rupee(o.bill.total)}</div></div>
            <span>${STATUS_EMOJI[o.status]} ${esc(o.status_label)}</span>
          </a>`).join("")}`
      : `<div class="empty"><div class="big">🧾</div><h2>No orders yet</h2><a class="btn" href="#/">Order now</a></div>`;
  }

  // ---- Router ----------------------------------------------------------------------
  async function route() {
    clearTimeout(pollTimer);
    const hash = location.hash.replace(/^#/, "") || "/";
    const parts = hash.split("/").filter(Boolean);
    try {
      if (parts[0] === "r" && parts[1]) await renderRestaurant(parts[1]);
      else if (parts[0] === "cart") await renderCart();
      else if (parts[0] === "orders" && parts[1]) await renderTracking(parts[1]);
      else if (parts[0] === "orders") await renderOrders();
      else await renderHome();
    } catch (e) {
      view.innerHTML = `<div class="empty"><div class="big">😕</div><h2>Something went wrong</h2><p>${esc(e.message)}</p><a class="btn" href="#/">Go home</a></div>`;
    }
  }

  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
  renderCartCount();
  route();
})();
'''

TEST_STORE = r'''import pytest

from app.models import CartLine
from app.store import OrderStore, PricingError, quote, search


def lines(*pairs):
    return [CartLine(item_id=i, quantity=q) for i, q in pairs]


def test_search_filters_and_sorting():
    assert {r["id"] for r in search(veg=True)} == {"dosa-plaza", "green-bowl", "sweet-tooth"}
    assert [r["id"] for r in search(cuisine="Pizza")] == ["pizza-piazza"]
    assert all(r["rating"] >= 4.5 for r in search(min_rating=4.5))
    by_time = search(sort="delivery_time")
    assert [r["delivery_minutes"] for r in by_time] == sorted(r["delivery_minutes"] for r in by_time)


def test_search_matches_dishes():
    results = search(q="momos")
    assert [r["id"] for r in results] == ["dragon-wok"]
    assert results[0]["matched_dishes"] == ["Veg Steamed Momos"]


def test_quote_fees_gst_and_free_delivery():
    small = quote("dosa-plaza", lines(("dp-masala", 1)))
    assert small["item_total"] == 129 and small["delivery_fee"] == 40
    assert small["gst"] == round(129 * 0.05)
    assert small["total"] == 129 + 40 + 5 + small["gst"]
    big = quote("dosa-plaza", lines(("dp-masala", 3)))
    assert big["delivery_fee"] == 0  # free above ₹299


def test_coupons():
    order = lines(("bh-mutton", 1))  # ₹389
    assert quote("biryani-house", order, "WELCOME50")["discount"] == 100  # 50% capped at ₹100
    assert quote("biryani-house", lines(("bh-salan", 1)), "WELCOME50")["coupon"] == ""  # below min order
    assert quote("biryani-house", order, "FREEDEL")["discount"] == quote("biryani-house", order)["delivery_fee"]
    bogus = quote("biryani-house", order, "NOPE")
    assert bogus["discount"] == 0 and "not a valid coupon" in bogus["coupon_message"]


def test_items_must_belong_to_the_restaurant():
    with pytest.raises(PricingError):
        quote("pizza-piazza", lines(("bh-mutton", 1)))
    with pytest.raises(PricingError):
        quote("no-such-place", lines(("pp-margherita", 1)))


def test_order_status_progresses_over_time():
    now = [1000.0]
    store = OrderStore(clock=lambda: now[0])
    from app.models import Address, OrderRequest

    req = OrderRequest(
        restaurant_id="burger-barn", items=lines(("bb-fries", 2)), payment="cod",
        address=Address(name="Asha", phone="9876543210", line1="12 MG Road", city="Delhi", pincode="110001"),
    )
    order = store.place(req)
    assert order["id"] == "FD00001" and order["status"] == "placed"
    now[0] += 30
    assert store.get(order["id"])["status"] == "preparing"
    now[0] += 40
    assert store.get(order["id"])["status"] == "out_for_delivery"
    now[0] += 100
    done = store.get(order["id"])
    assert done["status"] == "delivered" and done["minutes_remaining"] == 0
    assert [t["done"] for t in done["timeline"]] == [True, True, True, True]
'''

TEST_API = r'''from fastapi.testclient import TestClient

from app import main

ADDRESS = {"name": "Asha", "phone": "9876543210", "line1": "12 MG Road", "city": "Delhi", "pincode": "110001"}


def client() -> TestClient:
    main.orders = main.OrderStore()
    return TestClient(main.app)


def test_pages_and_assets():
    c = client()
    assert "__TITLE__" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/styles.css").status_code == 200
    assert c.get("/health").json() == {"status": "ok"}


def test_discovery_endpoints():
    c = client()
    assert any(x["name"] == "Biryani" for x in c.get("/api/cuisines").json())
    veg = c.get("/api/restaurants", params={"veg": True}).json()
    assert veg and all(r["veg_only"] for r in veg)
    assert "menu" not in veg[0]
    r = c.get("/api/restaurants/pizza-piazza").json()
    assert r["menu"][0]["items"]
    assert c.get("/api/restaurants/nope").status_code == 404
    assert c.get("/api/restaurants", params={"sort": "bogus"}).status_code == 422


def test_quote_rejects_foreign_items():
    c = client()
    def cart(item_id, quantity):
        return {"restaurant_id": "pizza-piazza", "items": [{"item_id": item_id, "quantity": quantity}]}

    ok = c.post("/api/cart/quote", json=cart("pp-margherita", 2))
    assert ok.status_code == 200 and ok.json()["item_total"] == 498
    bad = c.post("/api/cart/quote", json=cart("bh-mutton", 1))
    assert bad.status_code == 422


def test_order_flow_and_validation():
    c = client()
    body = {"restaurant_id": "dosa-plaza", "items": [{"item_id": "dp-masala", "quantity": 2}], "address": ADDRESS,
            "payment": "upi", "coupon": "welcome50"}
    created = c.post("/api/orders", json=body)
    assert created.status_code == 201
    order = created.json()
    assert order["bill"]["coupon"] == "WELCOME50" and order["status"] == "placed"
    assert c.get(f"/api/orders/{order['id']}").json()["id"] == order["id"]
    assert [o["id"] for o in c.get("/api/orders").json()] == [order["id"]]
    assert c.get("/api/orders/FD99999").status_code == 404

    for bad in ({**ADDRESS, "phone": "12345"}, {**ADDRESS, "pincode": "11"}):
        assert c.post("/api/orders", json={**body, "address": bad}).status_code == 422
    assert c.post("/api/orders", json={**body, "payment": "bitcoin"}).status_code == 422
    assert c.post("/api/orders", json={**body, "items": []}).status_code == 422
'''

README = r'''# __TITLE__

A Zomato/Swiggy-style food ordering app generated by Intent2Deploy AI from the request: "__INTENT__".

## Features

- Restaurant discovery: search restaurants and dishes, filter by cuisine, pure veg and rating, sort by rating, time or cost
- Restaurant menus with veg/non-veg markers and bestsellers
- Cart (one restaurant at a time, saved in the browser) with quantity controls
- Server-side bill: item total, delivery fee (free above ₹299), platform fee, 5% GST, coupons (`WELCOME50`, `FREEDEL`, `FEAST75`)
- Checkout with address validation and payment choice (COD / UPI / card — recorded only, no real payment)
- Live order tracking (Placed → Preparing → Out for delivery → Delivered) and order history

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port __PORT__
```

Open http://127.0.0.1:__PORT__. API docs: http://127.0.0.1:__PORT__/docs

__WHERE_IT_RUNS__

## Test

```bash
python -m pytest -v
```

## Notes

- Orders are kept in memory and reset when the server restarts; add a database before production use.
- Order status advances on a compressed demo timeline (about 2 minutes end to end).
'''


def files(title: str, intent: str, common: dict) -> dict[str, str]:
    """File contents before placeholder filling (see templates.files)."""
    return {
        "app/__init__.py": '"""Food delivery app package."""\n',
        "app/data.py": DATA_PY,
        "app/models.py": MODELS_PY,
        "app/store.py": STORE_PY,
        "app/main.py": MAIN_PY,
        "static/index.html": INDEX_HTML,
        "static/styles.css": STYLES_CSS,
        "static/app.js": APP_JS,
        "tests/test_store.py": TEST_STORE,
        "tests/test_api.py": TEST_API,
        "requirements.txt": common["requirements"],
        "pytest.ini": common["pytest_ini"],
        "pyproject.toml": common["pyproject"],
        "README.md": README,
        ".github/workflows/ci.yml": common["ci"],
    }
