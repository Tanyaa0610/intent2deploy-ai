"""Configurable validation pipeline (master spec §16):

1. Syntax/compile check
2. Lint
3. Unit tests
4. Integration tests (if available/configured)
5. Build (if a build command is configured)
6. Optional security/static checks
7. (Final regression validation is just re-running the same pipeline
   after a repair — see app/services/validation/repair.py)
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.validation.sandbox import CommandResult, run_command, workspace_path


@dataclass
class StageResult:
    stage: str
    result: CommandResult


def _default_test_command(workspace_root: str) -> str:
    return "python3 -m pytest -q"


def run_pipeline(
    workflow_id: str,
    changed_python_files: list[str],
    test_command: str = "",
    build_command: str = "",
    lint_enabled: bool = True,
    security_check_enabled: bool = True,
) -> list[StageResult]:
    workspace = workspace_path(workflow_id)
    stages: list[StageResult] = []

    # 1. Syntax/compile check (Python files only; documented limitation for
    # other languages).
    for f in changed_python_files:
        if f.endswith(".py"):
            res = run_command(workspace, f"python3 -m py_compile {f}")
            stages.append(StageResult(stage="syntax", result=res))
            if res.status != "passed":
                # Stop early: nothing downstream can meaningfully run.
                return stages

    # 2. Lint
    if lint_enabled:
        res = run_command(workspace, "ruff check .")
        stages.append(StageResult(stage="lint", result=res))

    # 3. Unit tests
    cmd = test_command.strip() or _default_test_command(str(workspace))
    res = run_command(workspace, cmd)
    stages.append(StageResult(stage="unit_tests", result=res))

    # 4. Integration tests: this demo project does not separate
    # integration tests from the unit test run; documented as a
    # configuration option (a distinct `INTEGRATION_TEST_COMMAND` would
    # be added here if the target repository defines one).

    # 5. Build
    if build_command.strip():
        res = run_command(workspace, build_command.strip())
        stages.append(StageResult(stage="build", result=res))

    # 6. Optional security/static checks (Ruff's flake8-bandit-derived "S"
    # rule set - a real static check, not a simulated one).
    if security_check_enabled:
        res = run_command(workspace, "ruff check --select S .")
        stages.append(StageResult(stage="security", result=res))

    return stages


def overall_status(stages: list[StageResult]) -> str:
    if not stages:
        return "error"
    if all(s.result.status == "passed" for s in stages if s.stage in ("syntax", "unit_tests")):
        return "passed"
    return "failed"
