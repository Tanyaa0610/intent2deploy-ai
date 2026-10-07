"""Serves evaluation run results produced by scripts/run_evaluation.py
(master spec §23, §37). Reads real JSON files from evaluation/results/ —
never fabricates numbers."""
from __future__ import annotations

import json

from fastapi import APIRouter

from app.core.config import PROJECT_ROOT

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"


@router.get("/results")
def get_results() -> dict:
    if not RESULTS_DIR.exists():
        return {"runs": [], "message": "No evaluation runs found. Run `python scripts/run_evaluation.py` first."}
    runs = []
    for f in sorted(RESULTS_DIR.glob("run_*.json"), reverse=True):
        if f.name.startswith("baseline_run_"):
            continue  # served separately by /baseline-results
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"runs": runs}


@router.get("/baseline-results")
def get_baseline_results() -> dict:
    """Results from the BASELINE (non-orchestrated) arm — see
    scripts/run_baseline_evaluation.py and
    docs/EXPERIMENTAL_EVALUATION.md."""
    if not RESULTS_DIR.exists():
        return {"runs": [], "message": "No baseline runs found. Run `python scripts/run_baseline_evaluation.py` first."}
    runs = []
    for f in sorted(RESULTS_DIR.glob("baseline_run_*.json"), reverse=True):
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"runs": runs}


@router.get("/comparison")
def get_comparison() -> dict:
    """The baseline-vs-Intent2Deploy comparison, interpretation, and
    failure analysis produced by scripts/compare_evaluation_runs.py.
    Returns `available: False` (never a fabricated comparison) if that
    script has not been run yet."""
    path = RESULTS_DIR / "experiment_summary.json"
    if not path.exists():
        return {
            "available": False,
            "message": (
                "No comparison found. Run `python scripts/run_evaluation.py`, then "
                "`python scripts/run_baseline_evaluation.py`, then "
                "`python scripts/compare_evaluation_runs.py`."
            ),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "message": "experiment_summary.json exists but could not be parsed."}
    data["available"] = True
    return data
