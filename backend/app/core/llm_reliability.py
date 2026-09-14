"""LLM output reliability layer (master spec §46):

LLM Output -> Schema Validation -> (caller-supplied) Evidence Validation
-> (caller-supplied) Safety Validation -> only then execute.

This module handles the first step generically: parse the provider's raw
text as JSON and validate it against a Pydantic model, with a bounded
number of retries on malformed JSON/schema violations.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.providers.base import LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 2

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class StructuredCallResult:
    def __init__(self, parsed: BaseModel, raw_text: str, response: LLMResponse, attempts: int):
        self.parsed = parsed
        self.raw_text = raw_text
        self.response = response
        self.attempts = attempts


class LLMOutputError(Exception):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Could not parse JSON from LLM output: {exc}") from exc
    raise LLMOutputError("LLM output did not contain a JSON object.")


def structured_call(
    provider: LLMProvider,
    prompt_name: str,
    rendered_prompt: str,
    context: dict,
    schema: type[T],
) -> StructuredCallResult:
    """Call the provider and validate its output against `schema`, retrying
    on malformed JSON or schema violations up to MAX_RETRIES times."""
    last_error: Exception | None = None
    response: LLMResponse | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        response = provider.complete(prompt_name, rendered_prompt, context)
        try:
            data = _extract_json(response.text)
            parsed = schema.model_validate(data)
            return StructuredCallResult(parsed=parsed, raw_text=response.text, response=response, attempts=attempt)
        except (LLMOutputError, ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
    raise LLMOutputError(
        f"LLM output for prompt '{prompt_name}' failed schema validation after "
        f"{MAX_RETRIES + 1} attempts: {last_error}"
    )
