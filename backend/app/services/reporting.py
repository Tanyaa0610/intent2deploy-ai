"""Final report assembly (master spec §7, §32).

Deterministically assembles the full workflow trace from persisted data
(never re-derives or fabricates anything), then asks the LLM provider for
a short prose executive summary of that trace via the
`final_report_generation` prompt.

This module is the SINGLE SOURCE OF TRUTH for the Final Report: the UI
report tab, the downloadable JSON artifact, and the downloadable Markdown
artifact are all built from the one `build_report()` trace below —
`report_to_markdown()` only re-renders that same trace as text, it never
re-queries the database. A value that is not actually persisted is
reported as the literal string "Not recorded" (or an empty list/null,
where a list/null is the more natural shape) rather than guessed.

Backward compatibility: every key that existed in the trace before this
module was expanded (workflow_id, intent, final_status, repository, plan,
evidence, changes, tests, validation_results, final_validation,
repair_attempts, repairs, human_intervention_count, change_approvals,
git_operations, audit_trail, risks, guardrails, production_readiness,
evidence_classification, timing_ms, executive_summary) keeps its exact
prior shape and computation — see test_report_evidence_classification.py
and test_orchestrator_e2e.py. Everything else below is additive.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.models.models import (
    AuditEvent,
    ChangeApprovalRecord,
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
)
from app.services.github import github_ops
from app.services.orchestrator import get_architecture, get_workflow
from app.services.pipeline_view import build_pipeline
from app.services.planner.intent_classifier import classify_intent
from app.services.providers.factory import get_provider

REPORT_VERSION = "2.0"

NOT_RECORDED = "Not recorded"


def _classify_evidence(plan: Plan | None, evidence: list, invented_files_removed: list[str]) -> list[dict]:
    """Deterministic, non-fabricated evidence classification (Part 14): every
    entry here is derived from a real persisted fact — nothing is invented
    to fill out the FACT/INFERRED/ASSUMPTION/UNKNOWN/UNVERIFIED taxonomy."""
    items: list[dict] = [
        {
            "item": "Developer intent",
            "classification": "FACT",
            "note": "Exact text submitted by the developer; not paraphrased.",
        }
    ]
    for e in evidence[:8]:
        items.append(
            {
                "item": f"{e.file}:{e.start_line}-{e.end_line}",
                "classification": "FACT",
                "note": f"Real repository retrieval result (score={e.score:.2f}, method={e.retrieval_method}).",
            }
        )
    if plan is not None:
        items.append({"item": "Plan summary & steps", "classification": "INFERRED", "note": "Derived by the LLM from the retrieval evidence above, not a literal repository fact."})
        for a in json.loads(plan.assumptions_json):
            items.append({"item": a, "classification": "ASSUMPTION", "note": "Stated assumption in the generated plan; not independently verified against the repository."})
        risks = json.loads(plan.risks_json)
        if not risks:
            items.append({"item": "Risk assessment", "classification": "UNKNOWN", "note": "The plan stated no risks — treated as UNKNOWN, never silently read as 'low risk'."})
    for f in invented_files_removed:
        items.append({"item": f, "classification": "UNVERIFIED", "note": "Referenced by the LLM but absent from retrieval evidence; stripped from the grounded plan before use."})
    return items


def _extract_test_function_names(content: str) -> list[str]:
    return re.findall(r"^\s*def (test_\w+)\(", content, re.M)


def build_report(session: Session, workflow_id: str, include_executive_summary: bool = True) -> dict:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    plan = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    tests = session.exec(select(GeneratedTest).where(GeneratedTest.workflow_id == workflow_id)).all()
    validations = session.exec(select(ValidationResult).where(ValidationResult.workflow_id == workflow_id).order_by(ValidationResult.timestamp)).all()
    repairs = session.exec(select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id).order_by(RepairAttempt.created_at)).all()
    evidence = session.exec(select(RetrievedDocument).where(RetrievedDocument.workflow_id == workflow_id)).all()
    events = session.exec(select(AuditEvent).where(AuditEvent.workflow_id == workflow_id).order_by(AuditEvent.timestamp)).all()
    git_ops_rows = session.exec(select(GitOperation).where(GitOperation.workflow_id == workflow_id).order_by(GitOperation.timestamp)).all()
    change_approvals = session.exec(select(ChangeApprovalRecord).where(ChangeApprovalRecord.workflow_id == workflow_id).order_by(ChangeApprovalRecord.timestamp)).all()
    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    guardrail_checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id).order_by(GuardrailCheck.evaluated_at)).all()
    chaos_rows = session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id).order_by(ChaosExperiment.timestamp)).all()
    readiness = session.exec(
        select(ProductionReadinessAssessment)
        .where(ProductionReadinessAssessment.workflow_id == workflow_id)
        .order_by(ProductionReadinessAssessment.created_at.desc())
    ).first()

    invented_files_removed: list[str] = []
    for e in events:
        if e.event_type == "PLAN_GENERATED":
            invented_files_removed = json.loads(e.metadata_json).get("invented_files_removed", [])
            break

    final_validation = None
    if validations:
        max_attempt = max(v.attempt for v in validations)
        latest = [v for v in validations if v.attempt == max_attempt]
        final_validation = "passed" if all(v.status == "passed" for v in latest if v.stage in ("syntax", "unit_tests")) else "failed"

    # ---- single trace object: every section below reads from the same
    # already-queried rows, never a second independent query path. ----
    trace: dict = {
        "workflow_id": workflow.id,
        "intent": workflow.intent,
        "final_status": workflow.state.value,
        "repository": repository.source if repository else "",
        "plan": {
            "summary": plan.summary,
            "acceptance_criteria": json.loads(plan.acceptance_criteria_json),
            "steps": json.loads(plan.steps_json),
            "risks": json.loads(plan.risks_json),
            "approved": plan.approved,
        }
        if plan
        else None,
        "evidence": [
            {"file": e.file, "start_line": e.start_line, "end_line": e.end_line, "score": e.score, "reason": e.reason}
            for e in evidence
        ],
        "changes": [
            {"file": c.file, "operation": c.operation, "reason": c.reason, "confidence": c.confidence}
            for c in changes
        ],
        "tests": [{"file": t.file, "rationale": t.rationale, "category": t.category} for t in tests],
        "validation_results": [
            {"stage": v.stage, "status": v.status, "attempt": v.attempt, "duration_ms": v.duration_ms}
            for v in validations
        ],
        "final_validation": final_validation,
        "repair_attempts": workflow.repair_attempts,
        "repairs": [{"attempt_number": r.attempt_number, "diagnosis": r.diagnosis, "result": r.result} for r in repairs],
        "human_intervention_count": workflow.human_intervention_count,
        "change_approvals": [{"approved": a.approved, "comment": a.comment} for a in change_approvals],
        "git_operations": [{"operation": g.operation, "detail": g.detail, "ref": g.ref} for g in git_ops_rows],
        "audit_trail": [{"event_type": e.event_type, "stage": e.stage, "timestamp": e.timestamp.isoformat()} for e in events],
        "risks": [
            {
                "risk_id": r.risk_id,
                "title": r.title,
                "component": r.component,
                "severity": r.severity,
                "status": r.status,
                "source": r.source,
            }
            for r in risks
        ],
        "guardrails": {
            "total": len(guardrail_checks),
            "passed": sum(1 for g in guardrail_checks if g.status == "PASSED"),
            "warnings": sum(1 for g in guardrail_checks if g.status == "WARNING"),
            "blocked": sum(1 for g in guardrail_checks if g.status == "BLOCKED"),
            "failed": sum(1 for g in guardrail_checks if g.status == "FAILED"),
            "by_category": {
                cat: sum(1 for g in guardrail_checks if g.category == cat)
                for cat in sorted({g.category for g in guardrail_checks})
            },
            "blocking": [
                {"guardrail_id": g.guardrail_id, "name": g.name, "category": g.category, "reason": g.trigger_condition}
                for g in guardrail_checks
                if g.status in ("BLOCKED", "FAILED")
            ],
        },
        "production_readiness": {
            "decision": readiness.decision,
            "reasons": json.loads(readiness.reasons_json),
        }
        if readiness
        else None,
        "evidence_classification": _classify_evidence(plan, evidence, invented_files_removed),
        "invented_files_removed": invented_files_removed,
        "timing_ms": {
            "indexing": workflow.indexing_ms,
            "retrieval": workflow.retrieval_ms,
            "planning": workflow.planning_ms,
            "codegen": workflow.codegen_ms,
            "testgen": workflow.testgen_ms,
            "validation": workflow.validation_ms,
            "total": workflow.total_ms,
        },
    }

    # The executive summary is the one non-deterministic (LLM-backed) part
    # of this trace. Callers that only need deterministic, persisted
    # evidence (e.g. the workflow evaluation endpoint) can skip it via
    # include_executive_summary=False to avoid an LLM round-trip on every
    # request — `is_mock` itself is free (provider construction only).
    provider = get_provider()
    is_mock = provider.is_mock
    if include_executive_summary:
        try:
            prompt = load_prompt("final_report_generation")
            rendered = prompt.render(workflow_trace_json=json.dumps(trace)[:8000])
            from pydantic import BaseModel

            class _Summary(BaseModel):
                executive_summary: str

            result = structured_call(
                provider, "final_report_generation", rendered, {"workflow_trace": trace}, schema=_Summary
            )
            trace["executive_summary"] = result.parsed.executive_summary
        except Exception as exc:  # noqa: BLE001 - report generation must never crash on summary failure
            trace["executive_summary"] = f"(executive summary unavailable: {exc})"
    else:
        trace["executive_summary"] = None

    # =====================================================================
    # Expanded, auditable sections — all derived from the rows queried
    # above (or one additional read-only, non-persisted call each to
    # get_architecture()/build_pipeline(), themselves already-existing
    # deterministic evidence builders). No second tracking system.
    # =====================================================================

    report_type = "intent2deploy_workflow_report"
    generated_at = datetime.now(timezone.utc).isoformat()

    trace["report_metadata"] = {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "workflow_id": workflow.id,
        "project_id": workflow.project_id,
        "status": workflow.state.value,
        "report_type": report_type,
    }

    # ---- 2. Developer intent -------------------------------------------
    trace["developer_intent"] = {
        "text": workflow.intent,
        "submitted_at": workflow.created_at.isoformat(),
        "base_branch": workflow.base_branch or NOT_RECORDED,
        "test_command": workflow.test_command or NOT_RECORDED,
        "build_command": workflow.build_command or NOT_RECORDED,
        "environment": workflow.environment.value,
    }

    # ---- 3. Intent understanding ----------------------------------------
    # classify_intent() is the same pure, deterministic function the mock
    # provider itself uses to pick a code-generation strategy — calling it
    # here is a read of the already-persisted `workflow.intent` text, not
    # a new source of truth. It only reflects reality in mock mode; a live
    # LLM provider reads the intent directly and never produces this label.
    if is_mock:
        category = classify_intent(workflow.intent)
        trace["intent_understanding"] = {
            "classified_category": category,
            "classification_method": "deterministic mock-mode intent classifier (app/services/planner/intent_classifier.py)",
            "confidence": NOT_RECORDED,
            "note": "Category label applies only to LLM_MODE=mock, which selects one of a bounded set of real code-generation strategies by this label. A live LLM provider interprets the intent directly and does not persist a category.",
            "interpreted_problem": plan.summary if plan else NOT_RECORDED,
        }
    else:
        trace["intent_understanding"] = {
            "classified_category": NOT_RECORDED,
            "classification_method": NOT_RECORDED,
            "confidence": NOT_RECORDED,
            "note": "LLM_MODE is not mock (or provider mode could not be determined) — no deterministic category label is computed for live-LLM runs.",
            "interpreted_problem": plan.summary if plan else NOT_RECORDED,
        }

    # ---- 4/5. Production context & repository indexing -------------------
    if repository:
        trace["production_context"] = {
            "repository_source": repository.source,
            "repository_local_path": repository.local_path,
            "environment": workflow.environment.value,
            "file_count": repository.file_count,
            "chunk_count": repository.chunk_count,
            "indexed_at": repository.indexed_at.isoformat() if repository.indexed_at else None,
        }
        trace["repository_indexing"] = {
            "status": "indexed" if repository.indexed_at else "not indexed",
            "files_indexed": repository.file_count,
            "chunks_created": repository.chunk_count,
            "vector_store": repository.collection_name or NOT_RECORDED,
            "indexing_duration_ms": workflow.indexing_ms,
            "indexed_at": repository.indexed_at.isoformat() if repository.indexed_at else None,
            "warnings": [],
        }
    else:
        trace["production_context"] = {"repository_source": NOT_RECORDED, "repository_local_path": NOT_RECORDED, "environment": workflow.environment.value, "file_count": None, "chunk_count": None, "indexed_at": None}
        trace["repository_indexing"] = {"status": NOT_RECORDED, "files_indexed": None, "chunks_created": None, "vector_store": NOT_RECORDED, "indexing_duration_ms": workflow.indexing_ms, "indexed_at": None, "warnings": []}

    # ---- 6. Repository RAG / retrieval -----------------------------------
    trace["retrieval_evidence"] = [
        {
            "file": e.file,
            "start_line": e.start_line,
            "end_line": e.end_line,
            "score": e.score,
            "reason": e.reason,
            "chunk_type": e.chunk_type,
            "symbol": e.symbol,
            "retrieval_method": e.retrieval_method,
            "content_preview": e.content_preview,
        }
        for e in evidence
    ]
    trace["repository_rag"] = {
        "query": workflow.intent,
        "retrieval_duration_ms": workflow.retrieval_ms,
        "files_retrieved": sorted({e.file for e in evidence}),
        "chunk_count_retrieved": len(evidence),
        "evidence": trace["retrieval_evidence"],
        "limitations": [] if evidence else ["No retrieval evidence is persisted for this workflow."],
    }

    # ---- 7. Architecture analysis ----------------------------------------
    try:
        trace["architecture_analysis"] = get_architecture(session, workflow_id)
    except Exception as exc:  # noqa: BLE001 - architecture is best-effort filesystem evidence
        trace["architecture_analysis"] = {"error": NOT_RECORDED, "detail": str(exc)}

    # ---- 8. Risk analysis (full RiskItem fields) -------------------------
    trace["risk_analysis"] = [
        {
            "risk_id": r.risk_id,
            "title": r.title,
            "component": r.component,
            "category": r.component or NOT_RECORDED,
            "severity": r.severity,
            "likelihood": r.likelihood,
            "blast_radius": r.blast_radius or NOT_RECORDED,
            "detection": r.detection or NOT_RECORDED,
            "existing_mitigation": r.mitigation or NOT_RECORDED,
            "recommended_mitigation": r.mitigation or NOT_RECORDED,
            "validation_method": r.validation_method or NOT_RECORDED,
            "status": r.status,
            "evidence": json.loads(r.evidence_json),
            "source": r.source,
        }
        for r in risks
    ]

    # ---- 9. Engineering plan (complete) -----------------------------------
    if plan:
        trace["engineering_plan"] = {
            "summary": plan.summary,
            "assumptions": json.loads(plan.assumptions_json),
            "acceptance_criteria": json.loads(plan.acceptance_criteria_json),
            "steps": json.loads(plan.steps_json),
            "files_likely_to_change": json.loads(plan.files_json),
            "dependencies": json.loads(plan.dependencies_json),
            "test_strategy": json.loads(plan.test_strategy_json),
            "risks": json.loads(plan.risks_json),
            "rollback_strategy": NOT_RECORDED,
            "constraints": NOT_RECORDED,
            "prompt_version": plan.prompt_version or NOT_RECORDED,
            "created_at": plan.created_at.isoformat(),
            "approved": plan.approved,
            "approval_comment": plan.approval_comment or "",
        }
    else:
        trace["engineering_plan"] = None

    # ---- 10. Human plan approval ------------------------------------------
    plan_approval_event = next((e for e in events if e.event_type in ("PLAN_APPROVED", "PLAN_REJECTED")), None)
    if plan is not None and plan.approved is not None:
        trace["plan_approval"] = {
            "status": "approved" if plan.approved else "rejected",
            "timestamp": plan_approval_event.timestamp.isoformat() if plan_approval_event else NOT_RECORDED,
            "comment": plan.approval_comment or "",
            "human_intervention_count": workflow.human_intervention_count,
        }
    else:
        trace["plan_approval"] = {"status": "pending" if plan else NOT_RECORDED, "timestamp": None, "comment": "", "human_intervention_count": workflow.human_intervention_count}

    # ---- 11. Code generation (actual vs. proposed-only, with real diffs) -
    # Workspace files are mutated ONLY after approve_changes(approved=True)
    # (see orchestrator.approve_changes) — so ProposedChange rows represent
    # actually-applied changes when the latest ChangeApprovalRecord
    # approved them, and proposed-but-not-applied changes otherwise.
    latest_change_approval = change_approvals[-1] if change_approvals else None
    changes_applied = bool(latest_change_approval and latest_change_approval.approved)
    changed_file_set = {c.file for c in changes}
    retrieved_only_files = sorted({e.file for e in evidence} - changed_file_set)

    trace["code_generation"] = {
        "applied": changes_applied,
        "files_modified": [
            {
                "file": c.file,
                "operation": c.operation,
                "reason": c.reason,
                "confidence": c.confidence,
                "acceptance_criterion": c.acceptance_criterion or NOT_RECORDED,
                "risks": json.loads(c.risks_json),
                "patch": c.patch,
                "status": "applied to workspace" if changes_applied else "proposed only — change set was rejected, workspace not mutated",
            }
            for c in changes
        ]
        if changes_applied
        else [],
        "files_proposed_not_applied": []
        if changes_applied
        else [
            {
                "file": c.file,
                "operation": c.operation,
                "reason": c.reason,
                "confidence": c.confidence,
                "risks": json.loads(c.risks_json),
                "patch": c.patch,
            }
            for c in changes
        ],
        "retrieved_read_only_files": retrieved_only_files,
    }

    # ---- 12. Human change approval -----------------------------------------
    change_approval_event = next((e for e in events if e.event_type in ("PATCH_APPROVED", "PATCH_REJECTED")), None)
    trace["change_approval"] = {
        "status": ("approved" if latest_change_approval.approved else "rejected") if latest_change_approval else NOT_RECORDED,
        "timestamp": change_approval_event.timestamp.isoformat() if change_approval_event else (latest_change_approval.timestamp.isoformat() if latest_change_approval else None),
        "comment": latest_change_approval.comment if latest_change_approval else "",
        "human_intervention_count": workflow.human_intervention_count,
        "files_approved": sorted(changed_file_set) if changes_applied else [],
        "all_decisions": [
            {"approved": a.approved, "comment": a.comment, "timestamp": a.timestamp.isoformat()}
            for a in change_approvals
        ],
    }

    # ---- 13. Test generation (generated != executed) -----------------------
    testgen_event = next((e for e in events if e.event_type == "TESTS_GENERATED"), None)
    trace["test_generation"] = {
        "status": "generated" if tests else ("pending" if workflow.testgen_ms is None else "no tests generated"),
        "generation_duration_ms": workflow.testgen_ms,
        "count": len(tests),
        "generated_at": testgen_event.timestamp.isoformat() if testgen_event else None,
        "tests": [
            {
                "file": t.file,
                "category": t.category,
                "rationale": t.rationale,
                "test_functions": _extract_test_function_names(t.content),
                "content": t.content,
                "executed": False,
                "execution_note": "Generated and persisted to the repository. Execution status is reported separately, at validation-stage granularity, in the Validation section — individual per-test pass/fail is not persisted.",
            }
            for t in tests
        ],
    }

    # ---- 14/15. Resilience testing & chaos simulation ------------------------
    # pipeline_view.build_pipeline() uses the SAME split for the
    # "Resilience Testing" / "Chaos Simulation" pipeline stages — reused
    # here verbatim so the report can never disagree with the UI strip.
    def _chaos_row(c: ChaosExperiment) -> dict:
        return {
            "experiment_id": c.experiment_id,
            "scenario": c.target,
            "failure_injected": c.fault,
            "hypothesis": c.hypothesis,
            "expected_behavior": c.expected_behavior,
            "actual_behavior": c.observed_behavior or NOT_RECORDED,
            "result": c.result,
            "environment": c.environment,
            "evidence": json.loads(c.evidence_json),
            "timestamp": c.timestamp.isoformat(),
        }

    applicable_chaos = [c for c in chaos_rows if c.result != "NOT_APPLICABLE"]
    trace["resilience_testing"] = {
        "status": "passed" if applicable_chaos and all(c.result == "PASSED" for c in applicable_chaos) else ("failed" if applicable_chaos else "not applicable — no applicable resilience scenario for this change"),
        "scenarios": [_chaos_row(c) for c in applicable_chaos],
    }
    trace["chaos_simulation"] = {
        "status": "passed" if applicable_chaos and all(c.result == "PASSED" for c in applicable_chaos) else ("failed" if applicable_chaos else ("not applicable" if chaos_rows else "pending")),
        "pass_count": sum(1 for c in chaos_rows if c.result == "PASSED"),
        "applicable_count": len(applicable_chaos),
        "total_count": len(chaos_rows),
        "scenarios": [_chaos_row(c) for c in chaos_rows],
        "limitations": [] if chaos_rows else ["No chaos experiments have been run for this workflow."],
    }

    # ---- 16. Guardrails & safety (full evidence) -----------------------------
    trace["guardrail_results"] = [
        {
            "guardrail_id": g.guardrail_id,
            "category": g.category,
            "name": g.name,
            "description": g.description,
            "purpose": g.purpose,
            "trigger_condition": g.trigger_condition,
            "enforcement_point": g.enforcement_point,
            "severity": g.severity,
            "status": g.status,
            "action": g.action,
            "evidence": json.loads(g.evidence_json),
            "remediation": g.remediation,
            "configurable_threshold": g.configurable_threshold,
            "evaluated_at": g.evaluated_at.isoformat(),
        }
        for g in guardrail_checks
    ]
    trace["guardrails_full"] = {
        "total": len(guardrail_checks),
        "passed": sum(1 for g in guardrail_checks if g.status == "PASSED"),
        "warnings": sum(1 for g in guardrail_checks if g.status == "WARNING"),
        "blocked": sum(1 for g in guardrail_checks if g.status == "BLOCKED"),
        "failed": sum(1 for g in guardrail_checks if g.status == "FAILED"),
        "not_applicable": sum(1 for g in guardrail_checks if g.status == "NOT_APPLICABLE"),
        "approval_required": sum(1 for g in guardrail_checks if g.action == "REQUIRE_APPROVAL"),
        "by_category": trace["guardrails"]["by_category"],
        "altered_execution": bool([g for g in guardrail_checks if g.status in ("BLOCKED", "FAILED") or g.action in ("BLOCK", "ABORT", "REQUIRE_APPROVAL")]),
        "checks": trace["guardrail_results"],
    }

    # ---- 17. Validation (full, with command/stdout/stderr/regression) -------
    trace["validation"] = {
        "final_result": final_validation or NOT_RECORDED,
        "repair_triggered": any(v.attempt > 0 for v in validations),
        "attempts": sorted({v.attempt for v in validations}),
        "runs": [
            {
                "stage": v.stage,
                "status": v.status,
                "attempt": v.attempt,
                "command": v.command or NOT_RECORDED,
                "exit_code": v.exit_code,
                "duration_ms": v.duration_ms,
                "stdout": v.stdout,
                "stderr": v.stderr,
                "timestamp": v.timestamp.isoformat(),
            }
            for v in validations
        ],
        "duration_ms": workflow.validation_ms,
    }

    # ---- 18. AI repair --------------------------------------------------------
    if repairs:
        trace["ai_repair"] = {
            "triggered": True,
            "attempt_count": len(repairs),
            "attempts": [
                {
                    "attempt_number": r.attempt_number,
                    "diagnosis": r.diagnosis,
                    "repair_patch": r.repair_patch,
                    "approved": r.approved,
                    "result": r.result or NOT_RECORDED,
                    "timestamp": r.created_at.isoformat(),
                }
                for r in repairs
            ],
            "final_result": repairs[-1].result or NOT_RECORDED,
        }
    else:
        trace["ai_repair"] = {
            "triggered": False,
            "attempt_count": 0,
            "attempts": [],
            "reason": "Validation passed without failure — AI repair is only triggered from VALIDATION_FAILED." if final_validation == "passed" else ("Validation has not completed yet." if final_validation is None else "Repair was not attempted despite a validation failure being recorded."),
        }

    # ---- 19. Production readiness (decision + reasons + checklist) ----------
    if readiness:
        trace["production_readiness_full"] = {
            "decision": readiness.decision,
            "reasons": json.loads(readiness.reasons_json),
            "checklist": json.loads(readiness.checklist_json),
            "assessed_at": readiness.created_at.isoformat(),
        }
    else:
        trace["production_readiness_full"] = {"decision": NOT_RECORDED, "reasons": [], "checklist": {}, "assessed_at": None}

    # ---- 20. CI/CD --------------------------------------------------------
    cicd_configured = github_ops.is_configured()
    ci_event = next((g for g in reversed(guardrail_checks) if g.guardrail_id == "CICD-01"), None)
    if ci_event:
        trace["ci_cd"] = {"applicable": True, "status": ci_event.status, "detail": ci_event.trigger_condition, "evaluated_at": ci_event.evaluated_at.isoformat()}
    elif not cicd_configured:
        trace["ci_cd"] = {"applicable": False, "status": "NOT_APPLICABLE", "detail": "GITHUB_TOKEN/OWNER/REPO not configured — CI/CD automation was not performed for this workflow."}
    else:
        trace["ci_cd"] = {"applicable": True, "status": "PENDING", "detail": "GitHub Actions is configured but no CI run has been recorded for this workflow yet."}

    # ---- 21. GitHub / PR ---------------------------------------------------
    pr_ops = [g for g in git_ops_rows if g.operation in ("push", "pr_created")]
    commit_ops = [g for g in git_ops_rows if g.operation == "commit"]
    branch_ops = [g for g in git_ops_rows if g.operation == "branch_created"]
    trace["github_pr"] = {
        "branch": workflow.branch_name or NOT_RECORDED,
        "branch_created": bool(branch_ops),
        "commit": {"status": "committed", "detail": commit_ops[-1].detail, "ref": commit_ops[-1].ref, "timestamp": commit_ops[-1].timestamp.isoformat()} if commit_ops else {"status": "not performed", "detail": NOT_RECORDED, "ref": None, "timestamp": None},
        "push": next(({"status": "pushed", "detail": g.detail, "ref": g.ref, "timestamp": g.timestamp.isoformat()} for g in reversed(git_ops_rows) if g.operation == "push"), {"status": "Not performed / Not applicable"}),
        "pull_request": next(({"status": "created", "detail": g.detail, "ref": g.ref, "timestamp": g.timestamp.isoformat()} for g in reversed(git_ops_rows) if g.operation == "pr_created"), {"status": "Not performed / Not applicable"}),
        "ci_status": trace["ci_cd"]["status"],
        "configured": cicd_configured,
        "all_operations": [{"operation": g.operation, "detail": g.detail, "ref": g.ref, "approved": g.approved, "timestamp": g.timestamp.isoformat()} for g in git_ops_rows],
    }
    if not pr_ops and not cicd_configured:
        trace["github_pr"]["note"] = "Not performed / Not applicable — GITHUB_TOKEN/OWNER/REPO not configured in this environment."

    # ---- 22/final_outcome ---------------------------------------------------
    # Mirrors the same completion rule used by the evaluation benchmark
    # runner (scripts/run_evaluation.py: COMPLETED state + at least one
    # applied change with confidence > 0) so this report can never disagree
    # with how "success" is defined elsewhere in this codebase.
    succeeded = workflow.state.value == "COMPLETED" and any(c.confidence > 0 for c in changes) and changes_applied
    open_risks = [r for r in risks if r.status == "OPEN"]
    trace["final_outcome"] = {
        "requested_change_succeeded": succeeded,
        "final_status": workflow.state.value,
        "files_changed": sorted(changed_file_set) if changes_applied else [],
        "final_validation": final_validation or NOT_RECORDED,
        "final_readiness_decision": readiness.decision if readiness else NOT_RECORDED,
        "remaining_open_risks": [{"risk_id": r.risk_id, "title": r.title, "severity": r.severity} for r in open_risks],
        "repair_attempts": workflow.repair_attempts,
        "human_intervention_count": workflow.human_intervention_count,
        "total_duration_ms": workflow.total_ms,
    }

    # ---- 23. Complete workflow timeline (single source: build_pipeline) -----
    trace["timeline"] = build_pipeline(session, workflow_id)["stages"]

    # ---- 24. File-level change summary ---------------------------------------
    file_change_summary = []
    for c in changes:
        file_change_summary.append(
            {
                "file": c.file,
                "action": f"{c.operation} ({'actually modified' if changes_applied else 'proposed, not applied — change set rejected'})",
                "reason": c.reason,
                "evidence": f"patch persisted ({len(c.patch.splitlines())} diff line(s))" if c.patch else NOT_RECORDED,
                "validation": final_validation or NOT_RECORDED,
            }
        )
    for f in retrieved_only_files:
        file_change_summary.append({"file": f, "action": "retrieved / read-only (not modified)", "reason": "Retrieved as relevant context during RAG retrieval but not part of the proposed change set.", "evidence": "retrieval evidence row", "validation": "n/a — not modified"})
    trace["file_change_summary"] = file_change_summary

    # ---- 25. Test evidence summary --------------------------------------------
    test_evidence_summary = []
    for t in tests:
        fn_names = _extract_test_function_names(t.content) or [t.file]
        for fn in fn_names:
            test_evidence_summary.append(
                {
                    "test": fn,
                    "file": t.file,
                    "purpose": t.rationale,
                    "category": t.category,
                    "result": "covered by unit_tests validation stage (aggregate result: {})".format(
                        next((v.status for v in validations if v.stage == "unit_tests" and v.attempt == max((v2.attempt for v2 in validations), default=0)), "not yet run")
                    ),
                    "evidence": f"{t.file} (generated test, workflow {workflow_id})",
                }
            )
    trace["test_evidence"] = test_evidence_summary

    # ---- 26. Guardrail evidence summary (table-ready, same rows as above) ----
    trace["guardrail_evidence"] = [
        {"category": g["category"], "check": f"[{g['guardrail_id']}] {g['name']}", "result": g["status"], "action": g["action"], "evidence": g["evidence"]}
        for g in trace["guardrail_results"]
    ]

    # ---- 27. Risk & readiness summary ------------------------------------------
    trace["risk_readiness_summary"] = [
        {
            "risk": r["title"],
            "severity": r["severity"],
            "detection": r["detection"],
            "mitigation": r["existing_mitigation"],
            "final_status": r["status"],
        }
        for r in trace["risk_analysis"]
    ]

    # ---- 28. Decision / approval audit -----------------------------------------
    approval_audit = []
    if plan is not None and plan.approved is not None:
        approval_audit.append(
            {
                "checkpoint": "Engineering Plan",
                "timestamp": trace["plan_approval"]["timestamp"],
                "decision": "approved" if plan.approved else "rejected",
                "comment": plan.approval_comment or "",
                "resulting_action": "proceeded to code generation" if plan.approved else "workflow stopped (PLAN_REJECTED)",
            }
        )
    for a in change_approvals:
        approval_audit.append(
            {
                "checkpoint": "Code Changes",
                "timestamp": a.timestamp.isoformat(),
                "decision": "approved" if a.approved else "rejected",
                "comment": a.comment or "",
                "resulting_action": "workspace mutated, changes applied" if a.approved else "workspace not mutated (CHANGES_REJECTED)",
            }
        )
    for r in repairs:
        if r.approved is not None:
            approval_audit.append(
                {
                    "checkpoint": f"Repair attempt {r.attempt_number}",
                    "timestamp": r.created_at.isoformat(),
                    "decision": "approved" if r.approved else "rejected",
                    "comment": "",
                    "resulting_action": r.result or NOT_RECORDED,
                }
            )
    commit_approval_events = [e for e in events if e.event_type == "COMMIT_APPROVED"]
    for e in commit_approval_events:
        approval_audit.append({"checkpoint": "Commit", "timestamp": e.timestamp.isoformat(), "decision": "approved", "comment": e.message or "", "resulting_action": "commit created"})
    trace["approvals"] = approval_audit

    # ---- 29. Limitations (only actually-observed/derivable facts) -------------
    limitations: list[dict] = []
    if is_mock:
        limitations.append({"category": "mock-mode", "note": "LLM_MODE=mock was used for this workflow: code generation, test generation, and intent classification used a bounded set of deterministic strategies rather than a general-purpose LLM."})
    elif is_mock is None:
        limitations.append({"category": "mock-mode", "note": "LLM provider mode could not be determined for this report; executive summary generation also failed — see executive_summary field."})
    if evidence:
        limitations.append({"category": "retrieval", "note": f"Retrieval returned {len(evidence)} evidence chunk(s) against a fixed top_k; precision/recall depend on repository size and are not persisted per-workflow beyond the evaluation benchmark."})
    if validations:
        limitations.append({"category": "validation", "note": "Validation results are recorded at stage granularity (syntax, lint, unit_tests, security), not per individual test function — individual generated-test pass/fail is not persisted."})
    if not chaos_rows:
        limitations.append({"category": "resilience/chaos", "note": "No chaos/resilience experiments have been recorded for this workflow."})
    elif not applicable_chaos:
        limitations.append({"category": "resilience/chaos", "note": "All recorded chaos experiments were NOT_APPLICABLE to this change — no applicable resilience evidence exists."})
    if not cicd_configured:
        limitations.append({"category": "infrastructure", "note": "GITHUB_TOKEN/OWNER/REPO are not configured in this environment — CI/CD and GitHub PR automation were not performed."})
    if not repository:
        limitations.append({"category": "repository", "note": "No repository record is linked to this workflow."})
    trace["limitations"] = limitations

    # ---- 30/31 top-level convenience aliases matching the requested schema ---
    trace["workflow_summary"] = {
        "final_status": workflow.state.value,
        "total_duration_ms": workflow.total_ms,
        "human_intervention_count": workflow.human_intervention_count,
        "repair_attempts": workflow.repair_attempts,
        "production_readiness_decision": readiness.decision if readiness else NOT_RECORDED,
        "final_validation": final_validation or NOT_RECORDED,
        "requested_change_succeeded": succeeded,
    }
    trace["repository_evidence"] = trace["production_context"]
    trace["approvals_audit"] = trace["approvals"]
    trace["repair_history"] = trace["ai_repair"]["attempts"]
    trace["readiness"] = trace["production_readiness_full"]
    trace["resilience_results"] = trace["resilience_testing"]["scenarios"]
    trace["chaos_results"] = trace["chaos_simulation"]["scenarios"]
    trace["generated_tests"] = trace["test_generation"]["tests"]
    trace["code_changes"] = trace["code_generation"]["files_modified"] or trace["code_generation"]["files_proposed_not_applied"]

    trace["stages"] = {
        "intent_understanding": trace["intent_understanding"],
        "production_context": trace["production_context"],
        "repository_indexing": trace["repository_indexing"],
        "repository_rag": trace["repository_rag"],
        "architecture_analysis": trace["architecture_analysis"],
        "risk_analysis": trace["risk_analysis"],
        "engineering_plan": trace["engineering_plan"],
        "plan_approval": trace["plan_approval"],
        "code_generation": trace["code_generation"],
        "change_approval": trace["change_approval"],
        "test_generation": trace["test_generation"],
        "resilience_testing": trace["resilience_testing"],
        "chaos_simulation": trace["chaos_simulation"],
        "guardrails": trace["guardrails_full"],
        "validation": trace["validation"],
        "ai_repair": trace["ai_repair"],
        "production_readiness": trace["production_readiness_full"],
        "ci_cd": trace["ci_cd"],
        "github_pr": trace["github_pr"],
        "final_report": {"generated_at": generated_at, "report_version": REPORT_VERSION},
    }

    return trace


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None recorded._", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("\n", " ").replace("|", "\\|") or "—" for c in row) + " |")
    lines.append("")
    return lines


def report_to_markdown(trace: dict) -> str:
    L: list[str] = []
    add = L.append

    add("# Intent2Deploy — Workflow Execution Report")
    add("")
    meta = trace.get("report_metadata", {})
    add(f"**Report version:** {meta.get('report_version', NOT_RECORDED)}  ")
    add(f"**Generated at:** {meta.get('generated_at', NOT_RECORDED)}  ")
    add(f"**Workflow ID:** {trace['workflow_id']}  ")
    add(f"**Project ID:** {meta.get('project_id', NOT_RECORDED)}")
    add("")

    # 1. Executive Summary
    add("## 1. Executive Summary")
    ws = trace.get("workflow_summary", {})
    add(f"- Developer intent: {trace['intent']}")
    add(f"- Repository: {trace['repository'] or NOT_RECORDED}")
    add(f"- Final workflow status: **{trace['final_status']}**")
    add(f"- Requested change succeeded: **{ws.get('requested_change_succeeded')}**")
    add(f"- Final validation: {ws.get('final_validation', NOT_RECORDED)}")
    add(f"- Total execution time: {ws.get('total_duration_ms', NOT_RECORDED)} ms")
    add(f"- Human interventions: {ws.get('human_intervention_count', NOT_RECORDED)}")
    add(f"- Repair attempts: {ws.get('repair_attempts', NOT_RECORDED)}")
    add(f"- Production readiness: {ws.get('production_readiness_decision', NOT_RECORDED)}")
    add("")
    add(trace.get("executive_summary", ""))
    add("")

    # 2. Developer Intent
    add("## 2. Developer Intent")
    di = trace.get("developer_intent", {})
    add(f"- Exact intent: {di.get('text', trace['intent'])}")
    add(f"- Submitted at: {di.get('submitted_at', NOT_RECORDED)}")
    add(f"- Base branch: {di.get('base_branch', NOT_RECORDED)}")
    add(f"- Test command: {di.get('test_command', NOT_RECORDED)}")
    add(f"- Build command: {di.get('build_command', NOT_RECORDED)}")
    add(f"- Environment: {di.get('environment', NOT_RECORDED)}")
    add("")

    # 3. Workflow Overview
    add("## 3. Workflow Overview")
    add(f"- Final status: {trace['final_status']}")
    add(f"- Final validation: {trace.get('final_validation') or NOT_RECORDED}")
    add(f"- Repair attempts: {trace['repair_attempts']}")
    add(f"- Human interventions: {trace['human_intervention_count']}")
    add("")

    # 4. Intent Understanding
    add("## 4. Intent Understanding")
    iu = trace.get("intent_understanding", {})
    add(f"- Classified category: {iu.get('classified_category', NOT_RECORDED)}")
    add(f"- Classification method: {iu.get('classification_method', NOT_RECORDED)}")
    add(f"- Confidence: {iu.get('confidence', NOT_RECORDED)}")
    add(f"- Interpreted problem: {iu.get('interpreted_problem', NOT_RECORDED)}")
    add(f"- Note: {iu.get('note', '')}")
    add("")

    # 5. Production Context
    add("## 5. Production Context")
    pc = trace.get("production_context", {})
    for k, label in [("repository_source", "Repository source"), ("repository_local_path", "Local path"), ("environment", "Environment"), ("file_count", "Files"), ("chunk_count", "Chunks"), ("indexed_at", "Indexed at")]:
        add(f"- {label}: {pc.get(k, NOT_RECORDED)}")
    add("")

    # 6. Repository Indexing
    add("## 6. Repository Indexing")
    ri = trace.get("repository_indexing", {})
    for k, label in [("status", "Status"), ("files_indexed", "Files indexed"), ("chunks_created", "Chunks created"), ("vector_store", "Vector store"), ("indexing_duration_ms", "Indexing duration (ms)")]:
        add(f"- {label}: {ri.get(k, NOT_RECORDED)}")
    add("")

    # 7. Repository RAG & Retrieved Evidence
    add("## 7. Repository RAG & Retrieved Evidence")
    rag = trace.get("repository_rag", {})
    add(f"- Query: {rag.get('query', NOT_RECORDED)}")
    add(f"- Retrieval duration: {rag.get('retrieval_duration_ms', NOT_RECORDED)} ms")
    add(f"- Chunks retrieved: {rag.get('chunk_count_retrieved', 0)}")
    add("")
    L.extend(_md_table(
        ["File", "Lines", "Score", "Method", "Chunk type", "Reason"],
        [[e["file"], f"{e['start_line']}-{e['end_line']}", f"{e['score']:.2f}", e["retrieval_method"], e["chunk_type"], e["reason"]] for e in rag.get("evidence", [])],
    ))

    # 8. Architecture Analysis
    add("## 8. Architecture Analysis")
    arch = trace.get("architecture_analysis", {})
    if "error" in arch:
        add(f"- {NOT_RECORDED} ({arch.get('detail', '')})")
    else:
        add(f"- Total files: {arch.get('total_files', NOT_RECORDED)}")
        add(f"- Total functions: {arch.get('total_functions', NOT_RECORDED)}")
        add(f"- Total classes: {arch.get('total_classes', NOT_RECORDED)}")
        add(f"- External dependencies: {', '.join(arch.get('external_dependencies', [])) or 'none detected'}")
        add("")
        L.extend(_md_table(["Component", "Path", "Files", "Functions", "Classes"], [[c["name"], c["path"], len(c["files"]), c["functions"], c["classes"]] for c in arch.get("components", [])]))
    add("")

    # 9. Risk Analysis
    add("## 9. Risk Analysis")
    L.extend(_md_table(
        ["Risk", "Category", "Severity", "Detection", "Existing mitigation", "Recommended mitigation", "Status"],
        [[r["title"], r["component"] or NOT_RECORDED, r["severity"], r["detection"], r["existing_mitigation"], r["recommended_mitigation"], r["status"]] for r in trace.get("risk_analysis", [])],
    ))

    # 10. Engineering Plan
    add("## 10. Engineering Plan")
    plan = trace.get("engineering_plan")
    if plan:
        add(f"- Summary: {plan['summary']}")
        add("- Assumptions:")
        for a in plan["assumptions"]:
            add(f"  - {a}")
        add("- Acceptance criteria:")
        for c in plan["acceptance_criteria"]:
            add(f"  - {c}")
        add("- Implementation steps:")
        for s in plan["steps"]:
            add(f"  - {s}")
        add(f"- Proposed files: {', '.join(plan['files_likely_to_change']) or NOT_RECORDED}")
        add("- Test strategy:")
        for t in plan["test_strategy"]:
            add(f"  - {t}")
        add(f"- Rollback strategy: {plan['rollback_strategy']}")
        add(f"- Constraints: {plan['constraints']}")
        add("- Risks stated in plan:")
        for r in plan["risks"]:
            add(f"  - {r}")
    else:
        add(f"_{NOT_RECORDED}_")
    add("")

    # 11. Human Approval — Plan
    add("## 11. Human Approval — Plan")
    pa = trace.get("plan_approval", {})
    for k, label in [("status", "Status"), ("timestamp", "Timestamp"), ("comment", "Comment"), ("human_intervention_count", "Human intervention count (workflow total)")]:
        add(f"- {label}: {pa.get(k) if pa.get(k) not in (None, '') else NOT_RECORDED}")
    add("")

    # 12. Code Generation
    add("## 12. Code Generation")
    cg = trace.get("code_generation", {})
    add(f"- Applied to workspace: {cg.get('applied')}")
    add("### Files actually modified" if cg.get("applied") else "### Files proposed (NOT applied — change set rejected)")
    rows = cg.get("files_modified") or cg.get("files_proposed_not_applied") or []
    for c in rows:
        add(f"**`{c['file']}`** ({c['operation']}, confidence={c['confidence']})")
        add(f"- Reason: {c['reason']}")
        if c.get("risks"):
            add(f"- Risks: {', '.join(c['risks'])}")
        add("- Unified diff:")
        add("```diff")
        add(c["patch"] or NOT_RECORDED)
        add("```")
        add("")
    add(f"- Retrieved/read-only files (not modified): {', '.join(cg.get('retrieved_read_only_files', [])) or 'none'}")
    add("")

    # 13. Human Approval — Code Changes
    add("## 13. Human Approval — Code Changes")
    ca = trace.get("change_approval", {})
    for k, label in [("status", "Status"), ("timestamp", "Timestamp"), ("comment", "Comment"), ("human_intervention_count", "Human intervention count (workflow total)")]:
        add(f"- {label}: {ca.get(k) if ca.get(k) not in (None, '') else NOT_RECORDED}")
    add("")

    # 14. Test Generation
    add("## 14. Test Generation")
    tg = trace.get("test_generation", {})
    add(f"- Status: {tg.get('status')}")
    add(f"- Count: {tg.get('count')}")
    add(f"- Generation duration: {tg.get('generation_duration_ms')} ms")
    for t in tg.get("tests", []):
        add(f"### `{t['file']}` [{t['category']}]")
        add(f"- Rationale: {t['rationale']}")
        add(f"- Test functions: {', '.join(t['test_functions']) or NOT_RECORDED}")
        add(f"- {t['execution_note']}")
        add("```python")
        add(t["content"])
        add("```")
        add("")

    # 15. Resilience Testing
    add("## 15. Resilience Testing")
    rt = trace.get("resilience_testing", {})
    add(f"- Status: {rt.get('status')}")
    L.extend(_md_table(
        ["Scenario", "Failure/Condition", "Expected Behavior", "Actual Result", "Status", "Evidence"],
        [[s["scenario"], s["failure_injected"], s["expected_behavior"], s["actual_behavior"], s["result"], "; ".join(str(x) for x in s["evidence"]) or NOT_RECORDED] for s in rt.get("scenarios", [])],
    ))

    # 16. Chaos Simulation
    add("## 16. Chaos Simulation")
    cs = trace.get("chaos_simulation", {})
    add(f"- Status: {cs.get('status')} ({cs.get('pass_count')}/{cs.get('applicable_count')} applicable passed, {cs.get('total_count')} total recorded)")
    L.extend(_md_table(
        ["Scenario ID", "Scenario", "Failure Injected", "Expected Behavior", "Actual Behavior", "Result", "Evidence"],
        [[s["experiment_id"], s["scenario"], s["failure_injected"], s["expected_behavior"], s["actual_behavior"], s["result"], "; ".join(str(x) for x in s["evidence"]) or NOT_RECORDED] for s in cs.get("scenarios", [])],
    ))
    for lim in cs.get("limitations", []):
        add(f"> Limitation: {lim}")
    add("")

    # 17. Guardrails & Safety
    add("## 17. Guardrails & Safety (Guardrail Results)")
    g = trace.get("guardrails_full", {})
    add(f"- Total checks: {g.get('total')} — passed={g.get('passed')}, warnings={g.get('warnings')}, blocked={g.get('blocked')}, failed={g.get('failed')}, not_applicable={g.get('not_applicable')}")
    add(f"- Approval-required checks: {g.get('approval_required')}")
    add(f"- A guardrail altered or prevented execution: {g.get('altered_execution')}")
    add("")
    L.extend(_md_table(
        ["Category", "Guardrail", "Result", "Action", "Evidence"],
        [[c["category"], f"[{c['guardrail_id']}] {c['name']}", c["status"], c["action"], "; ".join(str(x) for x in c["evidence"]) or NOT_RECORDED] for c in g.get("checks", [])],
    ))

    # 18. Validation
    add("## 18. Validation")
    v = trace.get("validation", {})
    add(f"- Final result: {v.get('final_result')}")
    add(f"- Repair triggered: {v.get('repair_triggered')}")
    add(f"- Total validation duration: {v.get('duration_ms')} ms")
    for run in v.get("runs", []):
        add(f"### [{run['stage']}] attempt {run['attempt']} — {run['status']}")
        add(f"- Command: `{run['command']}`")
        add(f"- Exit code: {run['exit_code']}")
        add(f"- Duration: {run['duration_ms']} ms")
        if run["stderr"]:
            add("- stderr:")
            add("```")
            add(run["stderr"][:4000])
            add("```")
        add("")

    # 19. AI Repair
    add("## 19. AI Repair")
    ar = trace.get("ai_repair", {})
    add(f"- Triggered: {ar.get('triggered')}")
    if ar.get("triggered"):
        add(f"- Attempts: {ar.get('attempt_count')}")
        for a in ar.get("attempts", []):
            add(f"  - Attempt {a['attempt_number']}: {a['diagnosis']} → result={a['result']}")
        add(f"- Final result: {ar.get('final_result')}")
    else:
        add(f"- Reason skipped: {ar.get('reason')}")
    add("")

    # 20. Production Readiness
    add("## 20. Production Readiness (Production Readiness — Final Decision)")
    pr = trace.get("production_readiness_full", {})
    add(f"- Decision: **{pr.get('decision')}**")
    add("- Reasons:")
    for r in pr.get("reasons", []):
        add(f"  - {r}")
    add("- Checklist:")
    for k, v2 in pr.get("checklist", {}).items():
        add(f"  - {k}: {v2}")
    add("")

    # 21. CI/CD
    add("## 21. CI/CD")
    ci = trace.get("ci_cd", {})
    add(f"- Applicable: {ci.get('applicable')}")
    add(f"- Status: {ci.get('status')}")
    add(f"- Detail: {ci.get('detail')}")
    add("")

    # 22. GitHub / Pull Request
    add("## 22. GitHub / Pull Request")
    gh = trace.get("github_pr", {})
    add(f"- Branch: {gh.get('branch')}")
    add(f"- Commit: {gh.get('commit', {}).get('status')}")
    add(f"- Push: {gh.get('push', {}).get('status')}")
    add(f"- Pull request: {gh.get('pull_request', {}).get('status')}")
    add(f"- CI status: {gh.get('ci_status')}")
    if gh.get("note"):
        add(f"- {gh['note']}")
    add("")

    # 23. Complete Workflow Timeline
    add("## 23. Complete Workflow Timeline")
    L.extend(_md_table(
        ["Stage", "Status", "Timestamp / Duration", "Evidence", "Outcome"],
        [[s["name"], s["status"], s.get("timestamp") or (f"{s.get('duration_ms')}ms" if s.get("duration_ms") is not None else NOT_RECORDED), "; ".join(s.get("evidence", [])) or NOT_RECORDED, s.get("output") or NOT_RECORDED] for s in trace.get("timeline", [])],
    ))

    # 24. File-Level Change Summary
    add("## 24. File-Level Change Summary")
    L.extend(_md_table(
        ["File", "Action", "Reason", "Evidence", "Validation"],
        [[f["file"], f["action"], f["reason"], f["evidence"], f["validation"]] for f in trace.get("file_change_summary", [])],
    ))

    # 25. Test Evidence
    add("## 25. Test Evidence")
    L.extend(_md_table(
        ["Test", "Purpose", "Result", "Evidence"],
        [[t["test"], t["purpose"], t["result"], t["evidence"]] for t in trace.get("test_evidence", [])],
    ))

    # 26. Guardrail Evidence
    add("## 26. Guardrail Evidence")
    L.extend(_md_table(
        ["Category", "Check", "Result", "Action", "Evidence"],
        [[g["category"], g["check"], g["result"], g["action"], "; ".join(str(x) for x in g["evidence"]) or NOT_RECORDED] for g in trace.get("guardrail_evidence", [])],
    ))

    # 27. Risk & Readiness Summary
    add("## 27. Risk & Readiness Summary")
    L.extend(_md_table(
        ["Risk", "Severity", "Detection", "Mitigation", "Final Status"],
        [[r["risk"], r["severity"], r["detection"], r["mitigation"], r["final_status"]] for r in trace.get("risk_readiness_summary", [])],
    ))

    # 28. Human Approval Audit
    add("## 28. Human Approval Audit")
    L.extend(_md_table(
        ["Checkpoint", "Timestamp", "Decision", "Comment", "Resulting Action"],
        [[a["checkpoint"], a["timestamp"], a["decision"], a["comment"] or NOT_RECORDED, a["resulting_action"]] for a in trace.get("approvals", [])],
    ))

    # 29. Final Outcome
    add("## 29. Final Outcome")
    fo = trace.get("final_outcome", {})
    add(f"- Requested change succeeded: **{fo.get('requested_change_succeeded')}**")
    add(f"- Files changed: {', '.join(fo.get('files_changed', [])) or 'none'}")
    add(f"- Final validation: {fo.get('final_validation')}")
    add(f"- Final readiness decision: {fo.get('final_readiness_decision')}")
    add(f"- Remaining open risks: {len(fo.get('remaining_open_risks', []))}")
    for r in fo.get("remaining_open_risks", []):
        add(f"  - [{r['severity']}] {r['title']}")
    add("")

    # 30. Limitations
    add("## 30. Limitations")
    for lim in trace.get("limitations", []):
        add(f"- **[{lim['category']}]** {lim['note']}")
    if not trace.get("limitations"):
        add("_None observed._")
    add("")

    # 31. Recommended Next Steps
    add("## 31. Recommended Next Steps")
    if fo.get("remaining_open_risks"):
        add("- Mitigate or explicitly accept the remaining open risks listed above before promoting this change further.")
    if pr.get("decision") == "NOT_READY":
        add("- Address the blocking reasons listed in Production Readiness before proceeding.")
    if not trace.get("github_pr", {}).get("configured"):
        add("- Configure GITHUB_TOKEN/OWNER/REPO to enable real CI/CD and PR automation for this workflow.")
    if trace["final_status"] != "COMPLETED":
        add("- Workflow has not reached COMPLETED — resume at the current stage to continue.")
    add("")
    add("## Evidence Classification (FACT / INFERRED / ASSUMPTION / UNKNOWN / UNVERIFIED)")
    for item in trace["evidence_classification"]:
        add(f"- **[{item['classification']}]** {item['item']} — {item['note']}")
    add("")
    add("## Audit Trail")
    for e in trace["audit_trail"]:
        add(f"- `{e['timestamp']}` {e['event_type']} ({e['stage']})")
    add("")
    add("## Timing (ms)")
    for k, v3 in trace["timing_ms"].items():
        add(f"- {k}: {v3}")

    return "\n".join(L)
