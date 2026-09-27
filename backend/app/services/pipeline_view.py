"""Builds the Part A2 pipeline visualization from real persisted workflow
state. Every field is derived from an actual database row — never a
fabricated status. Stage statuses use `PipelineStageStatus` (Part A2):
PENDING, RUNNING, PASSED, FAILED, BLOCKED, AWAITING_APPROVAL, SKIPPED,
NOT_APPLICABLE.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.models.enums import WorkflowState
from app.models.models import (
    ChaosExperiment,
    GeneratedTest,
    GitOperation,
    GuardrailCheck,
    Plan,
    ProductionReadinessAssessment,
    ProposedChange,
    RepairAttempt,
    Repository,
    RetrievedDocument,
    RiskItem,
    ValidationResult,
    Workflow,
)
from app.services.github import github_ops


def _stage(
    name: str,
    status: str,
    *,
    timestamp: str | None = None,
    duration_ms: int | None = None,
    input_: str = "",
    output: str = "",
    evidence: list[str] | None = None,
    approval_state: str | None = None,
    guardrails_triggered: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "status": status,
        "timestamp": timestamp,
        "duration_ms": duration_ms,
        "input": input_,
        "output": output,
        "evidence": evidence or [],
        "approval_state": approval_state,
        "guardrails_triggered": guardrails_triggered or [],
    }


def build_pipeline(session: Session, workflow_id: str) -> dict:
    from app.services.orchestrator import OrchestratorError

    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise OrchestratorError(f"Workflow '{workflow_id}' not found.")

    repository = session.get(Repository, workflow.repository_id)
    plan = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    evidence_rows = session.exec(select(RetrievedDocument).where(RetrievedDocument.workflow_id == workflow_id)).all()
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    tests = session.exec(select(GeneratedTest).where(GeneratedTest.workflow_id == workflow_id)).all()
    validations = session.exec(select(ValidationResult).where(ValidationResult.workflow_id == workflow_id)).all()
    repairs = session.exec(select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id)).all()
    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    chaos = session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id)).all()
    readiness = session.exec(
        select(ProductionReadinessAssessment).where(ProductionReadinessAssessment.workflow_id == workflow_id).order_by(ProductionReadinessAssessment.created_at.desc())
    ).first()
    git_ops_rows = session.exec(select(GitOperation).where(GitOperation.workflow_id == workflow_id)).all()
    guardrail_checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id)).all()

    def guardrails_for(checkpoint_prefix: str) -> list[dict]:
        return [
            {"guardrail_id": g.guardrail_id, "name": g.name, "status": g.status}
            for g in guardrail_checks
            if g.enforcement_point.startswith(checkpoint_prefix)
        ]

    stages: list[dict] = []

    stages.append(
        _stage(
            "Developer Intent",
            "PASSED",
            timestamp=workflow.created_at.isoformat(),
            input_=workflow.intent,
            output=workflow.intent,
        )
    )

    if plan is not None:
        stages.append(
            _stage(
                "Intent Understanding",
                "PASSED",
                timestamp=plan.created_at.isoformat(),
                duration_ms=workflow.planning_ms,
                input_=workflow.intent,
                output=plan.summary,
            )
        )
    else:
        stages.append(_stage("Intent Understanding", "RUNNING" if workflow.state == WorkflowState.PLANNING else "PENDING"))

    stages.append(
        _stage(
            "Production Context",
            "PASSED" if any(g.guardrail_id == "DEPLOY-02" and g.status == "PASSED" for g in guardrail_checks) else "BLOCKED" if any(g.guardrail_id == "DEPLOY-02" and g.status == "BLOCKED" for g in guardrail_checks) else "PENDING",
            output=f"environment={workflow.environment.value}",
            guardrails_triggered=guardrails_for("workflow_creation"),
        )
    )

    if evidence_rows:
        stages.append(
            _stage(
                "Repository RAG",
                "PASSED",
                duration_ms=workflow.retrieval_ms,
                input_=workflow.intent,
                output=f"{len(evidence_rows)} evidence chunk(s) retrieved",
                evidence=[f"{e.file}:{e.start_line}-{e.end_line}" for e in evidence_rows[:10]],
            )
        )
    else:
        stages.append(_stage("Repository RAG", "PASSED" if repository and repository.indexed_at else "PENDING"))

    stages.append(
        _stage(
            "Architecture Analysis",
            "PASSED" if repository and repository.indexed_at else "PENDING",
            output="Available on demand via /architecture" if repository and repository.indexed_at else "",
        )
    )

    if risks:
        open_critical = sum(1 for r in risks if r.severity == "CRITICAL" and r.status == "OPEN")
        stages.append(
            _stage(
                "Risk Analysis",
                "FAILED" if open_critical else "PASSED",
                output=f"{len(risks)} risk(s) identified, {open_critical} open CRITICAL",
                evidence=[r.title for r in risks[:5]],
                guardrails_triggered=guardrails_for("risk_analysis"),
            )
        )
    else:
        stages.append(_stage("Risk Analysis", "PENDING" if plan else "PENDING"))

    if plan is not None:
        if plan.approved is True:
            plan_status = "PASSED"
        elif plan.approved is False:
            plan_status = "FAILED"
        elif workflow.state == WorkflowState.AWAITING_PLAN_APPROVAL:
            plan_status = "AWAITING_APPROVAL"
        else:
            plan_status = "PENDING"
        stages.append(
            _stage(
                "Engineering Plan",
                plan_status,
                output=plan.summary,
                approval_state="approved" if plan.approved else ("rejected" if plan.approved is False else "pending"),
                guardrails_triggered=guardrails_for("planning"),
            )
        )
    else:
        stages.append(_stage("Engineering Plan", "PENDING"))

    approval_events = [g for g in guardrail_checks if g.guardrail_id == "DEPLOY-03"]
    if approval_events:
        last = approval_events[-1]
        stages.append(
            _stage(
                "Human Approval",
                "PASSED" if last.status == "PASSED" else "BLOCKED",
                output=last.trigger_condition,
                guardrails_triggered=[{"guardrail_id": g.guardrail_id, "name": g.name, "status": g.status} for g in approval_events],
            )
        )
    else:
        stages.append(_stage("Human Approval", "PENDING"))

    if changes:
        blocked_codegen = [g for g in guardrail_checks if g.enforcement_point == "codegen" and g.status == "BLOCKED"]
        stages.append(
            _stage(
                "Code Generation",
                "BLOCKED" if blocked_codegen else "PASSED",
                duration_ms=workflow.codegen_ms,
                output=f"{len(changes)} file(s) changed: {', '.join(c.file for c in changes)}",
                guardrails_triggered=guardrails_for("codegen"),
            )
        )
    else:
        stages.append(_stage("Code Generation", "BLOCKED" if any(g.enforcement_point == "codegen" and g.status == "BLOCKED" for g in guardrail_checks) else "PENDING"))

    stages.append(
        _stage(
            "Test Generation",
            "PASSED" if tests else "PENDING",
            duration_ms=workflow.testgen_ms,
            output=f"{len(tests)} test(s) generated" if tests else "",
        )
    )

    applicable_chaos = [c for c in chaos if c.result != "NOT_APPLICABLE"]
    stages.append(
        _stage(
            "Resilience Testing",
            "PASSED" if applicable_chaos and all(c.result == "PASSED" for c in applicable_chaos) else ("FAILED" if applicable_chaos else "PENDING"),
            output=f"{len(applicable_chaos)} applicable experiment(s)" if chaos else "",
        )
    )
    stages.append(
        _stage(
            "Chaos Simulation",
            "PASSED" if applicable_chaos and all(c.result == "PASSED" for c in applicable_chaos) else ("FAILED" if applicable_chaos else "NOT_APPLICABLE" if chaos else "PENDING"),
            output=f"{sum(1 for c in chaos if c.result == 'PASSED')}/{len(applicable_chaos)} passed" if applicable_chaos else "",
            evidence=[f"{c.experiment_id}: {c.fault} -> {c.result}" for c in chaos[:6]],
        )
    )

    if validations:
        max_attempt = max(v.attempt for v in validations)
        latest = [v for v in validations if v.attempt == max_attempt]
        passed = all(v.status == "passed" for v in latest if v.stage in ("syntax", "unit_tests"))
        stages.append(
            _stage(
                "Validation",
                "PASSED" if passed else "FAILED",
                duration_ms=workflow.validation_ms,
                output=", ".join(f"{v.stage}={v.status}" for v in latest),
                guardrails_triggered=guardrails_for("validation"),
            )
        )
    else:
        stages.append(_stage("Validation", "RUNNING" if workflow.state == WorkflowState.VALIDATING else "PENDING"))

    if repairs:
        stages.append(
            _stage(
                "AI Repair",
                "PASSED" if any(r.result == "passed" for r in repairs) else "FAILED",
                output=f"{len(repairs)} repair attempt(s)",
                guardrails_triggered=guardrails_for("repair"),
            )
        )
    else:
        stages.append(_stage("AI Repair", "SKIPPED"))

    if readiness is not None:
        stages.append(
            _stage(
                "Production Readiness",
                {"READY": "PASSED", "READY_WITH_WARNINGS": "PASSED", "NOT_READY": "BLOCKED"}[readiness.decision],
                output=readiness.decision,
                evidence=json.loads(readiness.reasons_json),
            )
        )
    else:
        stages.append(_stage("Production Readiness", "PENDING"))

    ci_event = next((g for g in reversed(guardrail_checks) if g.guardrail_id == "CICD-01"), None)
    if ci_event:
        stages.append(_stage("CI/CD", "PASSED" if ci_event.status == "PASSED" else "FAILED", output=ci_event.trigger_condition))
    elif not github_ops.is_configured():
        stages.append(_stage("CI/CD", "NOT_APPLICABLE", output="NOT_CONFIGURED — GITHUB_TOKEN/OWNER/REPO not set"))
    else:
        stages.append(_stage("CI/CD", "PENDING"))

    pr_ops = [g for g in git_ops_rows if g.operation in ("push", "pr_created")]
    stages.append(
        _stage(
            "GitHub / PR",
            "PASSED" if pr_ops else ("NOT_APPLICABLE" if not github_ops.is_configured() else "PENDING"),
            output="; ".join(f"{g.operation}: {g.detail}" for g in pr_ops),
        )
    )

    stages.append(_stage("Final Report", "PASSED" if workflow.state == WorkflowState.COMPLETED else "PENDING"))

    return {"workflow_id": workflow_id, "stages": stages}
