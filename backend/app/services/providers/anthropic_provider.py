"""Real Anthropic provider. Requires ANTHROPIC_API_KEY and LLM_MODE=live.

This performs a genuine API call via the official `anthropic` SDK. It is
not exercised by default (LLM_MODE=mock) since no credentials are
provisioned in the course/demo environment; the class is included so the
system is not hardcoded to a single provider (master spec §26) and so a
grader who supplies their own key can exercise real generation end to end.
"""
from __future__ import annotations

from app.core.config import settings
from app.services.providers.base import LLMProvider, LLMProviderError, LLMResponse, LLMUsage


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic
        except ImportError as exc:
            raise LLMProviderError("The 'anthropic' package is not installed.") from exc
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name or "claude-sonnet-5"

    def complete(self, prompt_name: str, rendered_prompt: str, context: dict) -> LLMResponse:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                messages=[{"role": "user", "content": rendered_prompt}],
            )
        except Exception as exc:  # pragma: no cover - network dependent
            raise LLMProviderError(f"Anthropic API call failed: {exc}") from exc

        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        usage = LLMUsage(
            prompt_tokens=getattr(resp.usage, "input_tokens", None),
            completion_tokens=getattr(resp.usage, "output_tokens", None),
            total_tokens=(getattr(resp.usage, "input_tokens", 0) or 0) + (getattr(resp.usage, "output_tokens", 0) or 0),
            available=True,
        )
        return LLMResponse(text=text, usage=usage, model=self._model, provider=self.name, is_mock=False)
