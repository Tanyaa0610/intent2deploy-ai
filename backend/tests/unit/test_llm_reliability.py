import pytest
from pydantic import BaseModel

from app.core.llm_reliability import LLMOutputError, structured_call
from app.services.providers.base import LLMProvider, LLMResponse, LLMUsage


class _Schema(BaseModel):
    value: int


class _AlwaysBadProvider(LLMProvider):
    name = "bad"

    def complete(self, prompt_name, rendered_prompt, context):
        return LLMResponse(text="not json at all", usage=LLMUsage(), model="x", provider=self.name, is_mock=True)


class _FlakyThenGoodProvider(LLMProvider):
    name = "flaky"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt_name, rendered_prompt, context):
        self.calls += 1
        if self.calls < 2:
            return LLMResponse(text="garbage", usage=LLMUsage(), model="x", provider=self.name, is_mock=True)
        return LLMResponse(text='{"value": 42}', usage=LLMUsage(), model="x", provider=self.name, is_mock=True)


def test_structured_call_succeeds_on_valid_json():
    provider = _FlakyThenGoodProvider()
    result = structured_call(provider, "p", "prompt", {}, schema=_Schema)
    assert result.parsed.value == 42
    assert result.attempts == 2  # retried once before succeeding


def test_structured_call_raises_after_exhausting_retries():
    provider = _AlwaysBadProvider()
    with pytest.raises(LLMOutputError):
        structured_call(provider, "p", "prompt", {}, schema=_Schema)


def test_structured_call_extracts_json_from_surrounding_text():
    class _Provider(LLMProvider):
        name = "wrapped"

        def complete(self, prompt_name, rendered_prompt, context):
            return LLMResponse(
                text='Here is the answer:\n{"value": 7}\nHope that helps.',
                usage=LLMUsage(),
                model="x",
                provider=self.name,
                is_mock=True,
            )

    result = structured_call(_Provider(), "p", "prompt", {}, schema=_Schema)
    assert result.parsed.value == 7
