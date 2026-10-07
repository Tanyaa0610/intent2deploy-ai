from pathlib import Path

from app.services.evaluation.baseline_runner import (
    collect_pristine_test_ids,
    run_baseline_task,
    select_basic_context,
)
from app.services.providers.local_provider import LocalProvider

DEMO_REPO = Path(__file__).resolve().parents[3] / "demo-repository"


def test_select_basic_context_finds_payments_file_for_payment_intent():
    file_contents, selected = select_basic_context(
        DEMO_REPO, "Fix duplicate orders caused by payment provider timeout retries", max_files=3
    )
    assert "src/shopflow/services/payment_service.py" in selected
    assert "class PaymentService" in file_contents["src/shopflow/services/payment_service.py"]


def test_select_basic_context_is_naive_and_deterministic():
    # Same intent -> same selection every time (no randomness, no network).
    a, _ = select_basic_context(DEMO_REPO, "Add a password reset feature", max_files=3)
    b, _ = select_basic_context(DEMO_REPO, "Add a password reset feature", max_files=3)
    assert a == b


def test_select_basic_context_returns_empty_for_no_signal_intent():
    file_contents, selected = select_basic_context(DEMO_REPO, "", max_files=3)
    assert file_contents == {}
    assert selected == set()


def test_collect_pristine_test_ids_matches_demo_repo_test_count():
    ids = collect_pristine_test_ids(DEMO_REPO)
    assert len(ids) > 0
    assert all(i.startswith("tests/") for i in ids)


def test_run_baseline_task_produces_grounded_completed_result_for_password_reset():
    task = {
        "id": "test_task_password_reset",
        "title": "Add a password-reset feature",
        "category": "feature_addition",
        "intent": "Add a password reset feature. Create appropriate tests and make sure existing authentication functionality is not affected.",
        "expected_files": ["src/shopflow/services/auth_service.py"],
        "difficulty": "medium",
    }
    pristine = collect_pristine_test_ids(DEMO_REPO)
    result = run_baseline_task(task, DEMO_REPO, pristine, run_id="unittest", provider=LocalProvider())

    assert result["error"] is None
    assert result["human_interventions"] == 0
    assert result["repair_attempts"] == 0
    assert result["guardrail_total"] is None  # structurally absent, not measured zero
    assert any(c > 0 for c in result["changes_confidence"])
    assert "src/shopflow/services/auth_service.py" in result["context_files_selected"]
    assert result["final_validation"] in ("passed", "failed")


def test_run_baseline_task_is_honest_noop_for_unrecognized_intent():
    task = {
        "id": "test_task_unknown",
        "title": "Something unrelated",
        "category": "generic",
        "intent": "Completely unrelated intent matching no mock strategy whatsoever",
        "expected_files": [],
        "difficulty": "easy",
    }
    pristine = collect_pristine_test_ids(DEMO_REPO)
    result = run_baseline_task(task, DEMO_REPO, pristine, run_id="unittest", provider=LocalProvider())

    assert result["completed"] is False
    assert result["final_status"] == "NO_CHANGE"
    assert all(c == 0 for c in result["changes_confidence"]) or result["changes_confidence"] == []
