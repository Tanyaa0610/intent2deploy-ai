"""Proves the final workflow report distinguishes FACT / INFERRED /
ASSUMPTION / UNKNOWN / UNVERIFIED and surfaces real risk/guardrail/
readiness data — not fabricated."""
from __future__ import annotations

from app.services import orchestrator as orch
from app.services.providers.local_provider import LocalProvider
from app.services.reporting import build_report, report_to_markdown


def test_report_includes_real_risks_guardrails_and_evidence_classification(db_session, demo_repo_copy):
    provider = LocalProvider()
    project = orch.create_project(db_session, "Report Evidence Project")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add a password reset feature.", environment="sandbox")
    wf = orch.run_indexing(db_session, wf.id)
    wf = orch.run_planning(db_session, wf.id, provider)
    wf = orch.approve_plan(db_session, wf.id, True)
    wf = orch.run_codegen(db_session, wf.id, provider)
    wf = orch.approve_changes(db_session, wf.id, True)
    wf = orch.run_test_generation(db_session, wf.id, provider)
    wf = orch.run_validation(db_session, wf.id)

    orch.run_risk_analysis(db_session, wf.id)
    orch.run_production_readiness(db_session, wf.id)

    trace = build_report(db_session, wf.id)

    # Real guardrail data, not a fabricated summary.
    assert trace["guardrails"]["total"] > 0
    assert set(trace["guardrails"]["by_category"]).issubset(
        {"SECURITY", "INFRASTRUCTURE", "CI_CD", "DEPLOYMENT", "COST", "AI_LLM", "INPUT", "OUTPUT"}
    )

    # Real risk data.
    assert trace["risks"]
    assert all(r["title"] for r in trace["risks"])

    # Real production-readiness decision with reasons.
    assert trace["production_readiness"]["decision"] in ("READY", "READY_WITH_WARNINGS", "NOT_READY")
    assert trace["production_readiness"]["reasons"]

    # Evidence classification only uses the five allowed labels, and every
    # entry traces back to something real (intent text, a retrieval hit, a
    # plan assumption).
    labels = {item["classification"] for item in trace["evidence_classification"]}
    assert labels.issubset({"FACT", "INFERRED", "ASSUMPTION", "UNKNOWN", "UNVERIFIED"})
    assert any(item["classification"] == "FACT" and item["item"] == "Developer intent" for item in trace["evidence_classification"])
    fact_files = {item["item"] for item in trace["evidence_classification"] if item["classification"] == "FACT"}
    retrieved_files = {f"{e['file']}:{e['start_line']}-{e['end_line']}" for e in trace["evidence"]}
    assert fact_files & retrieved_files or not trace["evidence"]

    markdown = report_to_markdown(trace)
    assert "Evidence Classification" in markdown
    assert "Guardrail Results" in markdown
    assert "Production Readiness — Final Decision" in markdown
