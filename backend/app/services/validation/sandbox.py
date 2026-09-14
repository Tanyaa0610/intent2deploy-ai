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

    @property
    def status(self) -> str:
        if self.rejected_reason:
            return "error"
        if self.timed_out:
            return "failed"
        return "passed" if self.exit_code == 0 else "failed"


def workspace_path(workflow_id: str) -> Path:
    root = Path(settings.workspaces_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / workflow_id


def create_workspace(workflow_id: str, source_repo: Path) -> Path:
    """Copy the source repository into an isolated workspace directory,
    excluding VCS/build artifacts."""
    dest = workspace_path(workflow_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        source_repo,
        dest,
        ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv", "venv", "*.pyc"),
    )
    gitignore = dest / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n", encoding="utf-8")
    return dest


def destroy_workspace(workflow_id: str) -> None:
    dest = workspace_path(workflow_id)
    if dest.exists():
        shutil.rmtree(dest)


def run_command(workspace: Path, command: str) -> CommandResult:
    """Validate and run a single allowlisted command inside `workspace`."""
    try:
        argv = validate_command(command)
    except CommandSecurityError as exc:
        return CommandResult(command=command, exit_code=None, stdout="", stderr=str(exc), duration_ms=0, rejected_reason=str(exc))

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=settings.command_timeout_seconds,
            env=_sandbox_env(),
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
            stderr=f"Command timed out after {settings.command_timeout_seconds}s",
            duration_ms=duration_ms,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandResult(
            command=command, exit_code=None, stdout="", stderr=str(exc), duration_ms=duration_ms, rejected_reason=str(exc)
        )
