"""Structured logging helpers.

`get_logger` returns a stdlib logger configured to emit one JSON object
per line (easy to grep/parse). `redact` strips known-sensitive keys
before anything is logged — callers should always pass event details
through it rather than logging raw dicts, so secrets never reach a log
sink by accident.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "salt",
    "token",
    "session_token",
    "reset_token",
    "authorization",
    "card_number",
    "cvv",
    "secret",
}

_configured = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload["fields"] = extra
        return json.dumps(payload)


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        root = logging.getLogger("shopflow")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _configured = True
    return logging.getLogger(f"shopflow.{name}")


def redact(details: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `details` with any sensitive key's value replaced
    by a fixed marker. Never log `details` directly — always log the
    result of this function."""
    redacted: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _SENSITIVE_KEYS:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted
