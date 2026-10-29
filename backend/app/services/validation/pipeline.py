"""Configurable validation pipeline (master spec §16):

1. Syntax/compile check
2. Lint
3. Unit tests
4. Integration tests (if available/configured)
5. Build (if a build command is configured)
6. Optional security/static checks
   (+ production verification: the built app is started the way it ships
   and tested live — see app/services/validation/production.py)
7. (Final regression validation is just re-running the same pipeline
   after a repair — see app/services/validation/repair.py)
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
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

    unit_tests_passed = res.status == "passed"

    # 5b. Container image build: every project ships a Dockerfile; build it
    # when a Docker engine is available, otherwise record why it was skipped
    # (CI builds it on GitHub either way).
    image = ""
    if settings.docker_validation and (workspace / "Dockerfile").is_file():
        from app.services.validation.sandbox import docker_available

        tag = "i2d-validate-" + "".join(ch for ch in workflow_id.lower() if ch.isalnum())[:24]
        available, detail = docker_available()
        if available:
            res = run_command(workspace, f"docker build -t {tag} .", timeout=settings.docker_build_timeout_seconds)
            image = tag if res.status == "passed" else ""
        else:
            res = CommandResult(command=f"docker build -t {tag} .", exit_code=None,
                                stdout=f"Skipped: {detail} The image is built by CI on GitHub.", stderr="",
                                duration_ms=0, skipped=True)
        stages.append(StageResult(stage="docker_build", result=res))

    # 5c. Production verification: boot the app the way it ships (its image
    # when built, else its production server command) and test it live.
    if settings.production_validation:
        from app.services.validation import production

        reason = "" if unit_tests_passed else "Unit tests failed; the running service is tested once they pass."
        for stage, result in production.run(workspace, image=image, skip_reason=reason):
            stages.append(StageResult(stage=stage, result=result))

    # 6. Optional security/static checks (Ruff's flake8-bandit-derived "S"
    # rule set - a real static check, not a simulated one).
    if security_check_enabled:
        res = run_command(workspace, "ruff check --select S .")
        stages.append(StageResult(stage="security", result=res))

    return stages


def overall_status(stages: list[StageResult]) -> str:
    if not stages:
        return "error"
    gating = ("syntax", "unit_tests", "docker_build")
    if all(s.result.status in ("passed", "skipped") for s in stages if s.stage in gating or s.stage.startswith("prod_")):
        return "passed"
    return "failed"
