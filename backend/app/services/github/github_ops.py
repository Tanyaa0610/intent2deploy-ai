"""Optional GitHub integration (master spec §19, §53).

Every action here is externally visible and must only be called after
the orchestrator has recorded an explicit human approval for it. If
GITHUB_TOKEN/GITHUB_OWNER/GITHUB_REPO are not configured, these functions
raise GitHubNotConfiguredError and the caller falls back to
LOCAL VALIDATION only — never fabricated CI results.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo

from app.core.config import settings


class GitHubNotConfiguredError(Exception):
    pass


class GitHubOperationError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.github_token and settings.github_owner and settings.github_repo)


def _require_configured() -> None:
    if not is_configured():
        raise GitHubNotConfiguredError(
            "GITHUB_TOKEN/GITHUB_OWNER/GITHUB_REPO are not set; GitHub integration is unavailable. "
            "Local validation results remain valid and are clearly labeled as LOCAL VALIDATION."
        )


def push_branch(repo_path: Path, branch_name: str) -> str:
    """Push a local branch to origin. Requires GitHub credentials to be
    configured. Returns the remote ref pushed."""
    _require_configured()
    repo = Repo(repo_path)
    remote_url = f"https://x-access-token:{settings.github_token}@github.com/{settings.github_owner}/{settings.github_repo}.git"
    try:
        if "origin" in [r.name for r in repo.remotes]:
            repo.delete_remote("origin")
        origin = repo.create_remote("origin", remote_url)
        origin.push(refspec=f"{branch_name}:{branch_name}")
    except GitCommandError as exc:
        raise GitHubOperationError(f"Push failed: {exc}") from exc
    return branch_name


@dataclass
class PullRequestInfo:
    number: int
    url: str
    state: str


def create_pull_request(branch_name: str, base_branch: str, title: str, body: str) -> PullRequestInfo:
    _require_configured()
    try:
        from github import Github
    except ImportError as exc:
        raise GitHubOperationError("PyGithub is not installed.") from exc

    client = Github(settings.github_token)
    repo = client.get_repo(f"{settings.github_owner}/{settings.github_repo}")
    try:
        pr = repo.create_pull(title=title, body=body, head=branch_name, base=base_branch)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Pull request creation failed: {exc}") from exc
    return PullRequestInfo(number=pr.number, url=pr.html_url, state=pr.state)


@dataclass
class WorkflowRunInfo:
    run_id: int
    status: str
    conclusion: str
    url: str


def get_latest_workflow_run(workflow_file: str = "ai-devops.yml") -> WorkflowRunInfo | None:
    _require_configured()
    try:
        from github import Github
    except ImportError as exc:
        raise GitHubOperationError("PyGithub is not installed.") from exc

    client = Github(settings.github_token)
    repo = client.get_repo(f"{settings.github_owner}/{settings.github_repo}")
    try:
        workflow = repo.get_workflow(workflow_file)
        runs = workflow.get_runs()
        latest = runs[0] if runs.totalCount > 0 else None
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Failed to fetch workflow runs: {exc}") from exc
    if latest is None:
        return None
    return WorkflowRunInfo(
        run_id=latest.id, status=latest.status, conclusion=latest.conclusion or "", url=latest.html_url
    )
