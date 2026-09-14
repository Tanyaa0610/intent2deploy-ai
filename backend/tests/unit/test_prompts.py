import pytest

from app.core.prompts import all_prompt_names, load_prompt

EXPECTED_PROMPTS = {
    "requirement_analysis",
    "retrieval_query_generation",
    "code_explanation",
    "implementation_planning",
    "code_modification",
    "test_generation",
    "failure_diagnosis",
    "repair_planning",
    "final_report_generation",
}


def test_all_expected_prompts_exist():
    assert EXPECTED_PROMPTS.issubset(set(all_prompt_names()))


@pytest.mark.parametrize("name", sorted(EXPECTED_PROMPTS))
def test_prompt_has_version_and_system_instruction(name):
    prompt = load_prompt(name)
    assert prompt.version
    assert prompt.system_instruction.strip()
    assert prompt.purpose


def test_implementation_planning_render_substitutes_variables():
    prompt = load_prompt("implementation_planning")
    rendered = prompt.render(intent="do X", retrieved_context="ctx", retrieved_files=["a.py"])
    assert "do X" in rendered
    assert "a.py" in rendered


def test_render_missing_variable_raises():
    prompt = load_prompt("implementation_planning")
    with pytest.raises(ValueError):
        prompt.render(intent="do X")  # missing retrieved_context/retrieved_files
