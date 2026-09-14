from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session

from app.core.db import get_session as _get_session
from app.services.providers.base import LLMProvider
from app.services.providers.factory import get_provider as _get_provider


def get_session() -> Generator[Session, None, None]:
    yield from _get_session()


def get_provider() -> LLMProvider:
    return _get_provider()
