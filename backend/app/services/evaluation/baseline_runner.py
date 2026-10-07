"""Baseline (non-orchestrated) LLM-assisted code-change runner.

Implements the BASELINE arm of the controlled experiment described in
docs/EXPERIMENTAL_EVALUATION.md, contrasted against the full Intent2Deploy
workflow (`scripts/run_evaluation.py`).

The baseline receives the same developer intent and the same underlying
LLM provider/model (`LocalProvider`, "local-mock-v1" in LLM_MODE=mock; see
`run_baseline_task`'s `provider` parameter for LLM_MODE=live) as
Intent2Deploy, but:

- gathers "basic repository context" via a naive keyword-overlap file
  scorer (`select_basic_context`) instead of Intent2Deploy's hybrid
  semantic + BM25 + path + symbol ChromaDB retrieval
  (app/services/rag/retriever.py);
- makes a single direct code-generation call with no planning stage, no
  human-approval checkpoints, and no guardrail engine;
- runs the task's validation command exactly once, with no bounded
  repair loop.

This module performs no network calls and shares no mutable state with
the orchestrator — it applies the generated patch to an isolated
workspace copy (via the existing sandbox workspace utilities) and never
touches the real repository fixture or an Intent2Deploy workflow's own
workspace, so baseline and Intent2Deploy runs (and repeated baseline
runs) cannot leak into one another.

No metric here is invented: everything is either read from the real
generated `LLMResponse`/patch, or from the real exit code/stdout of a
`pytest` subprocess run against a fresh copy of the repository.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from app.services.codegen.diffing import apply_patch
from app.services.planner.intent_classifier import extract_key_terms
from app.services.providers.base import LLMProvider
from app.services.providers.local_provider import LocalProvider
from app.services.validation.sandbox import create_workspace, destroy_workspace

_SOURCE_EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "tests", "node_modules", ".venv", "venv"}


def collect_pristine_test_ids(repo_path: Path) -> set[str]:
    """Collect the set of test node IDs that exist in the pristine
    repository's test suite, used as real (not proxy) ground truth for
    the regression metric. Shared by both evaluation arms so "regressed"
    means the same thing in both."""
    passed_ids: set[str] = set()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" in line and line.startswith("tests/"):
            passed_ids.add(line.split(" ")[0])
    return passed_ids


def select_basic_context(repo_path: Path, intent: str, max_files: int = 3) -> tuple[dict[str, str], set[str]]:
    """Naive "basic repository context" retrieval: score every source
    file by how many of the intent's extracted key terms occur in its
    path or content, and return the top `max_files`' contents.

    This stands in for a conventional LLM-assisted workflow that is
    handed "relevant repository files" without a real retrieval
    pipeline — no embeddings, no BM25, no AST-aware chunking (contrast
    with app/services/rag/retriever.py). Deterministic and reproducible:
    the same intent always yields the same selection.
    """
    terms = extract_key_terms(intent)
    if not terms:
        return {}, set()

    scored: list[tuple[int, str]] = []
    for path in sorted(repo_path.rglob("*.py")):
        rel_parts = path.relative_to(repo_path).parts
        if any(part in _SOURCE_EXCLUDE_DIRS for part in rel_parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lowered_text = text.lower()
        lowered_path = "/".join(rel_parts).lower()
        score = 0
        for term in terms:
            score += lowered_text.count(term)
            if term in lowered_path:
                score += 5  # filename/path match is a strong naive signal
        if score > 0:
            scored.append((score, "/".join(rel_parts)))

    scored.sort(key=lambda t: (-t[0], t[1]))
    top = scored[:max_files]
    file_contents = {rel: (repo_path / rel).read_text(encoding="utf-8") for _score, rel in top}
    return file_contents, set(file_contents.keys())


def _run_pytest(workspace: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )


def run_baseline_task(
    task: dict,
    repo_path: Path,
    pristine_test_ids: set[str],
    run_id: str,
    provider: LLMProvider | None = None,
    max_context_files: int = 3,
) -> dict:
    """Run one benchmark task through the baseline (non-orchestrated)
    approach and return a result dict shaped to line up field-for-field
    with `scripts/run_evaluation.py`'s per-task result, so the two can be
    compared directly by `scripts/compare_evaluation_runs.py`.

    Fields that have no baseline equivalent (guardrail checks, repair
    attempts, per-stage orchestrator latency) are explicitly zeroed /
    nulled rather than omitted, so the comparison script can tell "zero,
    measured" apart from "not applicable" — see each field's inline note.
    """
    provider = provider or LocalProvider()
    intent = task["intent"]
    started = time.monotonic()
    workspace_id = f"baseline-{run_id}-{task['id']}"

    result: dict = {
        "task_id": task["id"],
        "title": task["title"],
        "category": task["category"],
        "difficulty": task.get("difficulty", "medium"),
        "completed": False,
        "final_status": "NO_CHANGE",
        "final_validation": None,
        # Baseline has no approval checkpoints and no repair loop by
        # construction (see module docstring) — these are not "measured
        # zero", they are structurally absent from this arm.
        "human_interventions": 0,
        "repair_attempts": 0,
        "execution_time_ms": None,
        "changes_confidence": [],
        "retrieval_precision_at_k": None,
        "retrieval_recall_at_k": None,
        "unnecessary_modification_ratio": None,
        "touched_expected_files": None,
        "regressed_tests": [],
        # Baseline has no guardrail engine — structurally absent, not
        # "zero warnings measured".
        "guardrail_total": None,
        "guardrail_warnings": None,
        "guardrail_blocked": None,
        "guardrail_failed": None,
        "stage_latency_ms": {"context_selection": None, "codegen": None, "validation": None, "total": None},
        "context_files_selected": [],
        "error": None,
    }

    workspace: Path | None = None
    try:
        t0 = time.monotonic()
        file_contents, selected_files = select_basic_context(repo_path, intent, max_files=max_context_files)
        result["context_files_selected"] = sorted(selected_files)
        result["stage_latency_ms"]["context_selection"] = int((time.monotonic() - t0) * 1000)

        expected_files = set(task.get("expected_files", []))
        if expected_files:
            hit = selected_files & expected_files
            result["retrieval_precision_at_k"] = round(len(hit) / len(selected_files), 3) if selected_files else 0.0
            result["retrieval_recall_at_k"] = round(len(hit) / len(expected_files), 3)

        t1 = time.monotonic()
        response = provider.complete("code_modification", "", {"intent": intent, "file_contents": file_contents})
        result["stage_latency_ms"]["codegen"] = int((time.monotonic() - t1) * 1000)

        changes = json.loads(response.text).get("changes", [])
        result["changes_confidence"] = [c.get("confidence", 0.0) for c in changes]
        real_changes = [c for c in changes if c.get("patch")]
        changed_files = {c["file"] for c in real_changes}
        if expected_files and changed_files:
            unexpected = changed_files - expected_files
            result["unnecessary_modification_ratio"] = round(len(unexpected) / len(changed_files), 3)
        if expected_files:
            result["touched_expected_files"] = round(len(changed_files & expected_files) / len(expected_files), 3)

        has_real_change = len(real_changes) > 0

        workspace = create_workspace(workspace_id, repo_path)
        for c in real_changes:
            target = workspace / c["file"]
            old_content = target.read_text(encoding="utf-8") if target.exists() else ""
            new_content = apply_patch(old_content, c["patch"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")

        # Validation always runs, even for a no-op — this intentionally
        # mirrors Intent2Deploy's own run_evaluation.py semantics, where a
        # no-op workflow still reaches a "passed" validation result
        # trivially (nothing was touched, so nothing can fail). Keeping
        # this rule identical in both arms is what makes
        # "validation_success_rate" comparable between them; the
        # DISTINCT "completed" field (below) is what actually requires a
        # real change, in both arms — see docs/EXPERIMENTAL_EVALUATION.md.
        t2 = time.monotonic()
        proc = _run_pytest(workspace)
        result["stage_latency_ms"]["validation"] = int((time.monotonic() - t2) * 1000)

        failed_ids = {m.group(1) for m in re.finditer(r"FAILED (tests/\S+)", proc.stdout + proc.stderr)}
        result["regressed_tests"] = sorted(failed_ids & pristine_test_ids)
        validation_passed = proc.returncode == 0
        result["final_validation"] = "passed" if validation_passed else "failed"
        if not has_real_change:
            result["final_status"] = "NO_CHANGE"
            result["completed"] = False
        else:
            result["final_status"] = "VALIDATED" if validation_passed else "VALIDATION_FAILED"
            result["completed"] = validation_passed

        result["execution_time_ms"] = int((time.monotonic() - started) * 1000)
        result["stage_latency_ms"]["total"] = result["execution_time_ms"]

    except Exception as exc:  # pragma: no cover - defensive; surfaced in results, not swallowed
        result["error"] = str(exc)
    finally:
        if workspace is not None:
            destroy_workspace(workspace_id)

    return result
