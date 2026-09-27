from __future__ import annotations

from app.services.readiness.engine import ReadinessInput, assess


def _base(**overrides) -> ReadinessInput:
    defaults = dict(
        validation_passed=True,
        blocked_guardrails=[],
        warning_guardrails=[],
        open_critical_risks=0,
        open_high_risks=0,
        chaos_pass_rate=1.0,
        rollback_status="NOT_APPLICABLE",
        ci_passed=True,
    )
    defaults.update(overrides)
    return ReadinessInput(**defaults)


def test_all_clean_is_ready():
    result = assess(_base())
    assert result.decision == "READY"
    assert result.reasons


def test_validation_failure_is_not_ready():
    result = assess(_base(validation_passed=False))
    assert result.decision == "NOT_READY"
    assert any("Validation" in r for r in result.reasons)


def test_blocked_guardrail_is_not_ready():
    result = assess(_base(blocked_guardrails=["Secret Protection"]))
    assert result.decision == "NOT_READY"


def test_open_critical_risk_is_not_ready():
    result = assess(_base(open_critical_risks=1))
    assert result.decision == "NOT_READY"


def test_ci_failure_is_not_ready():
    result = assess(_base(ci_passed=False))
    assert result.decision == "NOT_READY"


def test_warning_guardrail_is_ready_with_warnings():
    result = assess(_base(warning_guardrails=["Rollback Gate"]))
    assert result.decision == "READY_WITH_WARNINGS"


def test_open_high_risk_is_ready_with_warnings():
    result = assess(_base(open_high_risks=2))
    assert result.decision == "READY_WITH_WARNINGS"


def test_partial_chaos_pass_rate_is_ready_with_warnings():
    result = assess(_base(chaos_pass_rate=0.5))
    assert result.decision == "READY_WITH_WARNINGS"


def test_decision_always_has_reasons_and_checklist():
    for overrides in ({}, {"validation_passed": False}, {"warning_guardrails": ["x"]}):
        result = assess(_base(**overrides))
        assert result.reasons
        assert result.checklist
