from __future__ import annotations

from pathlib import Path

from app.services.chaos.engine import chaos_pass_rate, run_experiments

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_REPO = PROJECT_ROOT / "demo-repository"


def test_run_experiments_flags_missing_idempotency_before_fix():
    outcomes = run_experiments(DEMO_REPO, ["src/payments/service.py"], "fix duplicate orders on payment timeout")
    dependency_experiment = next(o for o in outcomes if o.experiment_id == "CH01")
    assert dependency_experiment.result == "FAILED"
    assert "idempotency" in dependency_experiment.observed_behavior.lower() or "duplicate" in dependency_experiment.observed_behavior.lower()


def test_run_experiments_marks_irrelevant_faults_not_applicable():
    outcomes = run_experiments(DEMO_REPO, ["src/orders/service.py"], "fix a bug")
    by_id = {o.experiment_id: o for o in outcomes}
    assert by_id["CH04"].result == "NOT_APPLICABLE"  # no database in this repo
    assert by_id["CH05"].result == "NOT_APPLICABLE"
    assert by_id["CH11"].result == "NOT_APPLICABLE"  # no cache layer


def test_run_experiments_returns_all_twelve_catalog_entries():
    outcomes = run_experiments(DEMO_REPO, [], "generic")
    assert len(outcomes) == 12


def test_chaos_pass_rate_ignores_not_applicable():
    outcomes = run_experiments(DEMO_REPO, ["src/payments/service.py"], "fix duplicate orders on payment timeout")
    rate = chaos_pass_rate(outcomes)
    applicable = [o for o in outcomes if o.result != "NOT_APPLICABLE"]
    assert rate is not None
    assert 0.0 <= rate <= 1.0
    assert len(applicable) > 0


def test_chaos_pass_rate_none_when_nothing_applicable():
    class Fake:
        def __init__(self, result):
            self.result = result

    assert chaos_pass_rate([Fake("NOT_APPLICABLE"), Fake("NOT_APPLICABLE")]) is None
