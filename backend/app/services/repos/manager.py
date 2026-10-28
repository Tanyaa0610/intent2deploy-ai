"""Repository Manager: create, connect, clone and browse repositories.

Security model:
- Local paths must be absolute and resolve (symlinks followed) inside one of
  `settings.repo_roots`; credential directories (~/.ssh, ~/.aws, ...) are
  refused even when inside a root.
- Creating a repository never overwrites: the target must not exist or be an
  empty directory, and README.md is written with exclusive-create.
- GitHub tokens are used only for the git subprocess, passed through the
  environment as an HTTP header (never in argv, the remote URL, .git/config,
  the database, or an API response) and scrubbed from error messages.
- File browsing/search is confined to the repository root, hides `.git`, and
  refuses secret-like files (.env, private keys) using the same rules that
  keep them out of RAG context.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from app.core.config import settings
from app.core.security import IGNORED_DIR_NAMES, IGNORED_FILE_PATTERNS
from app.services.git.git_ops import GitCloneError, parse_github_url
from app.services.rag.chunking import detect_language

SENSITIVE_DIR_NAMES = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".gcloud", ".password-store"}

MAX_TREE_ENTRIES = 1000
MAX_FILE_BYTES = 1_000_000
MAX_SEARCH_FILE_BYTES = 400_000
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_FILES = 5000

_SECRET_FILE_PATTERNS = [
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r".*id_rsa.*"),
    re.compile(r".*\.pem$"),
    re.compile(r".*\.key$"),
]


class RepoManagerError(Exception):
    """User-facing error; the message is safe to return in an API response."""


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------
def allowed_roots() -> list[Path]:
    return [r.resolve() for r in settings.repo_roots]


def resolve_allowed_path(raw: str) -> Path:
    raw = (raw or "").strip()
    if not raw:
        raise RepoManagerError("Enter a path.")
    if "\x00" in raw:
        raise RepoManagerError("Invalid path.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise RepoManagerError("Use an absolute path (for example C:\\code\\my-app or /home/me/my-app).")
    resolved = candidate.resolve()

    for root in allowed_roots():
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if any(part in SENSITIVE_DIR_NAMES for part in rel.parts):
            raise RepoManagerError("This location holds credentials and cannot be used as a repository.")
        if resolved == Path.home().resolve():
            raise RepoManagerError("Choose a project folder, not the home directory itself.")
        return resolved

    roots = ", ".join(str(r) for r in allowed_roots())
    raise RepoManagerError(f"Path is outside the allowed roots ({roots}). Set ALLOWED_REPO_ROOTS to allow more.")


def validate_existing_directory(raw: str) -> Path:
    path = resolve_allowed_path(raw)
    if not path.exists():
        raise RepoManagerError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise RepoManagerError(f"Not a directory: {path}")
    if not os.access(path, os.R_OK | os.X_OK):
        raise RepoManagerError(f"No read access to {path}")
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        raise RepoManagerError(f"Cannot read {path}: {exc.strerror or exc}") from exc
    return path


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_local_repository(raw: str, git_init: bool, readme: bool, title: str) -> Path:
    target = resolve_allowed_path(raw)
    parent = target.parent
    if not parent.is_dir():
        raise RepoManagerError(f"Parent folder does not exist: {parent}")

    created_dir = False
    if target.exists():
        if not target.is_dir():
            raise RepoManagerError(f"A file already exists at {target}. Nothing was changed.")
        if any(target.iterdir()):
            raise RepoManagerError(f"{target} is not empty. Nothing was changed — use Connect for existing projects.")
    else:
        try:
            target.mkdir()
        except OSError as exc:
            raise RepoManagerError(f"Could not create {target}: {exc.strerror or exc}") from exc
        created_dir = True

    try:
        if readme:
            # "x" = exclusive create: fails instead of overwriting.
            with open(target / "README.md", "x", encoding="utf-8") as fh:
                fh.write(f"# {title or target.name}\n")
        if git_init:
            try:
                Repo.init(target, initial_branch="main")
            except GitCommandError:
                Repo.init(target)  # git < 2.28 has no --initial-branch
    except (OSError, GitCommandError) as exc:
        # Roll back only what this call created.
        if created_dir:
            shutil.rmtree(target, ignore_errors=True)
        else:
            (target / "README.md").unlink(missing_ok=True)
            shutil.rmtree(target / ".git", ignore_errors=True)
        raise RepoManagerError(f"Could not create repository: {exc}") from exc
    return target


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def _git_env(token: str | None) -> dict[str, str]:
    """Environment for git subprocesses: never prompt, never use the host's
    stored credential helpers, and send `token` (if any) as an HTTP header via
    GIT_CONFIG_* env vars so it never touches argv or .git/config."""
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "",
    }
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_1"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_1"] = f"AUTHORIZATION: basic {basic}"
    return env


def _git_error_message(exc: GitCommandError, token: str | None, branch: str | None = None) -> str:
    text = f"{exc.stderr or ''} {exc.stdout or ''}"
    if token:
        text = text.replace(token, "***")
    lowered = text.lower()
    if branch and ("remote branch" in lowered and "not found" in lowered):
        return f"Branch '{branch}' not found on the remote."
    if "could not resolve host" in lowered or ("unable to access" in lowered and "resolve" in lowered):
        return "Cannot reach github.com from this machine."
    if (
        "repository not found" in lowered
        or "authentication failed" in lowered
        or "could not read username" in lowered
        or "terminal prompts disabled" in lowered
        or "403" in lowered
    ):
        if token:
            return "Repository not found, or the token has no read access to it."
        return "Repository not found or private. For private repositories, provide a token."
    first = next((ln.strip() for ln in text.splitlines() if ln.strip().lower().startswith(("fatal", "error"))), "")
    return first[:300] or "git failed."


def clean_github_url(url: str) -> tuple[str, str, str]:
    """Return (owner, repo, credential-free clone URL)."""
    try:
        owner, repo = parse_github_url(url)
    except GitCloneError as exc:
        raise RepoManagerError(str(exc)) from exc
    return owner, repo, f"https://github.com/{owner}/{repo}.git"


def clone_github(clean_url: str, dest: Path, branch: str | None, token: str | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise RepoManagerError(f"Clone destination already exists: {dest}")
    kwargs: dict = {"depth": 1, "env": _git_env(token)}
    if not branch:
        from app.services.git.git_ops import integration_branch_on_remote

        branch = integration_branch_on_remote(clean_url, _git_env(token))  # staging, if present
    if branch:
        kwargs["branch"] = branch
    try:
        Repo.clone_from(clean_url, dest, **kwargs)
    except GitCommandError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise RepoManagerError(_git_error_message(exc, token, branch)) from exc


def pull_github(path: Path, token: str | None) -> str:
    try:
        repo = Repo(path)
        with repo.git.custom_environment(**_git_env(token)):
            repo.git.pull("--ff-only")
        return repo.head.commit.hexsha[:8]
    except GitCommandError as exc:
        raise RepoManagerError(_git_error_message(exc, token)) from exc
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise RepoManagerError("Local clone is missing or not a git repository.") from exc


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------
@dataclass
class GitInfo:
    is_git: bool
    branch: str | None = None
    head: str | None = None
    dirty: bool | None = None


def git_info(path: Path, include_dirty: bool = False) -> GitInfo:
    try:
        repo = Repo(path)
    except (InvalidGitRepositoryError, NoSuchPathError, OSError):
        return GitInfo(is_git=False)
    info = GitInfo(is_git=True)
    try:
        info.branch = repo.active_branch.name
    except TypeError:
        info.branch = "(detached)"
    except Exception:
        info.branch = None
    try:
        if repo.head.is_valid():
            info.head = repo.head.commit.hexsha[:8]
    except Exception:
        pass
    if include_dirty:
        try:
            info.dirty = repo.is_dirty(untracked_files=True)
        except Exception:
            info.dirty = None
    return info


def is_accessible(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.R_OK)
    except OSError:
        return False


def _is_secret_file(name: str) -> bool:
    return any(p.match(name) for p in _SECRET_FILE_PATTERNS)


def safe_child(root: Path, rel: str) -> Path:
    root_r = root.resolve()
    rel = (rel or "").replace("\\", "/").strip("/")
    target = (root_r / rel).resolve() if rel else root_r
    try:
        rel_parts = target.relative_to(root_r).parts
    except ValueError as exc:
        raise RepoManagerError("Path escapes the repository.") from exc
    if ".git" in rel_parts:
        raise RepoManagerError("The .git directory is not browsable.")
    return target


def list_directory(root: Path, rel: str) -> list[dict]:
    target = safe_child(root, rel)
    if not target.is_dir():
        raise RepoManagerError("Not a directory.")
    root_r = root.resolve()
    entries: list[dict] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise RepoManagerError(f"Cannot read directory: {exc.strerror or exc}") from exc
    for child in children:
        if child.name == ".git":
            continue
        try:
            is_dir = child.is_dir()
            # Hide symlinks that point outside the repository.
            child.resolve().relative_to(root_r)
        except (OSError, ValueError):
            continue
        entry = {
            "name": child.name,
            "path": (target.relative_to(root_r) / child.name).as_posix(),
            "type": "dir" if is_dir else "file",
            "size": None if is_dir else _size(child),
            "ignored": (child.name in IGNORED_DIR_NAMES) if is_dir else any(p.match(child.name) for p in IGNORED_FILE_PATTERNS),
            "restricted": (not is_dir) and _is_secret_file(child.name),
        }
        entries.append(entry)
        if len(entries) >= MAX_TREE_ENTRIES:
            break
    return entries


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def read_file(root: Path, rel: str) -> dict:
    target = safe_child(root, rel)
    if not target.is_file():
        raise RepoManagerError("Not a file.")
    if _is_secret_file(target.name):
        raise RepoManagerError("This file may contain secrets and is not shown.")
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise RepoManagerError(f"File is too large to preview ({size // 1024} KB).")
    data = target.read_bytes()
    if b"\x00" in data[:4096]:
        raise RepoManagerError("Binary file — no preview.")
    text = data.decode("utf-8", errors="replace")
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "size": size,
        "language": detect_language(target),
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "content": text,
    }


def search_text(root: Path, query: str, case_sensitive: bool = False) -> dict:
    if not query.strip():
        raise RepoManagerError("Enter a search term.")
    root_r = root.resolve()
    needle = query if case_sensitive else query.lower()
    results: list[dict] = []
    scanned = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root_r, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIR_NAMES)
        for name in sorted(filenames):
            if any(p.match(name) for p in IGNORED_FILE_PATTERNS):
                continue
            path = Path(dirpath) / name
            try:
                if path.is_symlink() or path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            scanned += 1
            if scanned > MAX_SEARCH_FILES:
                truncated = True
                break
            if b"\x00" in data[:4096]:
                continue
            text = data.decode("utf-8", errors="replace")
            hay = text if case_sensitive else text.lower()
            if needle not in hay:
                continue
            rel = path.relative_to(root_r).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if needle in (line if case_sensitive else line.lower()):
                    results.append({"file": rel, "line": lineno, "text": line.strip()[:240]})
                    if len(results) >= MAX_SEARCH_RESULTS:
                        return {"results": results, "truncated": True, "files_scanned": scanned}
        if truncated:
            break
    return {"results": results, "truncated": truncated, "files_scanned": scanned}


def index_insights(collection_name: str) -> dict:
    from collections import Counter

    from app.services.rag.vectorstore import get_vectorstore

    raw = get_vectorstore(collection_name).get(include=["metadatas"])
    metas: list[dict] = raw.get("metadatas") or []
    files_by_lang: dict[str, set[str]] = {}
    chunk_types: Counter[str] = Counter()
    chunks_per_file: Counter[str] = Counter()
    symbols = 0
    for m in metas:
        f = m.get("file", "")
        files_by_lang.setdefault(m.get("language") or "other", set()).add(f)
        chunk_types[m.get("chunk_type") or "other"] += 1
        chunks_per_file[f] += 1
        if m.get("symbol"):
            symbols += 1
    return {
        "chunks": len(metas),
        "files": len(chunks_per_file),
        "symbols": symbols,
        "languages": sorted(
            ({"language": k, "files": len(v)} for k, v in files_by_lang.items()), key=lambda x: -x["files"]
        ),
        "chunk_types": [{"type": k, "count": v} for k, v in chunk_types.most_common()],
        "largest_files": [{"file": k, "chunks": v} for k, v in chunks_per_file.most_common(8)],
    }
