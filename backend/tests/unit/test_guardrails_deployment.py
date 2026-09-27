"""DEPLOYMENT category guardrail tests (DEPLOY-01..DEPLOY-08)."""
from __future__ import annotations

from app.models.enums import GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_deploy01_environment_verification():
    ok = guardrails.check_environment_verification("workflow_creation", "sandbox")
    assert ok.status == GuardrailStatus.PASSED.value

    bad = guardrails.check_environment_verification("workflow_creation", "not-a-real-env")
    assert bad.status == GuardrailStatus.BLOCKED.value


def test_deploy02_production_target_blocked():
    blocked = guardrails.check_production_block("workflow_creation", "production")
    assert blocked.status == GuardrailStatus.BLOCKED.value


def test_deploy02_sandbox_deployment_allowed():
    ok = guardrails.check_production_block("workflow_creation", "sandbox")
    assert ok.status == GuardrailStatus.PASSED.value


def test_deploy03_deployment_approval():
    approved = guardrails.check_deployment_approval("commit", True, "looks good")
    assert approved.status == GuardrailStatus.PASSED.value

    declined = guardrails.check_deployment_approval("commit", False)
    assert declined.status == GuardrailStatus.BLOCKED.value


def test_deploy04_rollback_requirement():
    na = guardrails.check_rollback_requirement("risk_analysis", "LOW", "some plan")
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value

    blocked = guardrails.check_rollback_requirement("risk_analysis", "CRITICAL", "no mitigation discussed")
    assert blocked.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_rollback_requirement("risk_analysis", "HIGH", "includes a rollback strategy")
    assert ok.status == GuardrailStatus.PASSED.value


def test_deploy05_health_check_gate():
    present = guardrails.check_health_check_gate("codegen", {"app.py": '@app.get("/health")\ndef health(): return {"ok": True}'})
    assert present.status == GuardrailStatus.PASSED.value

    missing = guardrails.check_health_check_gate("codegen", {"app.py": "def foo(): pass"})
    assert missing.status == GuardrailStatus.WARNING.value


def test_deploy06_migration_safety():
    triggered = guardrails.check_migration_safety("codegen", ["migrations/0001_init.sql"])
    assert triggered.status == GuardrailStatus.WARNING.value
    assert triggered.severity == "CRITICAL"

    na = guardrails.check_migration_safety("codegen", ["src/auth/service.py"])
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value


def test_deploy07_deployment_scope():
    blocked = guardrails.check_deployment_scope("commit", ["src/a.py"], ["src/a.py", "src/b.py"])
    assert blocked.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_deployment_scope("commit", ["src/a.py"], ["src/a.py"])
    assert ok.status == GuardrailStatus.PASSED.value


def test_deploy08_deployment_evidence_is_recorded():
    result = guardrails.check_deployment_evidence("commit", "sandbox", "abc123", "intent2deploy/wf1", "unknown")
    assert result.status == GuardrailStatus.PASSED.value
    assert any("commit=abc123" in e for e in result.evidence)
