"""COST category guardrail tests (COST-01..COST-07)."""
from __future__ import annotations

from app.core.config import settings
from app.models.enums import GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_cost01_token_budget_exceeded_warns():
    exceeded = guardrails.check_llm_token_limit("planning", settings.max_llm_estimated_tokens_per_workflow + 1)
    assert exceeded.status == GuardrailStatus.WARNING.value

    ok = guardrails.check_llm_token_limit("planning", 100)
    assert ok.status == GuardrailStatus.PASSED.value


def test_cost02_call_budget_exceeded_warns():
    exceeded = guardrails.check_llm_call_limit("planning", settings.max_llm_calls_per_workflow + 1)
    assert exceeded.status == GuardrailStatus.WARNING.value

    ok = guardrails.check_llm_call_limit("planning", 1)
    assert ok.status == GuardrailStatus.PASSED.value


def test_cost03_repair_loop_cost_limit():
    exceeded = guardrails.check_repair_loop_limit("repair", settings.max_repair_attempts)
    assert exceeded.status == GuardrailStatus.BLOCKED.value

    ok = guardrails.check_repair_loop_limit("repair", 0)
    assert ok.status == GuardrailStatus.PASSED.value


def test_cost04_model_escalation_guard():
    escalated = guardrails.check_model_escalation("codegen", "claude-sonnet-5", "claude-opus-5")
    assert escalated.status == GuardrailStatus.WARNING.value

    same = guardrails.check_model_escalation("codegen", "claude-sonnet-5", "claude-sonnet-5")
    assert same.status == GuardrailStatus.PASSED.value


def test_cost05_infrastructure_cost_warning():
    result = guardrails.check_infrastructure_cost_warning("codegen", {"docker-compose.yml": "replicas: 20"})
    assert result.status == GuardrailStatus.WARNING.value

    na = guardrails.check_infrastructure_cost_warning("codegen", {})
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value


def test_cost06_ci_cost_awareness():
    excessive = guardrails.check_ci_cost_awareness("repair", 3, settings.max_repair_attempts + 5)
    assert excessive.status == GuardrailStatus.WARNING.value

    ok = guardrails.check_ci_cost_awareness("repair", 0, 1)
    assert ok.status == GuardrailStatus.PASSED.value


def test_cost07_workflow_budget_exceeded_requires_approval():
    exceeded = guardrails.check_workflow_budget("planning", settings.workflow_cost_budget_usd + 1)
    assert exceeded.status == GuardrailStatus.WARNING.value
    assert exceeded.action == "REQUIRE_APPROVAL"


def test_cost07_workflow_budget_warning_near_threshold():
    near = guardrails.check_workflow_budget("planning", settings.workflow_cost_budget_usd * 0.85)
    assert near.status == GuardrailStatus.WARNING.value
    assert near.action == "WARN"

    ok = guardrails.check_workflow_budget("planning", 0.0)
    assert ok.status == GuardrailStatus.PASSED.value
