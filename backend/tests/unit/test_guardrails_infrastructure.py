"""INFRASTRUCTURE category guardrail tests (INFRA-01..INFRA-06)."""
from __future__ import annotations

from app.core.config import settings
from app.models.enums import GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_infra01_detects_infrastructure_modification():
    triggered = guardrails.check_infrastructure_change_detection("codegen", ["backend/Dockerfile"])
    assert triggered.status == GuardrailStatus.WARNING.value

    na = guardrails.check_infrastructure_change_detection("codegen", ["src/auth/service.py"])
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value


def test_infra02_dependency_check():
    result = guardrails.check_infrastructure_dependency("codegen", ["src/api/app.py"])
    assert result.status == GuardrailStatus.WARNING.value
    empty = guardrails.check_infrastructure_dependency("codegen", [])
    assert empty.status == GuardrailStatus.PASSED.value


def test_infra03_resource_limit_check():
    missing = guardrails.check_resource_limits("codegen", {"docker-compose.yml": "services:\n  api:\n    image: x\n"})
    assert missing.status == GuardrailStatus.WARNING.value

    present = guardrails.check_resource_limits("codegen", {"docker-compose.yml": "services:\n  api:\n    resources:\n      limits:\n        cpus: '1'\n"})
    assert present.status == GuardrailStatus.PASSED.value

    na = guardrails.check_resource_limits("codegen", {})
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value


def test_infra04_environment_isolation_blocks_production():
    blocked = guardrails.check_environment_isolation("workflow_creation", "production")
    assert blocked.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_environment_isolation("workflow_creation", "sandbox")
    assert ok.status == GuardrailStatus.PASSED.value


def test_infra05_configuration_drift_warning():
    result = guardrails.check_configuration_drift("codegen", [".env.production"])
    assert result.status == GuardrailStatus.WARNING.value


def test_infra06_high_blast_radius_requires_approval():
    many = [f"file_{i}.py" for i in range(settings.max_blast_radius_files + 5)]
    warn = guardrails.check_infrastructure_blast_radius("codegen", many, [], [])
    assert warn.status == GuardrailStatus.WARNING.value
    assert warn.action == "REQUIRE_APPROVAL"

    ok = guardrails.check_infrastructure_blast_radius("codegen", ["a.py"], [], [])
    assert ok.status == GuardrailStatus.PASSED.value
