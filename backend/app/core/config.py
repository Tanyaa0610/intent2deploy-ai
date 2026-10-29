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

    # A generated project is larger than an ordinary change (app + tests +
    # CI + Docker files), so it has its own file limit.
    max_greenfield_files: int = 25

    # Containerization: build each project's Docker image during validation
    # when a Docker daemon is reachable (skipped, and reported, otherwise).
    docker_validation: bool = True
    docker_build_timeout_seconds: int = 900

    # Production verification (validation stages prod_*): boot the app the
    # way it ships and test the running service over HTTP — smoke, API
    # contract, hostile input, load and restart.
    production_validation: bool = True
    prod_boot_timeout_seconds: int = 60
    prod_load_requests: int = 300
    prod_load_concurrency: int = 20
    prod_p95_budget_ms: int = 1000

    # Zero-downtime deployments (staging preview): a new release starts next to
    # the live one and only takes traffic after passing live checks; a hot
    # standby copy takes over at once if the live one fails; a watchdog keeps
    # checking and heals. Failures raise alerts — they never take the site down.
    monitor_enabled: bool = True
    monitor_interval_seconds: float = 10.0
    monitor_failure_threshold: int = 2  # consecutive failed checks before healing
    standby_replica: bool = True
    rollback_window_seconds: int = 900  # the previous release stays warm this long
    # Optional: Slack/Teams/any incoming-webhook URL that alerts are POSTed to.
    alert_webhook_url: str = ""

    # AI-DevOps guardrail limits — INFRASTRUCTURE category
    max_blast_radius_files: int = 8

    # AI-DevOps guardrail limits — COST category. Token/dollar figures are
    # ESTIMATES (see Workflow.llm_estimated_tokens); mock mode has no real
    # provider billing API to read exact usage from.
    max_llm_calls_per_workflow: int = 12
    max_llm_estimated_tokens_per_workflow: int = 60_000
    workflow_cost_budget_usd: float = 1.00
    cost_per_1k_tokens_usd: float = 0.01  # generic fallback rate; not provider-specific pricing

    # Workspaces
    workspaces_dir: str = str(PROJECT_ROOT / "workspaces")

    # Local cache for repositories cloned from a GitHub URL (New Workflow
    # "GitHub Repository" input). Read-only clones used for indexing/RAG/
    # codegen only — never a push target.
    cloned_repos_dir: str = str(PROJECT_ROOT / "cloned_repos")

    # Filesystem roots the Repository Manager may create/connect local
    # repositories under (comma-separated absolute paths). Empty = the
    # current user's home directory plus the bundled demo repository. Under
    # Docker the container only sees its own filesystem, so host folders
    # must be bind-mounted and listed here (e.g. ALLOWED_REPO_ROOTS=/repos).
    allowed_repo_roots: str = ""

    # Integration branch for the feature-branch workflow: feature PRs merge
    # into it first, it can be run/previewed, and it is promoted to main via
    # a release PR. Empty = feature PRs target main directly.
    staging_branch: str = "staging"

    # Optional external automation adapter (Sweep.dev)
    sweep_api_key: str = ""

    @property
    def repo_roots(self) -> list[Path]:
        if self.allowed_repo_roots.strip():
            return [Path(p.strip()).expanduser() for p in self.allowed_repo_roots.split(",") if p.strip()]
        return [Path.home(), PROJECT_ROOT / "demo-repository"]

    @property
    def is_mock(self) -> bool:
        return self.llm_mode.lower() != "live"


settings = Settings()
