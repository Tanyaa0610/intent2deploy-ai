"""Central application configuration, loaded from environment variables.

Never hardcode secrets here. All values have safe local-development
defaults so the app runs out of the box in mock mode.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), extra="ignore")

    app_env: str = "development"

    # LLM provider abstraction
    llm_provider: str = "anthropic"  # anthropic | openai | local
    llm_mode: str = "mock"  # mock | live
    model_name: str = "claude-sonnet-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # GitHub
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""

    # Vector store
    vector_store: str = "chroma"
    chroma_persist_dir: str = str(PROJECT_ROOT / "chroma_data")

    # Database
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'intent2deploy.db'}"

    # Safety limits
    max_files_changed: int = 15
    max_patch_lines: int = 1000
    max_repair_attempts: int = 2
    command_timeout_seconds: int = 120

    # Workspaces
    workspaces_dir: str = str(PROJECT_ROOT / "workspaces")

    # Optional external automation adapter (Sweep.dev)
    sweep_api_key: str = ""

    @property
    def is_mock(self) -> bool:
        return self.llm_mode.lower() != "live"


settings = Settings()
