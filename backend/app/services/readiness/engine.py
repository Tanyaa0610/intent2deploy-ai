"""Production readiness gate (Guardrail 18 / Part K decision).

A workflow is never marked READY merely because its tests passed. This
composite evaluates functional correctness, regression safety, guardrail
outcomes, open risk severity, resilience/chaos results, and rollback
posture, and always returns an explicit list of reasons alongside the
decision — never a bare label.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReadinessInput:
    validation_passed: bool | None
    blocked_guardrails: list[str]  # guardrail names currently BLOCKED
    warning_guardrails: list[str]  # guardrail names currently WARNING
    open_critical_risks: int
    open_high_risks: int
    chaos_pass_rate: float | None
    rollback_status: str  # PASSED | WARNING | BLOCKED | NOT_APPLICABLE
    ci_passed: bool | None
    cost_status: str = "NOT_APPLICABLE"  # PASSED | WARNING | NOT_APPLICABLE


@dataclass
class ReadinessAssessment:
    decision: str  # READY | READY_WITH_WARNINGS | NOT_READY
    reasons: list[str]
    checklist: dict[str, str]


def assess(inp: ReadinessInput) -> ReadinessAssessment:
    reasons: list[str] = []
    checklist: dict[str, str] = {}

    checklist["functional_correctness"] = "PASSED" if inp.validation_passed else ("FAILED" if inp.validation_passed is False else "UNKNOWN")
    checklist["ci"] = "PASSED" if inp.ci_passed else ("FAILED" if inp.ci_passed is False else "UNKNOWN")
    checklist["regression_safety"] = "BLOCKED" if "Regression Gate" in inp.blocked_guardrails else "PASSED"
    checklist["security"] = "BLOCKED" if "Secret Detection" in inp.blocked_guardrails else "PASSED"
    checklist["resilience"] = (
        "UNKNOWN" if inp.chaos_pass_rate is None else ("PASSED" if inp.chaos_pass_rate >= 0.99 else "WARNING" if inp.chaos_pass_rate >= 0.5 else "FAILED")
    )
    checklist["rollback"] = inp.rollback_status
    checklist["open_risk"] = "CRITICAL" if inp.open_critical_risks else ("HIGH" if inp.open_high_risks else "NONE")
    checklist["cost"] = inp.cost_status

    hard_block = False
    if inp.validation_passed is False:
        reasons.append("Validation did not pass: functional correctness is not established.")
        hard_block = True
    if inp.blocked_guardrails:
        reasons.append(f"Blocking guardrail(s) triggered: {', '.join(inp.blocked_guardrails)}.")
        hard_block = True
    if inp.open_critical_risks:
        reasons.append(f"{inp.open_critical_risks} open CRITICAL risk(s) remain unmitigated.")
        hard_block = True
    if inp.ci_passed is False:
        reasons.append("Required CI checks did not pass.")
        hard_block = True

    if hard_block:
        return ReadinessAssessment(decision="NOT_READY", reasons=reasons, checklist=checklist)

    warnings: list[str] = []
    if inp.warning_guardrails:
        warnings.append(f"Guardrail warning(s) outstanding: {', '.join(inp.warning_guardrails)}.")
    if inp.open_high_risks:
        warnings.append(f"{inp.open_high_risks} open HIGH risk(s) remain — mitigated or accepted before release recommended.")
    if inp.chaos_pass_rate is not None and inp.chaos_pass_rate < 0.99:
        warnings.append(f"Resilience/chaos pass rate is {inp.chaos_pass_rate * 100:.0f}%, below 100%.")
    if inp.chaos_pass_rate is None:
        warnings.append("No resilience/chaos experiments were applicable or run for this change.")
    if inp.rollback_status in ("WARNING",):
        warnings.append("A HIGH-risk change has no documented rollback strategy.")
    if inp.cost_status == "WARNING":
        warnings.append("Estimated LLM/workflow cost is approaching or over the configured budget.")
    if inp.validation_passed is None:
        warnings.append("Validation has not been run yet.")
    if inp.ci_passed is None:
        warnings.append("CI has not been run or is not configured for this workflow.")

    if warnings:
        return ReadinessAssessment(decision="READY_WITH_WARNINGS", reasons=warnings, checklist=checklist)

    return ReadinessAssessment(decision="READY", reasons=["All functional, regression, security, resilience, CI, and risk checks passed with no open warnings."], checklist=checklist)
