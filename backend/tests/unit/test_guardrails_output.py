"""OUTPUT category guardrail tests (OUTPUT-01..OUTPUT-13)."""
from __future__ import annotations

from app.models.enums import GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_output01_schema_validation_rejects_invalid_output():
    invalid = guardrails.check_output_schema_validation("codegen", False, "ChangeSetOutput failed validation")
    assert invalid.status == GuardrailStatus.BLOCKED.value
    assert invalid.guardrail_id == "OUTPUT-01"


def test_output02_security_validation_blocks_unsafe_generated_code():
    result = guardrails.check_output_security_validation("codegen", {"f.py": "os.system(user_cmd)"})
    assert result.status == GuardrailStatus.BLOCKED.value
    assert result.guardrail_id == "OUTPUT-02"


def test_output03_secret_in_generated_output_blocked():
    result = guardrails.check_output_secret_detection("codegen", {"f.py": 'password = "hunter2!!"'})
    assert result.status == GuardrailStatus.BLOCKED.value
    assert result.guardrail_id == "OUTPUT-03"


def test_output04_unsafe_command_in_generated_output_blocked():
    result = guardrails.check_output_unsafe_command("codegen", {"f.py": "subprocess.run(cmd, shell=True)"})
    assert result.status == GuardrailStatus.BLOCKED.value

    clean = guardrails.check_output_unsafe_command("codegen", {"f.py": "def foo(): return 1"})
    assert clean.status == GuardrailStatus.PASSED.value


def test_output05_scope_validation_blocks_unrelated_files():
    result = guardrails.check_output_scope_validation("codegen", 2, {"a.py": 5}, ["a.py"], ["a.py", "database/migration.py"])
    assert result.status == GuardrailStatus.BLOCKED.value
    assert any("unrelated" in e for e in result.evidence)


def test_output05_scope_validation_passes_within_scope():
    result = guardrails.check_output_scope_validation("codegen", 1, {"a.py": 5}, ["a.py"], ["a.py"])
    assert result.status == GuardrailStatus.PASSED.value


def test_output06_dependency_change_detection():
    result = guardrails.check_output_dependency_change("codegen", ["package.json"])
    assert result.status == GuardrailStatus.WARNING.value
    assert result.guardrail_id == "OUTPUT-06"


def test_output07_infrastructure_change_detection():
    result = guardrails.check_output_infrastructure_change("codegen", ["docker-compose.yml"])
    assert result.status == GuardrailStatus.WARNING.value


def test_output08_api_compatibility_check():
    old = "@app.get('/x')\ndef foo():\n    pass\n"
    new = "def bar():\n    pass\n"
    breaking = guardrails.check_output_api_compatibility("codegen", "src/api/app.py", old, new)
    assert breaking.status == GuardrailStatus.WARNING.value

    na = guardrails.check_output_api_compatibility("codegen", "src/orders/service.py", old, new)
    assert na.status == GuardrailStatus.NOT_APPLICABLE.value


def test_output09_database_migration_check():
    result = guardrails.check_output_database_migration("codegen", ["migrations/0002_add_column.sql"])
    assert result.status == GuardrailStatus.WARNING.value


def test_output10_regression_check():
    regressed = guardrails.check_output_regression("validation", True, False)
    assert regressed.status == GuardrailStatus.BLOCKED.value
    assert regressed.guardrail_id == "OUTPUT-10"


def test_output11_evidence_and_hallucination_validation():
    result = guardrails.check_output_evidence("planning", ["invented.py"], [])
    assert result.status == GuardrailStatus.WARNING.value


def test_output12_policy_compliance_reflects_siblings():
    blocked_sibling = guardrails.check_output_secret_detection("codegen", {"f.py": 'password = "hunter2!!"'})
    result = guardrails.check_output_policy_compliance("codegen", [blocked_sibling])
    assert result.status == GuardrailStatus.BLOCKED.value

    clean_sibling = guardrails.check_output_secret_detection("codegen", {"f.py": "clean"})
    ok = guardrails.check_output_policy_compliance("codegen", [clean_sibling])
    assert ok.status == GuardrailStatus.PASSED.value


def test_output13_production_safety_check():
    result = guardrails.check_output_production_safety("codegen", "production")
    assert result.status == GuardrailStatus.BLOCKED.value
