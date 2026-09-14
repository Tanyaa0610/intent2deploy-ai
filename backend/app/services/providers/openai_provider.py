"""Real OpenAI provider. Requires OPENAI_API_KEY and LLM_MODE=live.

See anthropic_provider.py for the rationale: implemented for real (not
simulated), but not exercised without a supplied API key.
"""
from __future__ import annotations

from app.core.config import settings
from app.services.providers.base import LLMProvider, LLMProviderError, LLMResponse, LLMUsage


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise LLMProviderError("OPENAI_API_KEY is not set.")
        try:
            import openai
        except ImportError as exc:
            raise LLMProviderError("The 'openai' package is not installed.") from exc
        self._client = openai.OpenAI(api_key=settings.openai_api_key)
        self._model = settings.model_name or "gpt-4o-mini"

    def complete(self, prompt_name: str, rendered_prompt: str, context: dict) -> LLMResponse:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": rendered_prompt}],
            )
        except Exception as exc:  # pragma: no cover - network dependent
            raise LLMProviderError(f"OpenAI API call failed: {exc}") from exc

        text = resp.choices[0].message.content or ""
        usage = LLMUsage(
            prompt_tokens=getattr(resp.usage, "prompt_tokens", None),
            completion_tokens=getattr(resp.usage, "completion_tokens", None),
            total_tokens=getattr(resp.usage, "total_tokens", None),
            available=True,
        )
        return LLMResponse(text=text, usage=usage, model=self._model, provider=self.name, is_mock=False)
