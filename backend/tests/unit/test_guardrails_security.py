"""SECURITY category guardrail tests (SEC-01..SEC-05)."""
from __future__ import annotations

from app.models.enums import GuardrailAction, GuardrailStatus
from app.services.guardrails import engine as guardrails


def test_sec01_secret_detection_blocks_a_real_secret():
    dirty = guardrails.check_secret_detection("codegen", {"file.py": 'api_key = "sk-abcdefghij1234567890"'})
    assert dirty.status == GuardrailStatus.BLOCKED.value
    assert dirty.action == GuardrailAction.BLOCK.value
    assert dirty.evidence


def test_sec01_secret_detection_passes_clean_code():
    clean = guardrails.check_secret_detection("codegen", {"file.py": "def foo(password: str) -> None: ..."})
    assert clean.status == GuardrailStatus.PASSED.value
    assert clean.action == GuardrailAction.ALLOW.value


def test_sec02_dependency_security_flags_manifest_touch():
    touched = guardrails.check_dependency_security("codegen", ["requirements.txt"])
    assert touched.status == GuardrailStatus.WARNING.value
    assert touched.action == GuardrailAction.REQUIRE_APPROVAL.value
    assert "NOT_IMPLEMENTED" in touched.remediation

    untouched = guardrails.check_dependency_security("codegen", ["src/auth/service.py"])
    assert untouched.status == GuardrailStatus.NOT_APPLICABLE.value


def test_sec03_code_security_detects_unsafe_code():
    unsafe = guardrails.check_code_security("codegen", {"f.py": "subprocess.run(cmd, shell=True)"})
    assert unsafe.status == GuardrailStatus.BLOCKED.value
    assert unsafe.action == GuardrailAction.BLOCK.value
    assert "command_injection" in unsafe.evidence[0]

    safe = guardrails.check_code_security("codegen", {"f.py": "subprocess.run(['ls', '-la'])"})
    assert safe.status == GuardrailStatus.PASSED.value


def test_sec03_detects_sql_injection_and_eval():
    sqli = guardrails.check_code_security("codegen", {"f.py": 'cursor.execute(f"SELECT * FROM users WHERE id={uid}")'})
    assert sqli.status == GuardrailStatus.BLOCKED.value

    unsafe_eval = guardrails.check_code_security("codegen", {"f.py": "eval(user_input)"})
    assert unsafe_eval.status == GuardrailStatus.BLOCKED.value


def test_sec04_container_security_flags_root_user_and_latest_tag():
    dockerfile = "FROM python:latest\nRUN pip install -r requirements.txt\n"
    result = guardrails.check_container_security("codegen", {"Dockerfile": dockerfile})
    assert result.status == GuardrailStatus.WARNING.value
    assert any("root" in e for e in result.evidence)
    assert any("unsafe_base_image" in e for e in result.evidence)


def test_sec04_container_security_not_applicable_when_no_dockerfile():
    result = guardrails.check_container_security("codegen", {})
    assert result.status == GuardrailStatus.NOT_APPLICABLE.value


def test_sec05_security_configuration_flags_cors_wildcard():
    result = guardrails.check_security_configuration("codegen", {"app.py": 'app.add_middleware(CORSMiddleware, allow_origins=["*"])'})
    assert result.status == GuardrailStatus.WARNING.value

    clean = guardrails.check_security_configuration("codegen", {"app.py": "def foo(): pass"})
    assert clean.status == GuardrailStatus.PASSED.value
