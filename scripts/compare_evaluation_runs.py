#!/usr/bin/env python3
"""Compute the baseline-vs-Intent2Deploy comparison, interpretation, and
failure analysis described in docs/EXPERIMENTAL_EVALUATION.md.

Reads the most recent `run_<timestamp>.json` (Intent2Deploy, written by
scripts/run_evaluation.py) and `baseline_run_<timestamp>.json` (baseline,
written by scripts/run_baseline_evaluation.py) from evaluation/results/,
and writes:

    evaluation/results/experiment_summary.json  (machine-readable)
    evaluation/results/experiment_summary.md    (human-readable)

Every number in the output is read from those two input files or derived
from them by a fixed, documented formula (see METRICS below) — nothing
here is invented, estimated, or hardcoded. If a required input file is
missing, this script says so and exits rather than fabricating a result.

Usage:
    python scripts/compare_evaluation_runs.py [--results-dir evaluation/results]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RESEARCH_QUESTION = (
    "How reliably can an LLM transform natural-language developer intent "
    "into a validated, multi-stage AI-DevOps workflow with minimal human "
    "intervention?"
)

# Each metric: (json field in run summary, label, unit, formula, data source, interpretation hint)
METRICS = [
    (
        "task_completion_rate",
        "Task completion rate",
        "fraction of tasks",
        "completed_tasks / total_tasks, where a task counts as completed only if "
        "validation passed AND at least one real (non-zero-confidence) change was applied",
        "run summary (tasks_completed / tasks_total)",
        "Higher is better. Answers the research question's 'how reliably' directly.",
    ),
    (
        "code_correctness_rate",
        "Code correctness (structural proxy)",
        "fraction of tasks",
        "completed AND (no expected_files listed OR at least one expected_file was "
        "actually part of the applied change)",
        "computed by this script from touched_expected_files + completed per task",
        "A structural proxy, not a semantic grading of acceptance-criteria text — see "
        "docs/EXPERIMENTAL_EVALUATION.md 'Metric definitions' for the stated limitation.",
    ),
    (
        "validation_success_rate",
        "Test / validation pass rate",
        "fraction of tasks",
        "tasks whose final validation run exited 0 / total_tasks",
        "run summary (final_validation == 'passed')",
        "Includes trivial passes where nothing was changed — see interpretation notes.",
    ),
    (
        "avg_retrieval_recall_at_k",
        "File-selection recall",
        "fraction (0-1), averaged over tasks with ground truth",
        "|selected_files ∩ expected_files| / |expected_files|, per task, then averaged",
        "run summary (avg_retrieval_recall_at_k)",
        "Did the system find the files a human curator marked as relevant?",
    ),
    (
        "avg_retrieval_precision_at_k",
        "File-selection precision",
        "fraction (0-1), averaged over tasks with ground truth",
        "|selected_files ∩ expected_files| / |selected_files|, per task, then averaged",
        "run summary (avg_retrieval_precision_at_k)",
        "Of the files the system looked at, how many were actually relevant?",
    ),
    (
        "avg_unnecessary_modification_ratio_proxy",
        "Unnecessary modifications (proxy)",
        "fraction of changed files, averaged",
        "|changed_files - expected_files| / |changed_files|, per task, then averaged",
        "run summary (avg_unnecessary_modification_ratio_proxy)",
        "Proxy: expected_files is a human-curated approximation, not perfect ground truth.",
    ),
    (
        "avg_human_interventions",
        "Human intervention points",
        "count, averaged per task",
        "sum(Workflow.human_intervention_count) / total_tasks",
        "run summary (avg_human_interventions)",
        "Lower is better for 'minimal human intervention', but zero is not necessarily "
        "desirable — see interpretation.",
    ),
    (
        "regression_rate",
        "Regression rate",
        "fraction of tasks",
        "tasks where a pristine-passing test shows FAILED after the change / total_tasks",
        "run summary (regression_rate), both arms checked against the same pristine test set",
        "Lower is better. Real (not proxy) regression detection.",
    ),
    (
        "avg_execution_time_ms",
        "Execution time",
        "milliseconds, averaged per task",
        "wall-clock time per task, time.monotonic() around the full run",
        "run summary (avg_execution_time_ms)",
        "Lower is faster. Not a measure of quality by itself.",
    ),
]


def _pct_improvement(baseline: float | None, system: float | None) -> float | None:
    """Percentage change from baseline to system. Only computed where
    mathematically meaningful (baseline must be a nonzero number)."""
    if baseline is None or system is None:
        return None
    if baseline == 0:
        return None  # cannot express a percentage change from zero without fabricating a notion of scale
    return round(((system - baseline) / abs(baseline)) * 100, 1)


def _code_correctness_rate(results: list[dict]) -> float:
    if not results:
        return 0.0
    correct = 0
    for r in results:
        touched = r.get("touched_expected_files")
        ok = bool(r.get("completed")) and (touched is None or touched > 0)
        if ok:
            correct += 1
    return round(correct / len(results), 3)


def _latest(results_dir: Path, pattern: str, exclude_prefix: str | None = None) -> Path | None:
    candidates = sorted(results_dir.glob(pattern), reverse=True)
    if exclude_prefix:
        candidates = [c for c in candidates if not c.name.startswith(exclude_prefix)]
    return candidates[0] if candidates else None


def _classify_failure(task_id: str, baseline_r: dict | None, system_r: dict | None) -> dict:
    """Rule-based (not LLM-judged, not invented) classification of why a
    task failed or was only partially successful, using only fields
    already present in the two result records."""

    def reason_for(r: dict | None, arm: str) -> str:
        if r is None:
            return f"no {arm} result recorded for this task"
        if r.get("error"):
            return f"runner error: {r['error']}"
        confidences = r.get("changes_confidence") or []
        if not confidences or all(c == 0 for c in confidences):
            return "no grounded mock code-generation strategy matched this intent category (honest no-op, not a crash)"
        if r.get("final_validation") == "failed":
            regressed = r.get("regressed_tests") or []
            if regressed:
                return f"validation failed: {len(regressed)} previously-passing test(s) regressed ({', '.join(regressed[:3])}{'…' if len(regressed) > 3 else ''})"
            return "validation failed (test run exited non-zero, no specific pristine-test regression matched)"
        touched = r.get("touched_expected_files")
        if touched is not None and touched == 0:
            return "a change was generated and validated, but it did not touch any of the task's expected files"
        return "did not reach the completed state for an unrecorded reason — see raw result"

    return {
        "task_id": task_id,
        "baseline_completed": bool(baseline_r.get("completed")) if baseline_r else None,
        "intent2deploy_completed": bool(system_r.get("completed")) if system_r else None,
        "baseline_failure_reason": None if (baseline_r and baseline_r.get("completed")) else reason_for(baseline_r, "baseline"),
        "intent2deploy_failure_reason": None if (system_r and system_r.get("completed")) else reason_for(system_r, "Intent2Deploy"),
    }


def build_comparison(baseline: dict, system: dict) -> dict:
    baseline_results = {r["task_id"]: r for r in baseline["results"]}
    system_results = {r["task_id"]: r for r in system["results"]}
    all_task_ids = sorted(set(baseline_results) | set(system_results))

    baseline_summary = dict(baseline)
    system_summary = dict(system)
    baseline_summary["code_correctness_rate"] = _code_correctness_rate(baseline["results"])
    system_summary["code_correctness_rate"] = _code_correctness_rate(system["results"])

    table = []
    for field, label, unit, formula, source, note in METRICS:
        b = baseline_summary.get(field)
        s = system_summary.get(field)
        row = {
            "metric": label,
            "field": field,
            "unit": unit,
            "formula": formula,
            "data_source": source,
            "interpretation_note": note,
            "baseline": b,
            "intent2deploy": s,
            "absolute_difference": (round(s - b, 3) if isinstance(b, (int, float)) and isinstance(s, (int, float)) else None),
            "percent_improvement": _pct_improvement(b, s),
        }
        table.append(row)

    # ---- failure case analysis -------------------------------------------------
    failures = []
    for task_id in all_task_ids:
        b_r = baseline_results.get(task_id)
        s_r = system_results.get(task_id)
        b_ok = bool(b_r and b_r.get("completed"))
        s_ok = bool(s_r and s_r.get("completed"))
        if b_ok and s_ok:
            continue  # both succeeded — not a failure case
        case = _classify_failure(task_id, b_r, s_r)
        case["title"] = (s_r or b_r or {}).get("title", task_id)
        case["category"] = (s_r or b_r or {}).get("category", "")
        case["baseline_result"] = b_r
        case["intent2deploy_result"] = s_r
        failures.append(case)

    # ---- interpretation (templated from real numbers, not free text) -----------
    def fmt_pct(x):
        return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "n/a"

    interpretation = []

    tc_b, tc_s = baseline_summary["task_completion_rate"], system_summary["task_completion_rate"]
    if tc_s > tc_b:
        interpretation.append(
            f"Task completion: the results indicate a higher completion rate under Intent2Deploy than under "
            f"the baseline in this benchmark ({fmt_pct(tc_s)} vs {fmt_pct(tc_b)}, n={system['tasks_total']} tasks)."
        )
    elif tc_s < tc_b:
        interpretation.append(
            f"Task completion: in this benchmark, the baseline completed a higher fraction of tasks than "
            f"Intent2Deploy ({fmt_pct(tc_b)} vs {fmt_pct(tc_s)}). This is reported as observed; see failure "
            f"analysis for why."
        )
    else:
        interpretation.append(f"Task completion: both arms completed the same fraction of tasks in this benchmark ({fmt_pct(tc_s)}).")

    rec_b, rec_s = baseline_summary.get("avg_retrieval_recall_at_k"), system_summary.get("avg_retrieval_recall_at_k")
    prec_b, prec_s = baseline_summary.get("avg_retrieval_precision_at_k"), system_summary.get("avg_retrieval_precision_at_k")
    if rec_b is not None and rec_s is not None:
        if rec_s > rec_b:
            interpretation.append(
                f"File selection: Intent2Deploy's hybrid retrieval achieved higher recall of the expected files "
                f"than the baseline's keyword-matched context ({rec_s:.2f} vs {rec_b:.2f})."
            )
        elif rec_s < rec_b:
            interpretation.append(
                f"File selection: in this benchmark the baseline's naive context selection achieved recall "
                f"{rec_b:.2f} against Intent2Deploy's {rec_s:.2f} — the retrieval pipeline did not show an "
                f"advantage on recall for these tasks."
            )
        else:
            interpretation.append(f"File selection: recall was equal between arms ({rec_s:.2f}).")
    else:
        interpretation.append("File selection: recall could not be compared (missing retrieval data in one arm).")

    vr_b, vr_s = baseline_summary["validation_success_rate"], system_summary["validation_success_rate"]
    interpretation.append(
        f"Validation reliability: validation (test-run) pass rate was {fmt_pct(vr_s)} under Intent2Deploy and "
        f"{fmt_pct(vr_b)} under the baseline. Note both figures include trivial passes where no change was made "
        f"(see 'Measured results' limitations) — this field should be read together with task completion rate, "
        f"not alone."
    )

    um_b, um_s = baseline_summary.get("avg_unnecessary_modification_ratio_proxy"), system_summary.get("avg_unnecessary_modification_ratio_proxy")
    if um_b is not None and um_s is not None:
        if um_s < um_b:
            interpretation.append(
                f"Unnecessary modifications: Intent2Deploy's changes stayed closer to the expected file scope "
                f"than the baseline's in this benchmark (proxy ratio {um_s:.2f} vs {um_b:.2f})."
            )
        elif um_s > um_b:
            interpretation.append(
                f"Unnecessary modifications: the baseline's changes stayed closer to the expected file scope "
                f"than Intent2Deploy's in this benchmark (proxy ratio {um_b:.2f} vs {um_s:.2f})."
            )
        else:
            interpretation.append(f"Unnecessary modifications: both arms scored equally on this proxy ({um_s:.2f}).")
    else:
        interpretation.append("Unnecessary modifications: no task in this run produced a comparable measurement in both arms.")

    interpretation.append(
        f"Human intervention: the baseline requires 0 approval checkpoints by construction (it has none); "
        f"Intent2Deploy recorded an average of {system_summary['avg_human_interventions']} intervention point(s) "
        f"per task (plan, change, and commit approval in an unattended benchmark run — see "
        f"docs/EXPERIMENTAL_EVALUATION.md). This is a structural trade-off, not a reliability failure: the "
        f"approval points exist specifically so a human can catch problems the baseline has no mechanism to "
        f"surface at all."
    )

    rr_b, rr_s = baseline_summary["regression_rate"], system_summary["regression_rate"]
    interpretation.append(
        f"Regressions: regression rate was {fmt_pct(rr_s)} (Intent2Deploy) vs {fmt_pct(rr_b)} (baseline) against "
        f"the same pristine test collection."
        + (
            " Intent2Deploy's bounded repair loop (up to 2 attempts) had the opportunity to recover from a "
            "failing validation run before this was measured; the baseline has no equivalent mechanism."
            if system_summary.get("avg_repair_attempts", 0) > 0
            else " No repair attempts were triggered in this particular run."
        )
    )

    where_baseline_won = [row["metric"] for row in table if isinstance(row["baseline"], (int, float)) and isinstance(row["intent2deploy"], (int, float)) and row["field"] not in ("regression_rate", "avg_execution_time_ms", "avg_unnecessary_modification_ratio_proxy") and row["baseline"] > row["intent2deploy"]]
    where_baseline_won += [row["metric"] for row in table if row["field"] in ("regression_rate", "avg_execution_time_ms", "avg_unnecessary_modification_ratio_proxy") and isinstance(row["baseline"], (int, float)) and isinstance(row["intent2deploy"], (int, float)) and row["baseline"] < row["intent2deploy"]]
    if where_baseline_won:
        interpretation.append(
            "Where the baseline outperformed Intent2Deploy in this benchmark: " + "; ".join(where_baseline_won) + "."
        )
    else:
        interpretation.append("The baseline did not outperform Intent2Deploy on any measured metric in this run.")

    interpretation.append(
        f"Limitation: this benchmark has n={system['tasks_total']} tasks against a single fixture repository "
        "in LLM_MODE=mock. No statistical significance test is reported because the sample size does not "
        "support one; all comparisons above are descriptive, not inferential. See "
        "docs/EXPERIMENTAL_EVALUATION.md for the full limitations list."
    )

    # ---- research question alignment (Part 10) ----------------------------
    alignment = [
        {
            "concept": "Reliability",
            "hypothesis": "Intent2Deploy completes a higher fraction of tasks, without crashing or silently fabricating output, than a non-orchestrated baseline.",
            "metrics": ["task_completion_rate", "code_correctness_rate"],
            "result": f"completion {fmt_pct(tc_s)} (Intent2Deploy) vs {fmt_pct(tc_b)} (baseline); correctness-proxy {fmt_pct(system_summary['code_correctness_rate'])} vs {fmt_pct(baseline_summary['code_correctness_rate'])}",
        },
        {
            "concept": "Validated workflow",
            "hypothesis": "Changes that complete are actually test-passing and do not regress prior behavior.",
            "metrics": ["validation_success_rate", "regression_rate"],
            "result": f"validation pass rate {fmt_pct(vr_s)} vs {fmt_pct(vr_b)}; regression rate {fmt_pct(rr_s)} vs {fmt_pct(rr_b)}",
        },
        {
            "concept": "Multi-stage AI-DevOps workflow",
            "hypothesis": "Retrieval, planning, and guardrail stages measurably change what gets selected and changed, compared to a single-shot approach.",
            "metrics": ["avg_retrieval_precision_at_k", "avg_retrieval_recall_at_k", "avg_unnecessary_modification_ratio_proxy"],
            "result": f"recall {rec_s if rec_s is not None else 'n/a'} vs {rec_b if rec_b is not None else 'n/a'}; precision {prec_s if prec_s is not None else 'n/a'} vs {prec_b if prec_b is not None else 'n/a'}",
        },
        {
            "concept": "Minimal human intervention",
            "hypothesis": "Human involvement is bounded and purposeful (approval checkpoints), not proportional to failure.",
            "metrics": ["avg_human_interventions"],
            "result": f"{system_summary['avg_human_interventions']} intervention point(s)/task (Intent2Deploy) vs 0 (baseline, structurally absent)",
        },
    ]

    return {
        "research_question": RESEARCH_QUESTION,
        "generated_at": datetime.utcnow().isoformat(),
        "baseline_run_file": baseline_summary.get("_source_file"),
        "intent2deploy_run_file": system_summary.get("_source_file"),
        "tasks_total_baseline": baseline["tasks_total"],
        "tasks_total_intent2deploy": system["tasks_total"],
        "comparison_table": table,
        "failure_analysis": failures,
        "interpretation": interpretation,
        "research_question_alignment": alignment,
        "statistical_note": (
            "No significance testing is applied (n is too small to support it). All differences are reported "
            "as descriptive observations from this specific benchmark run, not as generalizable claims."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=str(PROJECT_ROOT / "evaluation" / "results"))
    args = parser.parse_args()
    results_dir = Path(args.results_dir)

    system_file = _latest(results_dir, "run_*.json", exclude_prefix="baseline_run_")
    baseline_file = _latest(results_dir, "baseline_run_*.json")

    if system_file is None or baseline_file is None:
        missing = []
        if system_file is None:
            missing.append("an Intent2Deploy run (evaluation/results/run_*.json — run `python scripts/run_evaluation.py`)")
        if baseline_file is None:
            missing.append("a baseline run (evaluation/results/baseline_run_*.json — run `python scripts/run_baseline_evaluation.py`)")
        print("Cannot build comparison — missing: " + "; ".join(missing))
        sys.exit(1)

    system = json.loads(system_file.read_text())
    baseline = json.loads(baseline_file.read_text())
    system["_source_file"] = system_file.name
    baseline["_source_file"] = baseline_file.name

    comparison = build_comparison(baseline, system)

    out_json = results_dir / "experiment_summary.json"
    out_json.write_text(json.dumps(comparison, indent=2))

    md = [
        "# Experiment Summary — Baseline vs Intent2Deploy",
        "",
        f"Research question: {RESEARCH_QUESTION}",
        "",
        f"Intent2Deploy run: `{system_file.name}` ({system['tasks_total']} tasks)",
        f"Baseline run: `{baseline_file.name}` ({baseline['tasks_total']} tasks)",
        "",
        "## Results table",
        "",
        "| Metric | Baseline | Intent2Deploy | Abs. diff | % change |",
        "|---|---|---|---|---|",
    ]
    for row in comparison["comparison_table"]:
        md.append(
            f"| {row['metric']} | {row['baseline']} | {row['intent2deploy']} | "
            f"{row['absolute_difference'] if row['absolute_difference'] is not None else 'n/a'} | "
            f"{(str(row['percent_improvement']) + '%') if row['percent_improvement'] is not None else 'n/a'} |"
        )
    md += ["", "## Interpretation", ""]
    md += [f"- {line}" for line in comparison["interpretation"]]
    md += ["", "## Research question alignment", ""]
    for row in comparison["research_question_alignment"]:
        md.append(f"- **{row['concept']}** — {row['hypothesis']} → {row['result']}")
    md += ["", "## Failure / partial-success cases", ""]
    if not comparison["failure_analysis"]:
        md.append("No failure cases: every task completed in both arms.")
    for case in comparison["failure_analysis"]:
        md.append(f"- **{case['task_id']} — {case['title']}** ({case['category']})")
        md.append(f"  - baseline: completed={case['baseline_completed']}" + (f" — {case['baseline_failure_reason']}" if case["baseline_failure_reason"] else ""))
        md.append(f"  - Intent2Deploy: completed={case['intent2deploy_completed']}" + (f" — {case['intent2deploy_failure_reason']}" if case["intent2deploy_failure_reason"] else ""))
    md += ["", f"_{comparison['statistical_note']}_"]

    out_md = results_dir / "experiment_summary.md"
    out_md.write_text("\n".join(md))

    print("\n".join(md))
    print(f"\nWritten: {out_json}\nWritten: {out_md}")


if __name__ == "__main__":
    main()
