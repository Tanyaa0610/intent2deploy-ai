"""Sandboxed command execution (master spec §14).

Every workflow gets its own workspace directory under
`{settings.workspaces_dir}/{workflow_id}`. Only allowlisted commands run,
under a timeout, with stdout/stderr/exit code captured. No arbitrary
model-generated shell command is ever executed directly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.security import CommandSecurityError, validate_command

# Ensure allowlisted tools installed in this backend's virtualenv (ruff,
# pytest, python3, ...) are resolvable even though the sandboxed
# subprocess runs with a different cwd. Without this, `subprocess.run`
# falls back to whatever "python3"/"ruff" happens to be first on the
# inherited PATH (which may be a bare system Python lacking pytest).
_VENV_BIN_DIR = str(Path(sys.executable).parent)


def _resolve_executable(name: str, search_path: str) -> str:
    """Resolve an allowlisted executable against the sandbox PATH.

    On Windows, subprocess looks programs up in the *parent's* PATH (not the
    `env` passed in), so the venv-first PATH alone is not enough. "python3"
    in particular often resolves to the Microsoft Store stub there, and a
    venv has no python3.exe — so Python always means this backend's own
    interpreter."""
    if name in ("python", "python3"):
        return sys.executable
    return shutil.which(name, path=search_path) or name


def _sandbox_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = _VENV_BIN_DIR + os.pathsep + env.get("PATH", "")
    return env


@dataclass
class CommandResult:
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    rejected_reason: str = ""
    skipped: bool = False  # deliberately not run (e.g. Docker not available); explained in stdout

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        if self.rejected_reason:
            return "error"
        if self.timed_out:
            return "failed"
        return "passed" if self.exit_code == 0 else "failed"


# Written into a workspace whose repository has no .gitignore of its own.
DEFAULT_GITIGNORE = "__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n"


def workspace_path(workflow_id: str) -> Path:
    root = Path(settings.workspaces_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / workflow_id


def _force_rmtree(path: Path) -> None:
    """rmtree that also removes read-only files (git object files are
    read-only on Windows, which makes a plain rmtree fail)."""
    import stat

    def _retry(func, p, _exc):  # noqa: ANN001
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:  # pragma: no cover
        shutil.rmtree(path, onerror=_retry)


def create_workspace(workflow_id: str, source_repo: Path) -> Path:
    """Copy the source repository into an isolated workspace directory,
    excluding build artifacts. Git history is kept so the workflow branch
    builds on the repository's real history (pushable, PR-able); the
    original repository is never modified."""
    dest = workspace_path(workflow_id)
    if dest.exists():
        _force_rmtree(dest)
    shutil.copytree(
        source_repo,
        dest,
        ignore=shutil.ignore_patterns("node_modules", "__pycache__", ".venv", "venv", "*.pyc"),
    )
    gitignore = dest / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
    return dest


def destroy_workspace(workflow_id: str) -> None:
    dest = workspace_path(workflow_id)
    if dest.exists():
        _force_rmtree(dest)


def run_command(workspace: Path, command: str, timeout: int | None = None) -> CommandResult:
    """Validate and run a single allowlisted command inside `workspace`."""
    try:
        argv = validate_command(command)
    except CommandSecurityError as exc:
        return CommandResult(command=command, exit_code=None, stdout="", stderr=str(exc), duration_ms=0, rejected_reason=str(exc))

    env = _sandbox_env()
    argv = [_resolve_executable(argv[0], env["PATH"]), *argv[1:]]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout or settings.command_timeout_seconds,
            env=env,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout[-20000:],
            stderr=proc.stderr[-20000:],
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            command=command,
            exit_code=None,
            stdout=(exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
            stderr=f"Command timed out after {timeout or settings.command_timeout_seconds}s",
            duration_ms=duration_ms,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            command=command, exit_code=None, stdout="", stderr=str(exc), duration_ms=duration_ms, rejected_reason=str(exc)
        )


def docker_available() -> tuple[bool, str]:
    """Whether a Docker daemon is reachable (CLI installed and engine running)."""
    exe = shutil.which("docker")
    if not exe:
        return False, "Docker is not installed on this machine."
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            [exe, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker did not respond: {exc}"
    if proc.returncode != 0 or not proc.stdout.strip():
        return False, "Docker is installed but its engine isn't running (start Docker Desktop)."
    return True, proc.stdout.strip()
