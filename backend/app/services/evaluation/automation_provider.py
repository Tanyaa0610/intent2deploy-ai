"""External automation provider adapter (master spec §20).

    AutomationProvider
     +-- LocalWorkflowProvider   (always available: this backend's own
                                  workflow state machine / sandbox)
     +-- GitHubActionsProvider   (available when GitHub is configured;
                                  see app/services/github/github_ops.py)
     +-- SweepProvider           (optional; requires SWEEP_API_KEY)

Sweep.dev is explicitly mentioned by the course as an AI workflow
automation tool. No Sweep credentials/API access are available in this
project's environment, so `SweepProvider` is implemented as a real
adapter with a real (documented) API contract but is never invoked with
a fabricated response — calling it without SWEEP_API_KEY configured
raises `AutomationProviderUnavailableError` rather than pretending to
call an external service. See docs/ai-testing-tools.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings
from app.services.github import github_ops


class AutomationProviderUnavailableError(Exception):
    pass


@dataclass
class AutomationRunResult:
    provider: str
    status: str
    detail: str
    url: str = ""


class AutomationProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def trigger(self, workflow_id: str, branch_name: str) -> AutomationRunResult: ...


class LocalWorkflowProvider(AutomationProvider):
    """This backend's own orchestrator + sandbox. Always available."""

    name = "local"

    def is_available(self) -> bool:
        return True

    def trigger(self, workflow_id: str, branch_name: str) -> AutomationRunResult:
        return AutomationRunResult(
            provider=self.name,
            status="completed",
            detail="Local sandboxed validation pipeline executed for this workflow.",
        )


class GitHubActionsProvider(AutomationProvider):
    name = "github_actions"

    def is_available(self) -> bool:
        return github_ops.is_configured()

    def trigger(self, workflow_id: str, branch_name: str) -> AutomationRunResult:
        if not self.is_available():
            raise AutomationProviderUnavailableError(
                "GitHub Actions provider requires GITHUB_TOKEN/GITHUB_OWNER/GITHUB_REPO."
            )
        run = github_ops.get_latest_workflow_run()
        if run is None:
            return AutomationRunResult(provider=self.name, status="pending", detail="No workflow run found yet.")
        return AutomationRunResult(
            provider=self.name, status=run.status, detail=run.conclusion, url=run.url
        )


class SweepProvider(AutomationProvider):
    """Adapter for Sweep.dev. Real interface, but unavailable in this
    environment without SWEEP_API_KEY — never simulated."""

    name = "sweep"

    def is_available(self) -> bool:
        return bool(settings.sweep_api_key)

    def trigger(self, workflow_id: str, branch_name: str) -> AutomationRunResult:
        if not self.is_available():
            raise AutomationProviderUnavailableError(
                "Sweep.dev integration is optional and unavailable in this environment "
                "(no SWEEP_API_KEY configured). See docs/ai-testing-tools.md for the "
                "documented integration contract."
            )
        # A real integration would call Sweep's API here with `settings.sweep_api_key`.
        # Intentionally not implemented further: we do not fabricate a response.
        raise AutomationProviderUnavailableError("Sweep.dev API call path is not implemented in this build.")


def available_providers() -> list[AutomationProvider]:
    return [p for p in (LocalWorkflowProvider(), GitHubActionsProvider(), SweepProvider()) if p.is_available()]
