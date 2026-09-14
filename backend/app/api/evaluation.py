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
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"runs": runs}
