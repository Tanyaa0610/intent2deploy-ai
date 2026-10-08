"""Workflow-specific evaluation against the faculty-defined framework.

Seven fixed categories (Explanation, Code Retrieval, Dependency
Understanding, Bug Analysis, Code Generation, Refactoring, RAG-based
Question) are scored from ONE workflow's already-persisted evidence —
the same `build_report()` trace used by the Final Report (single source
of truth; see app.services.reporting). No second tracking system.

Every metric in this module is one of exactly four kinds, and the exact
word is used consistently in `metric_status`, category `metrics`, and
`independent_checks`:

- "measured"   — directly calculated from persisted workflow evidence
  (test counts parsed from real pytest output, guardrail check counts,
  diff line counts, latencies, grounding/unsupported-reference rates).
- "evidence-based" — a deterministic 0-100 rubric score computed from
  the presence/content of real persisted evidence when no independent
  ground truth exists (e.g. "did the plan document acceptance
  criteria?"). Never claimed to be independently-verified correctness.
- "ground_truth_dependent" — the formula is well-defined but requires an
  independently-labelled reference this workflow does not have (true
  Recall@K/Precision@K need expected-file ground truth; regression RATE
  needs per-test identity matching across runs; root-cause/dependency/
  explanation *correctness* need an independent judge).
- "unavailable" — the required evidence was never persisted at all
  (provider-reported token usage).

No LLM, no randomness, no invented numbers, no "unavailable = 0"
anywhere in this module. `metric_status` and the unavailable count are
built dynamically from what was actually computed below — nothing is
hardcoded to a fixed list or a fixed count.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlmodel import Session

from app.services.codegen.diffing import count_patch_lines
from app.services.orchestrator import get_workflow
from app.services.reporting import build_report

SUFFICIENT_STATES = {
    "VALIDATION_PASSED",
    "VALIDATION_FAILED",
    "AWAITING_COMMIT_APPROVAL",
    "COMMITTED",
    "CI_RUNNING",
    "COMPLETED",
    "FAILED",
}

CATEGORY_KEYS = [
    "explanation",
    "code_retrieval",
    "dependency_understanding",
    "bug_analysis",
    "code_generation",
    "refactoring",
    "rag_based_question",
]

CATEGORY_LABELS = {
    "explanation": "Explanation",
    "code_retrieval": "Code Retrieval",
    "dependency_understanding": "Dependency Understanding",
    "bug_analysis": "Bug Analysis",
    "code_generation": "Code Generation",
    "refactoring": "Refactoring",
    "rag_based_question": "RAG-based Question",
}


# =============================================================================
# Generic weighted rubric: each criterion is (label, fraction, weight).
# fraction is 1.0 (fully met), 0.0 (not met), something in between for a
# partial/proportional criterion (e.g. a real pass rate), or None when the
# criterion genuinely does not apply to this workflow — those are excluded
# from the denominator (renormalized), never scored as 0.
# =============================================================================


def _rubric_score(criteria: list[tuple[str, float | None, int]]) -> tuple[int | None, bool, list[dict]]:
    applicable = [(label, frac, weight) for label, frac, weight in criteria if frac is not None]
    checklist = []
    for label, frac, weight in criteria:
        if frac is None:
            result = "N/A"
        elif frac >= 1.0:
            result = "met"
        elif frac <= 0.0:
            result = "not met"
        else:
            result = f"{round(frac * 100)}% met"
        checklist.append({"label": label, "result": result, "weight": weight})

    if not applicable:
        return None, False, checklist

    total_weight = sum(w for _, _, w in applicable)
    earned = sum(frac * w for _, frac, w in applicable)
    score = round(100 * earned / total_weight) if total_weight else None
    is_partial = len(applicable) < len(criteria)
    return score, is_partial, checklist


def _criteria_met_count(checklist: list[dict]) -> tuple[int, int]:
    """(met, applicable) — "met" counts only fully-satisfied criteria;
    N/A criteria are excluded from the denominator, matching _rubric_score."""
    applicable = [c for c in checklist if c["result"] != "N/A"]
    met = sum(1 for c in applicable if c["result"] == "met")
    return met, len(applicable)


def _cat(
    status: str,
    score: int | None,
    is_partial: bool,
    criteria: list[dict],
    metrics: dict,
    independent_checks: dict,
    evidence: dict,
    note: str,
    limitations: list[str] | None = None,
) -> dict:
    return {
        "status": status,
        "score": score,
        "is_partial": is_partial if status == "evaluated" else False,
        "criteria": criteria,
        "metrics": metrics,
        "independent_checks": independent_checks,
        "evidence": evidence,
        "note": note,
        "_limitations": limitations or [],  # consumed by the caller, not re-serialized under this key
    }


def _changed_items(trace: dict) -> list[dict]:
    cg = trace.get("code_generation") or {}
    return cg.get("files_modified") or cg.get("files_proposed_not_applied") or []


def _module_group(path: str) -> str:
    """Deterministic module/component grouping from a real file path —
    e.g. "src/shopflow/services/payment_service.py" -> "services",
    "tests/test_payments.py" -> "tests", "README.md" -> "root". Used to
    detect cross-module relationships (e.g. a service, its external
    integration, its API route, and its tests) directly from retrieval
    evidence, since this repository's architecture scan produces one
    single top-level component (src/shopflow/) rather than one component
    per sub-package — grouping by path is the real, available signal.
    """
    parts = path.split("/")
    if len(parts) <= 1:
        return "root"
    if parts[0] == "src" and len(parts) >= 3:
        return parts[2]
    return parts[0]


_PYTEST_SUMMARY_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")


def _parse_pytest_summary(stdout: str) -> dict | None:
    """Parse pytest's own final summary line (e.g. "76 passed, 4 warnings
    in 11.85s" or "2 failed, 74 passed in 12.01s") for real executed/
    passed/failed/skipped counts. Returns None if no recognizable summary
    is present — never guessed from a bare pass/fail status."""
    counts: dict[str, int] = {}
    for n, label in _PYTEST_SUMMARY_RE.findall(stdout):
        key = "error" if label.startswith("error") else label
        counts[key] = counts.get(key, 0) + int(n)
    if not counts:
        return None
    passed = counts.get("passed", 0) + counts.get("xpassed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    skipped = counts.get("skipped", 0) + counts.get("xfailed", 0)
    return {"executed": passed + failed + skipped, "passed": passed, "failed": failed, "skipped": skipped}


def _latest_unit_test_run(trace: dict) -> dict | None:
    runs = [r for r in (trace.get("validation") or {}).get("runs", []) if r["stage"] == "unit_tests"]
    if not runs:
        return None
    latest_attempt = max(r["attempt"] for r in runs)
    latest = [r for r in runs if r["attempt"] == latest_attempt]
    return latest[-1]


def _diff_line_counts(patch: str) -> tuple[int, int]:
    added = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    return added, removed


def _regression_gate_status(trace: dict) -> str:
    """The orchestrator already evaluates a real pre-change vs post-change
    regression GATE (guardrail CICD-02: baseline_tests_passed vs the
    final unit_tests result) and persists it as a GuardrailCheck row —
    reused here verbatim. This is a genuine measured binary gate result;
    it is NOT the same as a regression RATE (percentage), which would
    require per-test identity matching across runs that this system does
    not persist (pytest's summary line gives aggregate counts only, not
    which named tests passed before and fail now)."""
    check = next((g for g in trace.get("guardrail_results", []) if g["guardrail_id"] == "CICD-02"), None)
    if check is None:
        return "Not recorded"
    return check["status"]


# =============================================================================
# 1. EXPLANATION
# =============================================================================


def _eval_explanation(trace: dict) -> dict:
    plan = trace.get("engineering_plan")
    if plan is None:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "No engineering plan was generated for this workflow.")

    arch = trace.get("architecture_analysis") or {}
    risks = trace.get("risk_analysis") or []
    has_arch_or_risk = bool((arch.get("components") if isinstance(arch, dict) else None)) or bool(risks)

    criteria = [
        ("Developer intent/problem represented", 1.0 if trace.get("intent", "").strip() else 0.0, 20),
        ("Proposed objective/solution represented", 1.0 if plan.get("summary", "").strip() else 0.0, 20),
        ("Acceptance criteria present", 1.0 if plan.get("acceptance_criteria") else 0.0, 20),
        ("Relevant assumptions/context present", 1.0 if plan.get("assumptions") else 0.0, 20),
        ("Architecture/risk reasoning present", 1.0 if has_arch_or_risk else 0.0, 20),
    ]
    score, is_partial, checklist = _rubric_score(criteria)
    met, applicable = _criteria_met_count(checklist)

    latency_ms = trace.get("timing_ms", {}).get("planning")

    # Grounding check (not "hallucination rate" — see module docstring and
    # §8 of the spec): the planner already tracks, per workflow, which
    # LLM-referenced files turned out not to exist in retrieval evidence
    # and were stripped before use (AuditEvent
    # PLAN_GENERATED.metadata.invented_files_removed) — a real,
    # deterministic grounding signal, not an estimate.
    invented = trace.get("invented_files_removed") or []
    referenced = plan.get("files_likely_to_change", [])
    total_referenced = len(referenced) + len(invented)
    grounded_rate = round(100 * len(referenced) / total_referenced) if total_referenced else None
    unsupported_rate = round(100 * len(invented) / total_referenced) if total_referenced else None

    metrics = {
        "explanation_evidence_coverage": f"{score}% ({met}/{applicable} criteria met)" if score is not None else "N/A",
        "response_latency_ms": latency_ms if latency_ms is not None else "Not recorded",
    }
    if grounded_rate is not None:
        metrics["grounded_repository_reference_rate"] = f"{grounded_rate}% ({len(referenced)}/{total_referenced} referenced file(s) grounded in retrieval evidence)"
        metrics["unsupported_repository_reference_rate"] = f"{unsupported_rate}% ({len(invented)}/{total_referenced} referenced file(s) not grounded)"

    independent_checks = {
        "correctness": "Not independently verified",
        "relevance": "Not independently judged",
        "true_hallucination_rate": "Not independently measurable",
    }

    evidence = {
        "plan_summary": plan.get("summary"),
        "classified_category": (trace.get("intent_understanding") or {}).get("classified_category"),
        "acceptance_criteria": plan.get("acceptance_criteria", []),
        "assumptions": plan.get("assumptions", []),
    }
    limitations = [
        "Explanation correctness/relevance are not independently verified — no ground-truth answer or independent judge is available for ad-hoc workflows.",
        "True hallucination rate is not independently measurable — repository-reference grounding (above) is a real, deterministic signal but is not equivalent to general hallucination detection, which needs an independent reference or judge.",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Evidence-based explanation coverage score — reflects whether the explanation's expected "
        "components are present, not semantic correctness.",
        limitations,
    )


# =============================================================================
# 2. CODE RETRIEVAL
# =============================================================================


def _eval_code_retrieval(trace: dict) -> dict:
    rag = trace.get("repository_rag") or {}
    items = rag.get("evidence") or []
    if not items:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "No retrieval evidence was recorded for this workflow.")

    changed_files = {c["file"] for c in _changed_items(trace)}
    retrieved_files = sorted({e["file"] for e in items})
    has_changes = bool(changed_files)

    grounding_rate = None
    if has_changes:
        overlap = set(retrieved_files) & changed_files
        grounding_rate = round(100 * len(overlap) / len(changed_files))

    multi_signal = any(e["retrieval_method"].count("+") >= 1 for e in items) or len({e["retrieval_method"] for e in items}) > 1

    criteria = [
        ("Relevant retrieved evidence exists", 1.0 if items else 0.0, 40),
        ("Retrieved evidence overlaps changed files", (grounding_rate / 100) if has_changes else None, 30),
        ("Multiple retrieval signals support the result", 1.0 if multi_signal else 0.0, 20),
        ("Retrieval evidence strongly grounded in the change", (1.0 if grounding_rate >= 50 else (0.5 if grounding_rate and grounding_rate > 0 else 0.0)) if has_changes else None, 10),
    ]
    score, is_partial, checklist = _rubric_score(criteria)

    avg_score = round(sum(e["score"] for e in items) / len(items), 3)

    metrics = {
        "retrieval_evidence_score": f"{score}/100" if score is not None else "N/A",
        "grounding_rate": f"{grounding_rate}%" if grounding_rate is not None else "N/A (no changed files to compare against)",
        "mean_retrieval_ranking_score": f"{avg_score} (0–1 scale, internal ranking signal — not an accuracy percentage)",
        "retrieval_latency_ms": rag.get("retrieval_duration_ms") if rag.get("retrieval_duration_ms") is not None else "Not recorded",
        "chunks_retrieved": len(items),
    }
    independent_checks = {
        "recall_at_k": "Unavailable",
        "precision_at_k": "Unavailable",
    }
    evidence = {"files_retrieved": retrieved_files}
    limitations = [
        "Recall@K / Precision@K are unavailable for this ad-hoc workflow — no workflow-specific expected-file ground truth is persisted in the database (expected-file sets exist only in-memory for the 21-task benchmark run, never written to a workflow row; see Benchmark / Research Evaluation for the benchmark's real Recall@K/Precision@K).",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Evidence-based retrieval score — combines whether relevant evidence was found, whether it overlaps "
        "the actual change, and whether multiple independent retrieval signals agreed. Not a ground-truth "
        "accuracy percentage.",
        limitations,
    )


# =============================================================================
# 3. DEPENDENCY UNDERSTANDING
# =============================================================================


def _eval_dependency_understanding(trace: dict) -> dict:
    plan = trace.get("engineering_plan")
    arch = trace.get("architecture_analysis") or {}
    arch_available = isinstance(arch, dict) and "error" not in arch
    if plan is None and not arch_available:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "No plan or architecture evidence available for this workflow.")

    deps = (plan or {}).get("dependencies", [])
    external_deps = arch.get("external_dependencies", []) if arch_available else []
    components = arch.get("components", []) if arch_available else []
    changed_files = {c["file"] for c in _changed_items(trace)}
    has_changes = bool(changed_files)

    connected = False
    if has_changes and components:
        component_files = {f for comp in components for f in comp.get("files", [])}
        connected = bool(changed_files & component_files)

    multi_file_plan = len((plan or {}).get("files_likely_to_change", [])) > 1

    # Dependency/context identification is not only the (often-empty)
    # plan.dependencies list field — real cross-module relationship
    # evidence also shows up in WHICH modules retrieval connected for this
    # change (e.g. a service, its external integration, its API route,
    # and its tests). This repository's architecture scan produces one
    # single top-level component rather than one per sub-package, so path
    # -based module grouping is the actual available signal for that —
    # not an inferred/fabricated relationship, a real count of distinct,
    # retrieved modules.
    rag_files = {e["file"] for e in (trace.get("repository_rag") or {}).get("evidence", [])}
    retrieval_modules = sorted({_module_group(f) for f in rag_files})
    cross_module_evidence = len(retrieval_modules) >= 2
    dependency_identified = bool(deps) or cross_module_evidence

    criteria = [
        ("Dependency information explicitly identified", 1.0 if dependency_identified else 0.0, 25) if plan is not None else ("Dependency information explicitly identified", None, 25),
        ("Affected components connected to the change", (1.0 if connected else 0.0) if (has_changes and components) else None, 25),
        ("External/internal dependencies represented", (1.0 if external_deps else 0.0) if arch_available else None, 25),
        ("Dependency reasoning reflected in the plan", (1.0 if (deps or multi_file_plan) else 0.0) if plan is not None else None, 25),
    ]
    score, is_partial, checklist = _rubric_score(criteria)
    met, applicable = _criteria_met_count(checklist)

    metrics = {
        "dependency_evidence_coverage": f"{score}% ({met}/{applicable} criteria met)" if score is not None else "N/A",
        "dependencies_identified": len(deps),
        "distinct_modules_connected_by_retrieval": f"{len(retrieval_modules)} ({', '.join(retrieval_modules)})" if retrieval_modules else 0,
        "external_dependencies_detected": len(external_deps),
    }
    independent_checks = {"dependency_correctness": "Not independently verified"}
    evidence = {"plan_dependencies": deps, "external_dependencies": external_deps}
    limitations = [
        "Dependency correctness is not independently verified — no independent dependency ground truth exists for this workflow; the score reflects documented dependency/context coverage only.",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Evidence-based dependency/context coverage score — reflects documented dependency/context coverage, "
        "not independently-verified dependency correctness.",
        limitations,
    )


# =============================================================================
# 4. BUG ANALYSIS
# =============================================================================


def _eval_bug_analysis(trace: dict) -> dict:
    plan = trace.get("engineering_plan")
    risks = trace.get("risk_analysis") or []
    if plan is None and not risks:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "No risk analysis or plan evidence available for this workflow.")

    changed_files = {c["file"] for c in _changed_items(trace)}
    has_changes = bool(changed_files)
    risk_has_component = any(r.get("component") for r in risks)
    risk_has_mitigation = any((r.get("existing_mitigation") or "").strip() not in ("", "Not recorded") for r in risks)

    # The failure mechanism does not have to live only in a separately
    # named risk_analysis field — when the engineering plan's summary
    # (the proposed fix and why) and its acceptance criteria (the
    # specific trigger-condition -> expected-behavior pairs) are both
    # present, that together IS a description of the failure mechanism
    # and its resolution (e.g. "a client retry after a provider timeout"
    # [trigger] "does not create a duplicate charge" [resolved effect]).
    # Still real, persisted evidence — not inferred beyond what the plan
    # actually documents.
    plan_summary = (plan or {}).get("summary", "").strip()
    plan_describes_mechanism = bool(plan_summary) and bool((plan or {}).get("acceptance_criteria"))
    mechanism_described = bool(risks) or plan_describes_mechanism

    criteria = [
        ("Reported failure/problem captured", (1.0 if plan_summary else 0.0) if plan is not None else None, 20),
        ("Affected component identified", 1.0 if (risk_has_component or has_changes) else 0.0, 20),
        ("Failure mechanism / root cause described", 1.0 if mechanism_described else 0.0, 20),
        ("Mitigation proposed", 1.0 if (has_changes or risk_has_mitigation) else 0.0, 20),
        ("Mitigation aligns with acceptance criteria", (1.0 if (plan or {}).get("acceptance_criteria") else 0.0) if plan is not None else None, 20),
    ]
    score, is_partial, checklist = _rubric_score(criteria)
    met, applicable = _criteria_met_count(checklist)

    metrics = {
        "bug_analysis_evidence_coverage": f"{score}% ({met}/{applicable} criteria met)" if score is not None else "N/A",
        "risks_identified": len(risks),
        "mechanism_evidence_source": "risk analysis" if risks else ("engineering plan (summary + acceptance criteria)" if plan_describes_mechanism else "none"),
    }
    independent_checks = {"root_cause_accuracy": "Not independently verified"}
    evidence = {
        "risks": [{"title": r["title"], "severity": r["severity"], "component": r["component"]} for r in risks],
        "classified_category": (trace.get("intent_understanding") or {}).get("classified_category"),
    }
    limitations = [
        "Root-cause accuracy is not independently verified — no independent ground truth exists for root-cause correctness; the score reflects evidence-based failure-analysis coverage only.",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Evidence-based bug-analysis coverage score — reflects whether the failure, affected component, "
        "mechanism, and mitigation were captured, not independently-verified root-cause accuracy.",
        limitations,
    )


# =============================================================================
# 5. CODE GENERATION
# =============================================================================


def _eval_code_generation(trace: dict) -> dict:
    changes = _changed_items(trace)
    if not changes:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "No code changes were generated for this workflow.")

    val = trace.get("validation") or {}
    final_result = val.get("final_result")
    latest_run = _latest_unit_test_run(trace)
    test_counts = _parse_pytest_summary(latest_run["stdout"]) if latest_run and latest_run.get("stdout") else None
    test_pass_rate = round(100 * test_counts["passed"] / test_counts["executed"]) if test_counts and test_counts["executed"] else None

    validation_frac = None
    if final_result == "passed":
        validation_frac = 1.0
    elif final_result == "failed":
        validation_frac = 0.0

    criteria = [
        ("Code change generated", 1.0, 30),
        ("Generated tests executed and passed", (test_pass_rate / 100) if test_pass_rate is not None else 0.0, 30),
        ("Final validation passed", validation_frac, 25),
        ("No detected regression", None, 15),  # regression RATE requires per-test identity matching — see regression_gate for the measured binary signal
    ]
    score, is_partial, checklist = _rubric_score(criteria)

    lines_added = lines_removed = 0
    for c in changes:
        a, r = _diff_line_counts(c.get("patch", ""))
        lines_added += a
        lines_removed += r

    regression_gate = _regression_gate_status(trace)

    metrics = {
        "code_generation_score": f"{score}/100" if score is not None else "N/A",
        "files_changed": len(changes),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "validation": final_result or "Not yet run",
        "regression_gate": regression_gate,
    }
    if test_counts is not None:
        metrics["tests_executed"] = test_counts["executed"]
        metrics["tests_passed"] = test_counts["passed"]
        metrics["tests_failed"] = test_counts["failed"]
        metrics["test_pass_rate"] = f"{test_pass_rate}%"
    else:
        metrics["test_pass_rate"] = "No unit test execution recorded"

    independent_checks = {"regression_rate_percent": "Unavailable"}
    evidence = {"changed_files": [c["file"] for c in changes], "applied_to_workspace": trace.get("code_generation", {}).get("applied", False)}
    limitations = [
        "Regression rate (%) is unavailable for this ad-hoc workflow — computing it needs per-test identity "
        "matching between the pre-change and post-change test runs, which this system does not persist (only "
        "aggregate pass/fail counts per run); the Regression Gate above is a real measured pass/fail signal "
        "(pristine baseline vs. final result), not a percentage.",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Objective, measured score — generation, test execution, and validation are all directly "
        "measured from this workflow's actual results.",
        limitations,
    )


# =============================================================================
# 6. REFACTORING
# =============================================================================


def _eval_refactoring(trace: dict, intent_text: str, classified_category: str | None) -> dict:
    is_refactor = bool(classified_category and "refactor" in classified_category) or "refactor" in intent_text.lower()
    if not is_refactor:
        return _cat("not_applicable", None, False, [], {}, {}, {}, "Not applicable — workflow does not contain a refactoring objective.")

    changes = _changed_items(trace)
    if not changes:
        return _cat("not_evaluated", None, False, [], {}, {}, {}, "A refactoring objective was detected but no code changes were generated.")

    val = trace.get("validation") or {}
    final_result = val.get("final_result")
    validation_frac = 1.0 if final_result == "passed" else (0.0 if final_result == "failed" else None)

    lines_added = lines_removed = 0
    for c in changes:
        a, r = _diff_line_counts(c.get("patch", ""))
        lines_added += a
        lines_removed += r
    total_lines = sum(count_patch_lines(c.get("patch", "")) for c in changes)
    # Deterministic scope-adherence proxy from real patch size — not a
    # diff-quality judge, just a measured signal that the change stayed
    # small/targeted rather than sprawling.
    if total_lines <= 50:
        scope_frac = 1.0
    elif total_lines <= 150:
        scope_frac = 0.5
    else:
        scope_frac = 0.0

    criteria = [
        ("Validation passed", validation_frac, 40),
        ("No detected regression", None, 30),
        ("Scope adherence (targeted, minimal change)", scope_frac, 30),
    ]
    score, is_partial, checklist = _rubric_score(criteria)

    metrics = {
        "refactoring_score": f"{score}/100" if score is not None else "N/A",
        "changed_file_count": len(changes),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "validation": final_result or "Not yet run",
        "regression_gate": _regression_gate_status(trace),
    }
    independent_checks = {"regression_rate_percent": "Unavailable"}
    evidence = {"changed_files": [c["file"] for c in changes]}
    limitations = [
        "Regression rate (%) is unavailable for this ad-hoc workflow — see Code Generation.",
    ]
    return _cat(
        "evaluated", score, is_partial, checklist, metrics, independent_checks, evidence,
        "Evidence-based refactoring score — validation and the regression gate are measured; scope adherence "
        "is a deterministic proxy from the actual changed-line count, not a diff-quality judge.",
        limitations,
    )


# =============================================================================
# 7. RAG-BASED QUESTION
# =============================================================================


def _eval_rag_based_question(trace: dict) -> dict:  # noqa: ARG001 - trace kept for signature symmetry
    # The standalone Repository Intelligence -> Ask a Question feature
    # (POST /api/repository/ask) is not persisted and not linked to any
    # workflow_id anywhere in this schema — there is no table joining a
    # Q&A exchange to a Workflow row. So no workflow can genuinely contain
    # "linked" RAG-question evidence today; this is a real inspection of
    # the trace (which carries no such linkage), not a hardcoded stub.
    return _cat(
        "not_evaluated",
        None,
        False,
        [],
        {},
        {},
        {},
        "Not evaluated in this workflow — no repository-grounded question/answer evidence is linked to this "
        "workflow_id. (The standalone Repository Intelligence -> Ask a Question feature is not currently "
        "tied to a specific workflow; its results are never attributed to one unless explicitly linked.)",
    )


# =============================================================================
# Cross-cutting: guardrails and token usage (measured where real data
# exists; explicitly unavailable, never estimated, otherwise)
# =============================================================================


def _guardrail_metrics(trace: dict) -> dict:
    g = trace.get("guardrails_full") or {}
    if not g or not g.get("total"):
        return {
            "total": 0, "passed": 0, "warnings": 0, "blocked": 0, "failed": 0,
            "not_applicable": 0, "approval_required": 0, "by_category": {},
            "regression_gate": _regression_gate_status(trace),
            "note": "No guardrail checks were recorded for this workflow.",
        }
    return {
        "total": g.get("total", 0),
        "passed": g.get("passed", 0),
        "warnings": g.get("warnings", 0),
        "blocked": g.get("blocked", 0),
        "failed": g.get("failed", 0),
        "not_applicable": g.get("not_applicable", 0),
        "approval_required": g.get("approval_required", 0),
        "by_category": g.get("by_category", {}),
        "regression_gate": _regression_gate_status(trace),
    }


def _token_usage(workflow) -> dict:
    # Real provider-reported usage (LLMUsage.prompt_tokens/completion_tokens
    # with LLMUsage.available=True) is never persisted per-workflow in this
    # schema — only workflow.llm_estimated_tokens, which is by this
    # codebase's own design a character-length-based ESTIMATE (see
    # app/services/orchestrator.py), computed regardless of provider mode.
    # It is surfaced here only as an explicitly-labelled proxy, never
    # relabeled as actual usage.
    return {
        "prompt_tokens": "Not recorded",
        "completion_tokens": "Not recorded",
        "total_tokens": "Not recorded",
        "note": "Provider token usage is not recorded for this workflow — this system does not persist "
        "provider-reported per-call token counts.",
        "estimated_proxy": {
            "llm_calls": workflow.llm_call_count,
            "estimated_tokens": workflow.llm_estimated_tokens,
            "estimated_cost_usd": round(workflow.llm_estimated_cost_usd, 4),
            "note": "Character-length-based internal estimate (prompt/response text length // 4), not a "
            "provider-reported token count — never presented as actual usage.",
        },
    }


# =============================================================================
# Dynamic metric status table — built from exactly what was computed
# above; the unavailable count is len([m for m in table if m.status ==
# "unavailable"]), never a fixed number.
# =============================================================================


def _metric(metric: str, status: str, value, evidence: str) -> dict:
    return {"metric": metric, "status": status, "value": value, "evidence": evidence}


def _build_metric_status(categories: dict, guardrails: dict, token_usage: dict) -> list[dict]:
    table: list[dict] = []
    cg = categories["code_generation"]
    cr = categories["code_retrieval"]
    exp = categories["explanation"]
    dep = categories["dependency_understanding"]
    bug = categories["bug_analysis"]

    if cg["status"] == "evaluated":
        m = cg["metrics"]
        if "tests_executed" in m:
            table.append(_metric("Test Pass Rate", "measured", m["test_pass_rate"], f"{m['tests_passed']}/{m['tests_executed']} tests passed (pytest output)"))
            table.append(_metric("Tests Executed", "measured", m["tests_executed"], "Parsed from pytest summary"))
            table.append(_metric("Tests Failed", "measured", m["tests_failed"], "Parsed from pytest summary"))
        table.append(_metric("Validation Result", "measured", m["validation"], "Final validation stage result"))
        table.append(_metric("Files Changed", "measured", m["files_changed"], "Proposed/applied change set"))
        table.append(_metric("Lines Added / Removed", "measured", f"+{m['lines_added']} / -{m['lines_removed']}", "Unified diff of the applied patch"))
        table.append(_metric("Regression Gate", "measured", m["regression_gate"], "Guardrail CICD-02: pristine baseline vs. final result"))
        table.append(_metric("Regression Rate (%)", "ground_truth_dependent", "—", "Requires per-test identity matching across runs — not persisted"))

    if cr["status"] == "evaluated":
        m = cr["metrics"]
        table.append(_metric("Grounding Rate", "measured", m["grounding_rate"], "Retrieved files overlapping the actual change"))
        table.append(_metric("Mean Retrieval Ranking Score", "measured", m["mean_retrieval_ranking_score"].split(" (")[0], "Mean internal retrieval score across evidence"))
        table.append(_metric("Recall@K", "ground_truth_dependent", "—", "Requires workflow-specific expected-file ground truth — not persisted"))
        table.append(_metric("Precision@K", "ground_truth_dependent", "—", "Requires workflow-specific expected-file ground truth — not persisted"))

    if exp["status"] == "evaluated":
        m = exp["metrics"]
        table.append(_metric("Explanation Evidence Coverage", "evidence-based", m["explanation_evidence_coverage"], "5-criterion rubric over plan/intent evidence"))
        if "unsupported_repository_reference_rate" in m:
            table.append(_metric("Unsupported Repository-Reference Rate", "measured", m["unsupported_repository_reference_rate"].split(" (")[0], "invented_files_removed vs. plan-referenced files"))
            table.append(_metric("Grounded Repository-Reference Rate", "measured", m["grounded_repository_reference_rate"].split(" (")[0], "invented_files_removed vs. plan-referenced files"))
        table.append(_metric("True Hallucination Rate", "ground_truth_dependent", "—", "Requires an independent reference answer or judge"))
        table.append(_metric("Explanation Correctness", "ground_truth_dependent", "—", "Requires an independent reference answer or judge"))

    if dep["status"] == "evaluated":
        table.append(_metric("Dependency Evidence Coverage", "evidence-based", dep["metrics"]["dependency_evidence_coverage"], "4-criterion rubric over plan/architecture/retrieval evidence"))
        table.append(_metric("Dependency Correctness", "ground_truth_dependent", "—", "Requires an independent dependency ground truth"))

    if bug["status"] == "evaluated":
        table.append(_metric("Bug Analysis Evidence Coverage", "evidence-based", bug["metrics"]["bug_analysis_evidence_coverage"], "5-criterion rubric over plan/risk evidence"))
        table.append(_metric("Root-Cause Correctness", "ground_truth_dependent", "—", "Requires an independent ground truth"))

    if guardrails.get("total"):
        table.append(_metric("Guardrail Checks", "measured", guardrails["total"], "Persisted GuardrailCheck rows for this workflow"))
        table.append(_metric("Guardrail Blocks / Warnings", "measured", f"{guardrails['blocked']} blocked / {guardrails['warnings']} warnings", "Persisted GuardrailCheck rows for this workflow"))

    table.append(_metric("Provider Token Usage", "unavailable", "—", token_usage["note"]))
    ep = token_usage["estimated_proxy"]
    table.append(_metric("Estimated Token/Cost Proxy", "measured", f"~{ep['estimated_tokens']} tok / ${ep['estimated_cost_usd']}", "Character-length-based internal estimate (not actual provider usage)"))

    return table


def build_workflow_evaluation(session: Session, workflow_id: str) -> dict:
    workflow = get_workflow(session, workflow_id)
    status = workflow.state.value

    if status not in SUFFICIENT_STATES:
        return {
            "workflow_id": workflow_id,
            "status": status,
            "available": False,
            "evaluated_at": None,
            "message": "Evaluation will be available after workflow execution is complete.",
            "overall_score": None,
            "evaluated_categories": 0,
            "total_categories": len(CATEGORY_KEYS),
            "categories": {},
            "evidence": {},
            "measurement_limitations": [],
            "token_usage": {},
            "latency_breakdown": {},
            "guardrail_metrics": {},
            "metric_status": [],
            "metrics_summary": {"measured_count": 0, "evidence_based_count": 0, "ground_truth_dependent_count": 0, "unavailable_count": 0},
        }

    trace = build_report(session, workflow_id, include_executive_summary=False)

    iu = trace.get("intent_understanding") or {}
    classified_category = iu.get("classified_category")
    intent_text = trace.get("intent", "")

    categories = {
        "explanation": _eval_explanation(trace),
        "code_retrieval": _eval_code_retrieval(trace),
        "dependency_understanding": _eval_dependency_understanding(trace),
        "bug_analysis": _eval_bug_analysis(trace),
        "code_generation": _eval_code_generation(trace),
        "refactoring": _eval_refactoring(trace, intent_text, classified_category),
        "rag_based_question": _eval_rag_based_question(trace),
    }

    scored = [c["score"] for c in categories.values() if c["status"] == "evaluated" and c["score"] is not None]
    evaluated_categories = len(scored)
    overall_score = round(sum(scored) / len(scored)) if scored else None

    # Pull per-category limitation notes into one deduped, readable list —
    # never repeated per-category as a wall of "Not available" lines.
    measurement_limitations: list[str] = []
    seen = set()
    for key, cat in categories.items():
        for note in cat.pop("_limitations", []):
            tagged = f"{CATEGORY_LABELS[key]}: {note}"
            if note not in seen:
                seen.add(note)
                measurement_limitations.append(tagged)
    if categories["refactoring"]["status"] == "not_applicable":
        measurement_limitations.append(f"{CATEGORY_LABELS['refactoring']}: Not applicable — workflow does not contain a refactoring objective (does not count against the workflow).")
    if categories["rag_based_question"]["status"] == "not_evaluated":
        measurement_limitations.append(f"{CATEGORY_LABELS['rag_based_question']}: {categories['rag_based_question']['note']}")

    timing = trace.get("timing_ms", {})
    latency_breakdown = {k: v for k, v in timing.items() if v is not None}

    guardrail_metrics = _guardrail_metrics(trace)
    token_usage = _token_usage(workflow)
    metric_status = _build_metric_status(categories, guardrail_metrics, token_usage)

    metrics_summary = {
        "measured_count": sum(1 for m in metric_status if m["status"] == "measured"),
        "evidence_based_count": sum(1 for m in metric_status if m["status"] == "evidence-based"),
        "ground_truth_dependent_count": sum(1 for m in metric_status if m["status"] == "ground_truth_dependent"),
        "unavailable_count": sum(1 for m in metric_status if m["status"] == "unavailable"),
        "measured": [m["metric"] for m in metric_status if m["status"] == "measured"],
        "ground_truth_dependent": [m["metric"] for m in metric_status if m["status"] == "ground_truth_dependent"],
        "unavailable": [m["metric"] for m in metric_status if m["status"] == "unavailable"],
    }

    return {
        "workflow_id": workflow_id,
        "status": status,
        "available": True,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "message": None,
        "overall_score": overall_score,
        "overall_score_message": None if overall_score is not None else "Overall evidence score unavailable — insufficient measurable evidence.",
        "evaluated_categories": evaluated_categories,
        "total_categories": len(CATEGORY_KEYS),
        "categories": categories,
        "evidence": {
            "developer_intent": intent_text,
            "repository": trace.get("repository"),
            "final_status": trace.get("final_status"),
            "final_validation": trace.get("final_validation"),
            "total_duration_ms": timing.get("total"),
        },
        "measurement_limitations": measurement_limitations,
        "token_usage": token_usage,
        "latency_breakdown": latency_breakdown,
        "guardrail_metrics": guardrail_metrics,
        "metric_status": metric_status,
        "metrics_summary": metrics_summary,
    }
