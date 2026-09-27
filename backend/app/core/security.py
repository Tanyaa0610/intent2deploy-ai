"""Security primitives shared across services.

Implements the controls required by master spec §34:
- path traversal protection
- repository path validation
- command allowlist
- secret-pattern detection (for excluding secrets from RAG/LLM context)
"""
from __future__ import annotations

import re
from pathlib import Path

# Directories/files never indexed or sent to the LLM.
IGNORED_DIR_NAMES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".chroma",
    "chroma_data",
    "workspaces",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    "target",
    ".tox",
}

IGNORED_FILE_PATTERNS = [
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r".*\.pyc$"),
    re.compile(r".*\.pyo$"),
    re.compile(r".*\.so$"),
    re.compile(r".*\.dll$"),
    re.compile(r".*\.exe$"),
    re.compile(r".*\.db$"),
    re.compile(r".*\.sqlite3?$"),
    re.compile(r".*\.(png|jpg|jpeg|gif|ico|pdf|zip|tar|gz|woff2?|ttf|eot|mp4|mov)$", re.I),
    re.compile(r".*id_rsa.*"),
    re.compile(r".*\.pem$"),
    re.compile(r".*\.key$"),
]

# Patterns used to scan generated content / repository files for likely
# secrets before they are sent to the LLM or committed. This is a coarse
# heuristic scanner, not a guarantee of secret detection.
SECRET_PATTERNS = [
    # Require a quoted literal value (not a type annotation or bare
    # identifier like `password: str` / `new_password=raw_password`) so
    # these patterns flag hardcoded secret VALUES, not parameter names —
    # source code legitimately uses words like "password"/"secret" as
    # identifiers far more often than it hardcodes real credentials.
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"][A-Za-z0-9_\-]{8,}['\"]"),
    re.compile(r"(?i)password\s*[:=]\s*['\"]\S{4,}['\"]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]

# Commands explicitly permitted inside the sandboxed validation workspace.
# Each entry is the executable name; argument validation happens separately.
COMMAND_ALLOWLIST = {
    "pytest",
    "python",
    "python3",
    "ruff",
    "npm",
    "node",
    "pip",
    "mypy",
    "coverage",
}

# Sub-command allowlist for multi-word invocations like `npm test`.
NPM_ALLOWED_SUBCOMMANDS = {"test", "run", "install", "ci", "build"}

DANGEROUS_TOKENS = [
    "rm ", "rm\t", "sudo", "curl ", "wget ", ">", "<", "|", "&&", ";", "$(", "`",
    "chmod", "chown", "kill", "shutdown", "reboot", "mkfs", "dd ", "eval",
    "--force", "-rf",
]


class PathSecurityError(Exception):
    pass


class CommandSecurityError(Exception):
    pass


def is_ignored_path(path: Path) -> bool:
    parts = set(path.parts)
    if parts & IGNORED_DIR_NAMES:
        return True
    name = path.name
    return any(p.match(name) for p in IGNORED_FILE_PATTERNS)


def validate_repository_path(base_dir: Path, candidate: Path) -> Path:
    """Resolve `candidate` and ensure it stays within `base_dir` (no traversal)."""
    base_resolved = base_dir.resolve()
    candidate_resolved = (base_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise PathSecurityError(
            f"Path '{candidate}' escapes the allowed base directory '{base_dir}'."
        ) from exc
    return candidate_resolved


def validate_command(command: str) -> list[str]:
    """Validate a command string against the allowlist. Returns the argv list.

    Raises CommandSecurityError if the command is not permitted.
    """
    stripped = command.strip()
    if not stripped:
        raise CommandSecurityError("Empty command.")

    for token in DANGEROUS_TOKENS:
        if token in stripped:
            raise CommandSecurityError(f"Command contains disallowed token: '{token.strip()}'.")

    parts = stripped.split()
    executable = parts[0]
    # normalize things like "python3.11" -> still must be literally allowlisted
    if executable not in COMMAND_ALLOWLIST:
        raise CommandSecurityError(f"Executable '{executable}' is not in the command allowlist.")

    if executable == "npm" and len(parts) > 1:
        sub = parts[1]
        if sub not in NPM_ALLOWED_SUBCOMMANDS:
            raise CommandSecurityError(f"npm subcommand '{sub}' is not allowlisted.")

    return parts


def scan_for_secrets(text: str) -> list[str]:
    """Return a list of matched secret-like substrings (redacted) found in text."""
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{pattern.pattern[:30]}... at offset {match.start()}")
    return findings


def strip_potential_secrets(text: str) -> str:
    """Redact likely secret values before including content in LLM context/logs."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
