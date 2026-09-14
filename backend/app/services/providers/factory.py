from __future__ import annotations

from app.core.config import settings
from app.services.providers.base import LLMProvider
from app.services.providers.local_provider import LocalProvider


def get_provider() -> LLMProvider:
    if settings.is_mock:
        return LocalProvider()

    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        from app.services.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if provider == "openai":
        from app.services.providers.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if provider == "local":
        return LocalProvider()

    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")
