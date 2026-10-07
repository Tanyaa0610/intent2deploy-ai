"""Application configuration.

Values are read from real environment variables (see `.env.example`); a
tiny built-in loader applies a `.env` file in the repository root if one
exists, so no extra dependency (e.g. python-dotenv) is required. Every
setting has a safe local-development default, so the app also runs with
no `.env` file at all.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(REPO_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str
    session_ttl_seconds: int
    reset_token_ttl_seconds: int
    low_stock_threshold: int
    max_quantity_per_product: int
    seed_on_startup: bool


def get_settings() -> Settings:
    """Re-reads environment variables each call (cheap, and makes tests
    that monkeypatch os.environ straightforward)."""
    return Settings(
        db_path=os.environ.get("SHOPFLOW_DB_PATH", "shopflow.db"),
        session_ttl_seconds=_env_int("SHOPFLOW_SESSION_TTL_SECONDS", 3600),
        reset_token_ttl_seconds=_env_int("SHOPFLOW_RESET_TOKEN_TTL_SECONDS", 900),
        low_stock_threshold=_env_int("SHOPFLOW_LOW_STOCK_THRESHOLD", 5),
        max_quantity_per_product=_env_int("SHOPFLOW_MAX_QUANTITY_PER_PRODUCT", 10),
        seed_on_startup=_env_bool("SHOPFLOW_SEED_ON_STARTUP", True),
    )
