from pathlib import Path

from app.services.codegen.mock_strategies import bug_fix_orders, password_reset
from app.services.planner.intent_classifier import classify_intent

DEMO_AUTH_SERVICE = Path(__file__).resolve().parents[3] / "demo-repository" / "src" / "auth" / "service.py"


def test_classify_intent_maps_to_expected_categories():
    assert classify_intent("Add a password reset feature") == "password_reset"
    assert classify_intent("Fix the null-reference bug in the order service.") == "bug_fix_orders"
    assert classify_intent("Add input validation to the registration endpoint.") == "input_validation"
    assert classify_intent("Something totally unrelated to anything") == "generic"


def test_password_reset_strategy_produces_grounded_change():
    content = DEMO_AUTH_SERVICE.read_text()
    changes = password_reset({"src/auth/service.py": content})
    assert len(changes) == 1
    assert "generate_password_reset_token" in changes[0].new_content
    assert changes[0].new_content != changes[0].old_content


def test_bug_fix_strategy_is_noop_when_file_missing():
    assert bug_fix_orders({}) == []
