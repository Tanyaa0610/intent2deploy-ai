"""CI/CD category guardrail tests (CICD-01..CICD-08)."""
from __future__ import annotations

from app.models.enums import GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_cicd01_failing_test_blocks_progression():
    blocked = guardrails.check_test_gate("validation", {"lint": "passed", "unit_tests": "failed"})
    assert blocked.status == GuardrailStatus.BLOCKED.value


def test_cicd01_successful_ci_passes():
    ok = guardrails.check_test_gate("validation", {"lint": "passed", "unit_tests": "passed"})
    assert ok.status == GuardrailStatus.PASSED.value


def test_cicd02_regression_gate():
    na = guardrails.check_regression_gate("validation", None, None)
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value

    regressed = guardrails.check_regression_gate("validation", True, False)
    assert regressed.status == GuardrailStatus.BLOCKED.value

    fine = guardrails.check_regression_gate("validation", True, True)
    assert fine.status == GuardrailStatus.PASSED.value


def test_cicd03_build_gate():
    na = guardrails.check_build_gate("validation", False, None)
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value

    ok = guardrails.check_build_gate("validation", True, "passed")
    assert ok.status == GuardrailStatus.PASSED.value

    failed = guardrails.check_build_gate("validation", True, "failed")
    assert failed.status == GuardrailStatus.BLOCKED.value


def test_cicd04_security_scan_gate_blocks_on_findings():
    blocked = guardrails.check_security_scan_gate("validation", "failed", 3)
    assert blocked.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_security_scan_gate("validation", "passed", 0)
    assert ok.status == GuardrailStatus.PASSED.value


def test_cicd05_pipeline_integrity_detects_removed_test_step():
    old = "jobs:\n  test:\n    steps:\n      - run: pytest\n      - run: ruff check .\n"
    new = "jobs:\n  test:\n    steps:\n      - run: ruff check .\n"
    result = guardrails.check_pipeline_integrity("codegen", {".github/workflows/ci.yml": (old, new)})
    assert result.status == GuardrailStatus.BLOCKED.value
    assert result.evidence


def test_cicd06_ci_configuration_protection():
    result = guardrails.check_ci_configuration_protection("codegen", [".github/workflows/ci.yml"])
    assert result.status == GuardrailStatus.WARNING.value


def test_cicd07_failure_gate():
    blocked = guardrails.check_failure_gate("validation", {"lint": "passed", "unit_tests": "failed"})
    assert blocked.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_failure_gate("validation", {"lint": "passed", "unit_tests": "passed"})
    assert ok.status == GuardrailStatus.PASSED.value


def test_cicd08_evidence_gate_never_fabricates():
    real = guardrails.check_ci_evidence_gate("validation", True, "3 stages executed")
    assert real.status == GuardrailStatus.PASSED.value

    fabricated = guardrails.check_ci_evidence_gate("validation", False, "no commands recorded")
    assert fabricated.status == GuardrailStatus.FAILED.value
