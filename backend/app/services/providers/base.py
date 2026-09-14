"""LLM provider abstraction (master spec §26).

Every provider implements `complete`, which is given the fully-rendered
prompt (system instruction text, already filled from the prompt template)
plus a structured `context` dict carrying the same information in typed
form. Real providers (Anthropic/OpenAI) use only `rendered_prompt`. The
deterministic mock provider (`LocalProvider`) uses `context` directly so
it does not need to re-parse rendered text.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    available: bool = False


@dataclass
class LLMResponse:
    text: str
    usage: LLMUsage
    model: str
    provider: str
    is_mock: bool


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, prompt_name: str, rendered_prompt: str, context: dict) -> LLMResponse:
        """Return a raw text completion (expected to be JSON) for the prompt."""
        raise NotImplementedError

    @property
    def is_mock(self) -> bool:
        return False


class LLMProviderError(Exception):
    pass
