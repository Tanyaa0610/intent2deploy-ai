#!/usr/bin/env python3
"""BASELINE evaluation runner — see docs/EXPERIMENTAL_EVALUATION.md.

Runs every task in evaluation/tasks/*.json through the BASELINE
(non-orchestrated) approach: developer intent + a naive keyword-matched
"basic repository context" fed directly to the same LLM provider used by
Intent2Deploy (LocalProvider in LLM_MODE=mock), with no retrieval
pipeline, no planning stage, no human-approval checkpoints, no guardrail
engine, and a single validation run (no bounded repair loop). Results are
written in the same shape as `scripts/run_evaluation.py`'s output so
`scripts/compare_evaluation_runs.py` can line the two up metric-for-metric.

Usage:
    python scripts/run_baseline_evaluation.py [--tasks-dir evaluation/tasks] [--repo demo-repository]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.evaluation.baseline_runner import collect_pristine_test_ids, run_baseline_task  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-dir", default=str(PROJECT_ROOT / "evaluation" / "tasks"))
    parser.add_argument("--repo", default=str(PROJECT_ROOT / "demo-repository"))
    args = parser.parse_args()

    tasks_dir = Path(args.tasks_dir)
    tasks = sorted(tasks_dir.glob("task_*.json"))
    if not tasks:
        print(f"No tasks found in {tasks_dir}")
        sys.exit(1)

    results_dir = PROJECT_ROOT / "evaluation" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    repo_path = Path(args.repo)

    print(f"Collecting pristine test suite from {args.repo} ...")
    pristine_tests = collect_pristine_test_ids(repo_path)
    print(f"Pristine test suite: {len(pristine_tests)} tests")

    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    task_results = []
    for task_file in tasks:
        task = json.loads(task_file.read_text())
        print(f"\n=== [baseline] Running {task['id']}: {task['title']} ===")
        result = run_baseline_task(task, repo_path, pristine_tests, run_id)
        print(f"    completed={result['completed']} final_status={result['final_status']}")
        task_results.append(result)

    n = len(task_results)
    completed = sum(1 for r in task_results if r["completed"])
    validated = sum(1 for r in task_results if r["final_validation"] == "passed")
    times = [r["execution_time_ms"] for r in task_results if r["execution_time_ms"] is not None]
    avg_time = sum(times) / len(times) if times else None

    precisions = [r["retrieval_precision_at_k"] for r in task_results if r["retrieval_precision_at_k"] is not None]
    recalls = [r["retrieval_recall_at_k"] for r in task_results if r["retrieval_recall_at_k"] is not None]
    unnecessary = [r["unnecessary_modification_ratio"] for r in task_results if r["unnecessary_modification_ratio"] is not None]
    regressed_count = sum(1 for r in task_results if r["regressed_tests"])

    summary = {
        "arm": "baseline",
        "timestamp": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "tasks_total": n,
        "tasks_completed": completed,
        "task_completion_rate": round(completed / n, 3),
        "validation_success_rate": round(validated / n, 3),
        "avg_human_interventions": 0.0,
        "avg_repair_attempts": 0.0,
        "avg_execution_time_ms": round(avg_time, 1) if avg_time is not None else None,
        "avg_retrieval_precision_at_k": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "avg_retrieval_recall_at_k": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "avg_unnecessary_modification_ratio_proxy": round(sum(unnecessary) / len(unnecessary), 3) if unnecessary else None,
        "regression_rate": round(regressed_count / n, 3),
        "regression_rate_note": (
            "Computed against the same pristine-repository baseline test collection "
            f"({len(pristine_tests)} tests) used by the Intent2Deploy arm — a test is "
            "counted regressed only if it existed before this task's changes and shows "
            "FAILED in the single post-change pytest run."
        ),
        "avg_guardrail_warnings": None,
        "avg_guardrail_blocked": None,
        "guardrail_note": "Not applicable — the baseline arm has no guardrail engine by design.",
        "resource_consumption": "Not available from provider (LLM_MODE=mock)",
        "results": task_results,
    }

    out_file = results_dir / f"baseline_run_{run_id}.json"
    out_file.write_text(json.dumps(summary, indent=2))

    md_lines = [
        "# Baseline Evaluation Run Summary",
        "",
        f"Timestamp: {summary['timestamp']}",
        f"Tasks: {summary['tasks_total']}",
        f"Completed: {summary['tasks_completed']}",
        f"Task Completion Rate: {summary['task_completion_rate'] * 100:.0f}%",
        f"Validation Success Rate: {summary['validation_success_rate'] * 100:.0f}%",
        "Average Human Interventions: 0 (not applicable — baseline has no approval checkpoints)",
        "Average Repair Attempts: 0 (not applicable — baseline has no repair loop)",
        f"Average Execution Time: {summary['avg_execution_time_ms']}ms",
        f"Retrieval Precision@K (avg): {summary['avg_retrieval_precision_at_k']}",
        f"Retrieval Recall@K (avg): {summary['avg_retrieval_recall_at_k']}",
        f"Unnecessary Modification Ratio (proxy, avg): {summary['avg_unnecessary_modification_ratio_proxy']}",
        f"Regression Rate: {summary['regression_rate'] * 100:.0f}% ({summary['regression_rate_note']})",
        f"Guardrails: {summary['guardrail_note']}",
        f"Resource Consumption: {summary['resource_consumption']}",
        "",
        "| Task | Category | Completed | Final Status |",
        "|---|---|---|---|",
    ]
    for r in task_results:
        md_lines.append(f"| {r['task_id']} | {r['category']} | {r['completed']} | {r['final_status']} |")
    (results_dir / f"baseline_run_{run_id}_summary.md").write_text("\n".join(md_lines))

    print("\n" + "\n".join(md_lines))
    print(f"\nFull results written to {out_file}")


if __name__ == "__main__":
    main()
