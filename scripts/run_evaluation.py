#!/usr/bin/env python3
"""Evaluation runner (master spec §23, §24, §37).

Loads every task in evaluation/tasks/*.json, runs the FULL Intent2Deploy
AI workflow against the demo repository for each one (auto-approving each
human checkpoint, since this is an unattended benchmark run — every
approval still increments the workflow's human_intervention_count so the
metric is comparable to an interactively-approved run), and writes real,
measured results to evaluation/results/run_<timestamp>.json plus a
Markdown summary. No number in the output is invented: every metric is
computed from the actual persisted workflow rows for that run.

Usage:
    python scripts/run_evaluation.py [--tasks-dir evaluation/tasks] [--repo demo-repository]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app import models  # noqa: F401,E402
from app.models.enums import WorkflowState  # noqa: E402
from app.services import orchestrator as orch  # noqa: E402
from app.services.evaluation.baseline_runner import collect_pristine_test_ids  # noqa: E402
from app.services.orchestrator import OrchestratorError  # noqa: E402
from app.services.providers.local_provider import LocalProvider  # noqa: E402
from app.services.validation.sandbox import destroy_workspace  # noqa: E402


def run_one_task(
    session: Session, project_id: str, repository_id: str, task: dict, baseline_tests: set[str]
) -> dict:
    provider = LocalProvider()
    intent = task["intent"]
    started = time.monotonic()

    result: dict = {
        "task_id": task["id"],
        "title": task["title"],
        "category": task["category"],
        "difficulty": task.get("difficulty", "medium"),
        "completed": False,
        "final_status": "FAILED",
        "final_validation": None,
        "human_interventions": 0,
        "repair_attempts": 0,
        "execution_time_ms": None,
        "changes_confidence": [],
        "retrieval_precision_at_k": None,
        "retrieval_recall_at_k": None,
        "unnecessary_modification_ratio": None,
        "touched_expected_files": None,
        "regressed_tests": [],
        "guardrail_total": 0,
        "guardrail_warnings": 0,
        "guardrail_blocked": 0,
        "guardrail_failed": 0,
        "stage_latency_ms": {
            "indexing": None,
            "planning": None,
            "codegen": None,
            "testgen": None,
            "validation": None,
            "total": None,
        },
        "error": None,
    }

    try:
        wf = orch.create_workflow(session, project_id, repository_id, intent)
        wf = orch.run_indexing(session, wf.id)
        wf = orch.run_planning(session, wf.id, provider)

        # --- retrieval quality vs ground truth expected_files -----------
        from sqlmodel import select

        from app.models.models import RetrievedDocument

        retrieved_docs = session.exec(select(RetrievedDocument).where(RetrievedDocument.workflow_id == wf.id)).all()
        retrieved_files = {d.file for d in retrieved_docs}
        expected_files = set(task.get("expected_files", []))
        if expected_files:
            hit = retrieved_files & expected_files
            result["retrieval_precision_at_k"] = round(len(hit) / len(retrieved_files), 3) if retrieved_files else 0.0
            result["retrieval_recall_at_k"] = round(len(hit) / len(expected_files), 3) if expected_files else None

        wf = orch.approve_plan(session, wf.id, True, comment="auto-approved by evaluation runner")
        wf = orch.run_codegen(session, wf.id, provider)

        from app.models.models import ProposedChange

        changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == wf.id)).all()
        result["changes_confidence"] = [c.confidence for c in changes]
        changed_files = {c.file for c in changes}
        if expected_files and changed_files:
            unexpected = changed_files - expected_files
            result["unnecessary_modification_ratio"] = round(len(unexpected) / len(changed_files), 3)
        if expected_files:
            result["touched_expected_files"] = round(len(changed_files & expected_files) / len(expected_files), 3)

        wf = orch.approve_changes(session, wf.id, True, comment="auto-approved by evaluation runner")
        wf = orch.run_test_generation(session, wf.id, provider)
        wf = orch.run_validation(session, wf.id)

        attempts = 0
        while wf.state == WorkflowState.VALIDATION_FAILED and attempts < 2:
            try:
                repair = orch.propose_repair_for_workflow(session, wf.id, provider)
            except OrchestratorError:
                break
            if not repair.repair_patch:
                break
            wf = orch.approve_repair(session, wf.id, repair.id, True)
            attempts += 1

        # Real (not proxy) regression check: did any test that passed on
        # the pristine repository show up as FAILED in the final
        # unit_tests run for this task?
        from app.models.models import ValidationResult

        unit_results = session.exec(
            select(ValidationResult).where(
                ValidationResult.workflow_id == wf.id, ValidationResult.stage == "unit_tests"
            )
        ).all()
        if unit_results:
            latest = max(unit_results, key=lambda r: (r.attempt, r.timestamp))
            failed_ids = {
                m.group(1)
                for m in re.finditer(r"FAILED (tests/\S+)", latest.stdout + latest.stderr)
            }
            result["regressed_tests"] = sorted(failed_ids & baseline_tests)

        if wf.state == WorkflowState.AWAITING_COMMIT_APPROVAL:
            wf = orch.approve_commit(session, wf.id, True, comment="auto-approved by evaluation runner")
            wf = orch.finalize_workflow(session, wf.id)
            result["final_validation"] = "passed"
        else:
            result["final_validation"] = "failed"

        result["final_status"] = wf.state.value
        result["human_interventions"] = wf.human_intervention_count
        result["repair_attempts"] = wf.repair_attempts
        has_real_change = any(c > 0 for c in result["changes_confidence"])
        result["completed"] = wf.state == WorkflowState.COMPLETED and has_real_change
        result["execution_time_ms"] = int((time.monotonic() - started) * 1000)

        # Guardrail check counts, read from the real persisted rows the
        # orchestrator already wrote during this run (guardrails fire
        # automatically at each checkpoint; nothing is re-evaluated here).
        from app.models.models import GuardrailCheck

        checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == wf.id)).all()
        result["guardrail_total"] = len(checks)
        result["guardrail_warnings"] = sum(1 for c in checks if c.status == "WARNING")
        result["guardrail_blocked"] = sum(1 for c in checks if c.status == "BLOCKED")
        result["guardrail_failed"] = sum(1 for c in checks if c.status == "FAILED")

        # Per-stage latency, already computed by the orchestrator and
        # persisted on the Workflow row — just surfaced here.
        result["stage_latency_ms"] = {
            "indexing": wf.indexing_ms,
            "planning": wf.planning_ms,
            "codegen": wf.codegen_ms,
            "testgen": wf.testgen_ms,
            "validation": wf.validation_ms,
            "total": wf.total_ms,
        }

    except OrchestratorError as exc:
        result["error"] = str(exc)
    finally:
        try:
            destroy_workspace(wf.id)  # type: ignore[possibly-undefined]
        except Exception:
            pass

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-dir", default=str(PROJECT_ROOT / "evaluation" / "tasks"))
    parser.add_argument("--repo", default=str(PROJECT_ROOT / "demo-repository"))
    parser.add_argument("--db", default=str(PROJECT_ROOT / "evaluation" / "results" / "eval_run.db"))
    args = parser.parse_args()

    tasks_dir = Path(args.tasks_dir)
    tasks = sorted(tasks_dir.glob("task_*.json"))
    if not tasks:
        print(f"No tasks found in {tasks_dir}")
        sys.exit(1)

    results_dir = PROJECT_ROOT / "evaluation" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()

    print(f"Collecting baseline test suite from {args.repo} ...")
    baseline_tests = collect_pristine_test_ids(Path(args.repo))
    print(f"Baseline test suite: {len(baseline_tests)} tests")

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    task_results = []
    with Session(engine) as session:
        project = orch.create_project(session, "Evaluation Benchmark")
        repository = orch.register_repository(session, project.id, args.repo)

        for task_file in tasks:
            task = json.loads(task_file.read_text())
            print(f"\n=== Running {task['id']}: {task['title']} ===")
            result = run_one_task(session, project.id, repository.id, task, baseline_tests)
            print(f"    completed={result['completed']} final_status={result['final_status']} repairs={result['repair_attempts']}")
            task_results.append(result)

    n = len(task_results)
    completed = sum(1 for r in task_results if r["completed"])
    validated = sum(1 for r in task_results if r["final_validation"] == "passed")
    avg_interventions = sum(r["human_interventions"] for r in task_results) / n
    avg_repairs = sum(r["repair_attempts"] for r in task_results) / n
    times = [r["execution_time_ms"] for r in task_results if r["execution_time_ms"] is not None]
    avg_time = sum(times) / len(times) if times else None

    precisions = [r["retrieval_precision_at_k"] for r in task_results if r["retrieval_precision_at_k"] is not None]
    recalls = [r["retrieval_recall_at_k"] for r in task_results if r["retrieval_recall_at_k"] is not None]
    unnecessary = [r["unnecessary_modification_ratio"] for r in task_results if r["unnecessary_modification_ratio"] is not None]
    regressed_count = sum(1 for r in task_results if r["regressed_tests"])
    avg_guardrail_warnings = sum(r["guardrail_warnings"] for r in task_results) / n
    avg_guardrail_blocked = sum(r["guardrail_blocked"] for r in task_results) / n

    def _avg_stage(stage: str) -> float | None:
        vals = [r["stage_latency_ms"][stage] for r in task_results if r["stage_latency_ms"][stage] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "tasks_total": n,
        "tasks_completed": completed,
        "task_completion_rate": round(completed / n, 3),
        "validation_success_rate": round(validated / n, 3),
        "avg_human_interventions": round(avg_interventions, 2),
        "avg_repair_attempts": round(avg_repairs, 2),
        "avg_execution_time_ms": round(avg_time, 1) if avg_time is not None else None,
        "avg_retrieval_precision_at_k": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "avg_retrieval_recall_at_k": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "avg_unnecessary_modification_ratio_proxy": round(sum(unnecessary) / len(unnecessary), 3) if unnecessary else None,
        "regression_rate": round(regressed_count / n, 3),
        "regression_rate_note": (
            "Computed against the real pristine-repository baseline test collection "
            f"({len(baseline_tests)} tests) — a baseline test is counted regressed only "
            "if it passed before this task's changes and shows FAILED in the task's "
            "final unit_tests run."
        ),
        "avg_guardrail_warnings": round(avg_guardrail_warnings, 2),
        "avg_guardrail_blocked": round(avg_guardrail_blocked, 2),
        "avg_stage_latency_ms": {
            "indexing": _avg_stage("indexing"),
            "planning": _avg_stage("planning"),
            "codegen": _avg_stage("codegen"),
            "testgen": _avg_stage("testgen"),
            "validation": _avg_stage("validation"),
        },
        "resource_consumption": "Not available from provider (LLM_MODE=mock; token/cost accounting requires LLM_MODE=live with a configured provider)",
        "results": task_results,
    }

    out_file = results_dir / f"run_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_file.write_text(json.dumps(summary, indent=2))

    md_lines = [
        "# Evaluation Run Summary",
        "",
        f"Timestamp: {summary['timestamp']}",
        f"Tasks: {summary['tasks_total']}",
        f"Completed: {summary['tasks_completed']}",
        f"Task Completion Rate: {summary['task_completion_rate'] * 100:.0f}%",
        f"Validation Success Rate: {summary['validation_success_rate'] * 100:.0f}%",
        f"Average Human Interventions: {summary['avg_human_interventions']}",
        f"Average Repair Attempts: {summary['avg_repair_attempts']}",
        f"Average Execution Time: {summary['avg_execution_time_ms']}ms",
        f"Retrieval Precision@K (avg): {summary['avg_retrieval_precision_at_k']}",
        f"Retrieval Recall@K (avg): {summary['avg_retrieval_recall_at_k']}",
        f"Unnecessary Modification Ratio (proxy, avg): {summary['avg_unnecessary_modification_ratio_proxy']}",
        f"Regression Rate: {summary['regression_rate'] * 100:.0f}% ({summary['regression_rate_note']})",
        f"Average Guardrail Warnings: {summary['avg_guardrail_warnings']}",
        f"Average Guardrail Blocks: {summary['avg_guardrail_blocked']}",
        f"Average Stage Latency (ms): {summary['avg_stage_latency_ms']}",
        f"Resource Consumption: {summary['resource_consumption']}",
        "",
        "| Task | Category | Completed | Final Status | Repairs |",
        "|---|---|---|---|---|",
    ]
    for r in task_results:
        md_lines.append(f"| {r['task_id']} | {r['category']} | {r['completed']} | {r['final_status']} | {r['repair_attempts']} |")
    (results_dir / f"run_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}_summary.md").write_text("\n".join(md_lines))

    print("\n" + "\n".join(md_lines))
    print(f"\nFull results written to {out_file}")

    db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
