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
    Plan,
    ProposedChange,
    RepairAttempt,
    Repository,
    RetrievedDocument,
    ValidationResult,
)
from app.services.orchestrator import get_workflow
from app.services.providers.factory import get_provider


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
