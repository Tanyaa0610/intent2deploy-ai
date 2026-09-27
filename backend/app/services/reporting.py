"""Final report assembly (master spec §7, §32).

Deterministically assembles the full workflow trace from persisted data
(never re-derives or fabricates anything), then asks the LLM provider for
a short prose executive summary of that trace via the
`final_report_generation` prompt.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.models.models import (
    AuditEvent,
    ChangeApprovalRecord,
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
from app.services.orchestrator import get_workflow
from app.services.providers.factory import get_provider


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


def build_report(session: Session, workflow_id: str) -> dict:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    plan = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    tests = session.exec(select(GeneratedTest).where(GeneratedTest.workflow_id == workflow_id)).all()
    validations = session.exec(select(ValidationResult).where(ValidationResult.workflow_id == workflow_id)).all()
    repairs = session.exec(select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id)).all()
    evidence = session.exec(select(RetrievedDocument).where(RetrievedDocument.workflow_id == workflow_id)).all()
    events = session.exec(select(AuditEvent).where(AuditEvent.workflow_id == workflow_id).order_by(AuditEvent.timestamp)).all()
    git_ops_rows = session.exec(select(GitOperation).where(GitOperation.workflow_id == workflow_id)).all()
    change_approvals = session.exec(select(ChangeApprovalRecord).where(ChangeApprovalRecord.workflow_id == workflow_id)).all()
    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    guardrail_checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id)).all()
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

    trace = {
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

    try:
        provider = get_provider()
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

    return trace


def report_to_markdown(trace: dict) -> str:
    lines = [
        "# Intent2Deploy AI — Final Report",
        "",
        f"**Workflow ID:** {trace['workflow_id']}",
        f"**Final status:** {trace['final_status']}",
        f"**Repository:** {trace['repository']}",
        "",
        "## Developer Intent",
        trace["intent"],
        "",
        "## Executive Summary",
        trace.get("executive_summary", ""),
        "",
        "## Plan",
    ]
    if trace["plan"]:
        lines.append(f"- Summary: {trace['plan']['summary']}")
        lines.append(f"- Approved: {trace['plan']['approved']}")
        lines.append("- Acceptance criteria:")
        for c in trace["plan"]["acceptance_criteria"]:
            lines.append(f"  - {c}")
    lines.append("")
    lines.append("## Retrieved Evidence")
    for e in trace["evidence"]:
        lines.append(f"- `{e['file']}:{e['start_line']}-{e['end_line']}` (score={e['score']:.2f}) — {e['reason']}")
    lines.append("")
    lines.append("## Proposed Changes")
    for c in trace["changes"]:
        lines.append(f"- `{c['file']}` ({c['operation']}, confidence={c['confidence']}) — {c['reason']}")
    lines.append("")
    lines.append("## Tests")
    for t in trace["tests"]:
        lines.append(f"- `{t['file']}` [{t['category']}] — {t['rationale']}")
    lines.append("")
    lines.append("## Validation Results")
    for v in trace["validation_results"]:
        lines.append(f"- [{v['stage']}] attempt={v['attempt']} status={v['status']} ({v['duration_ms']}ms)")
    lines.append(f"\n**Final validation:** {trace['final_validation']}")
    lines.append(f"**Repair attempts:** {trace['repair_attempts']}")
    lines.append(f"**Human interventions:** {trace['human_intervention_count']}")
    lines.append("")
    lines.append("## Risks")
    for r in trace["risks"]:
        lines.append(f"- [{r['severity']}] `{r['risk_id']}` {r['title']} (component={r['component']}, status={r['status']}, source={r['source']})")
    lines.append("")
    lines.append("## Guardrail Results")
    g = trace["guardrails"]
    lines.append(f"- Total checks: {g['total']} — passed={g['passed']}, warnings={g['warnings']}, blocked={g['blocked']}, failed={g['failed']}")
    for cat, n in g["by_category"].items():
        lines.append(f"  - {cat}: {n} check(s)")
    if g["blocking"]:
        lines.append("- Blocking/failed guardrails:")
        for b in g["blocking"]:
            lines.append(f"  - [{b['guardrail_id']}] {b['name']} ({b['category']}) — {b['reason']}")
    lines.append("")
    lines.append("## Production Readiness — Final Decision")
    if trace["production_readiness"]:
        lines.append(f"**Decision:** {trace['production_readiness']['decision']}")
        for reason in trace["production_readiness"]["reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("Not yet assessed.")
    lines.append("")
    lines.append("## Evidence Classification (FACT / INFERRED / ASSUMPTION / UNKNOWN / UNVERIFIED)")
    for item in trace["evidence_classification"]:
        lines.append(f"- **[{item['classification']}]** {item['item']} — {item['note']}")
    lines.append("")
    lines.append("## Git Operations")
    for g in trace["git_operations"]:
        lines.append(f"- {g['operation']}: {g['detail']}")
    lines.append("")
    lines.append("## Audit Trail")
    for e in trace["audit_trail"]:
        lines.append(f"- `{e['timestamp']}` {e['event_type']} ({e['stage']})")
    lines.append("")
    lines.append("## Timing (ms)")
    for k, v in trace["timing_ms"].items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
