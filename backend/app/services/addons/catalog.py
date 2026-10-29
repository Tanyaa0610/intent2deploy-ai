"""The add-on catalog and how add-ons are matched, checked and applied."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.addons import dark_mode, database, login_protection

_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "data"}


@dataclass(frozen=True)
class AddOn:
    id: str
    title: str
    description: str
    triggers: re.Pattern
    applicable: Callable[[dict[str, str]], bool]
    applied: Callable[[dict[str, str]], bool]
    apply: Callable[[dict[str, str]], dict[str, str]]


ADDONS: list[AddOn] = [
    AddOn(
        "database", "Database (save data permanently)",
        "Stores accounts or records in a SQLite database instead of memory, so nothing is lost when the app restarts "
        "or is redeployed. Docker keeps it in a volume. Same API, pages and tests, plus persistence tests.",
        re.compile(r"\b(database|db|sqlite|persist\w*|save (the )?data|data (is )?(lost|gone|disappears)|"
                   r"store (it )?permanently|proper back-?end|real back-?end|back-?end (with|and) (a )?(database|db))\b",
                   re.I),
        lambda f: bool(database.kind(f)), database.applied, database.apply,
    ),
    AddOn(
        "dark_mode", "Dark mode",
        "Adds dark mode with a 🌙/☀️ toggle. It follows the device setting until the person picks one, and remembers it.",
        re.compile(r"\b(dark ?mode|dark theme|night mode|theme toggle)\b", re.I),
        dark_mode.applicable, dark_mode.applied, dark_mode.apply,
    ),
    AddOn(
        "login_protection", "Sign-in protection (rate limiting)",
        "Blocks password guessing: after 5 wrong passwords for an email in 15 minutes, sign-in for it is refused for a "
        "while, and reset codes can be requested at most 3 times per 15 minutes.",
        re.compile(r"\b(rate ?limit\w*|brute[- ]?force|password guessing|too many (login|sign-?in) attempts|"
                   r"(protect|secure) (the )?(login|sign-?in)|lock(ed)? out|account lockout)\b", re.I),
        login_protection.applicable, login_protection.applied, login_protection.apply,
    ),
]
BY_ID = {a.id: a for a in ADDONS}


def read_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not any(part in _SKIP for part in rel.parts) and p.stat().st_size < 500_000:
            try:
                files[rel.as_posix()] = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return files


def status(addon: AddOn, files: dict[str, str]) -> str:
    if addon.applied(files):
        return "applied"
    return "available" if addon.applicable(files) else "not_supported"


def statuses(root: Path) -> list[dict]:
    files = read_files(root)
    return [{"id": a.id, "title": a.title, "description": a.description, "status": status(a, files)} for a in ADDONS]


def matching(problem: str) -> list[str]:
    """Add-on ids a problem description asks for."""
    return [a.id for a in ADDONS if a.triggers.search(problem)]


def apply_all(root: Path, ids: list[str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Apply the add-ons in order. Returns (original files, new contents of every
    changed or new file, ids actually applied). Add-ons that are already applied
    or not supported for this project are skipped."""
    from app.services.validation.sandbox import DEFAULT_GITIGNORE

    original = read_files(root)
    # The workspace a change is applied in gets this .gitignore when the repository has none.
    original.setdefault(".gitignore", DEFAULT_GITIGNORE)
    files = dict(original)
    changed: dict[str, str] = {}
    used = []
    for addon_id in ids:
        addon = BY_ID.get(addon_id)
        if addon is None or status(addon, files) != "available":
            continue
        for path, content in addon.apply(files).items():
            if files.get(path) != content:
                files[path] = changed[path] = content
        used.append(addon_id)
    return original, changed, used
