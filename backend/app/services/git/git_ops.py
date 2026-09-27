"""Git integration (master spec §18): branch creation, status, diff, commit.

Uses GitPython. Commit only happens after explicit human approval
(enforced by the orchestrator's state machine, not here). Push is a
separate, also-gated operation in github/github_ops.py.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo


class GitOperationError(Exception):
    pass


class GitCloneError(Exception):
    pass


# Deliberately narrow: only https://github.com/<owner>/<repo> URLs are
# accepted for cloning (New Workflow "GitHub Repository" input). This is a
# read-only clone for indexing/RAG/codegen — never a push target, never
# authenticated, so no token ever needs to reach the frontend or this code.
GITHUB_HTTPS_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(\.git)?/?$"
)


def parse_github_url(url: str) -> tuple[str, str]:
    """Validate `url` is a plain https://github.com/<owner>/<repo> URL and
    return (owner, repo). Raises GitCloneError otherwise — this is the only
    gate against passing something unexpected to `git clone`."""
    match = GITHUB_HTTPS_URL_RE.match(url.strip())
    if not match:
        raise GitCloneError(
            f"'{url}' is not a valid GitHub repository URL. Expected the form "
            "https://github.com/<owner>/<repo>."
        )
    return match.group("owner"), match.group("repo")


def clone_github_repository(url: str, cache_root: Path) -> Path:
    """Shallow-clone a public GitHub repository into `cache_root` for
    indexing. Idempotent: if the target directory already holds a clone of
    this URL, it is reused rather than re-cloned. Never accepts anything
    other than a plain github.com HTTPS URL, and never carries a token."""
    owner, repo = parse_github_url(url)
    dest = cache_root / f"{owner}__{repo}"

    if dest.exists():
        if (dest / ".git").is_dir():
            return dest
        # Leftover from a previous failed/partial clone — clear it and retry.
        shutil.rmtree(dest, ignore_errors=True)

    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        Repo.clone_from(url, dest, depth=1, single_branch=True)
    except GitCommandError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitCloneError(
            f"Could not clone '{url}'. Check that the repository exists, is public, "
            "and that this network can reach github.com."
        ) from exc
    return dest


@dataclass
class CommitInfo:
    hexsha: str
    message: str
    branch: str


def ensure_repo(path: Path) -> Repo:
    try:
        return Repo(path)
    except InvalidGitRepositoryError:
        return Repo.init(path)


def branch_name_for_workflow(workflow_id: str) -> str:
    return f"intent2deploy/{workflow_id}"


def create_branch(repo_path: Path, workflow_id: str, base_branch: str = "main") -> str:
    repo = ensure_repo(repo_path)
    branch_name = branch_name_for_workflow(workflow_id)
    try:
        if branch_name in repo.heads:
            repo.heads[branch_name].checkout()
        elif not repo.heads:
            # Fresh repository with no commits yet: there is nothing to
            # branch "from" — the workflow branch simply becomes whatever
            # gets the first commit.
            repo.git.checkout("-b", branch_name)
        elif base_branch in repo.heads:
            repo.git.checkout(base_branch, "-b", branch_name)
        else:
            repo.git.checkout(repo.active_branch.name, "-b", branch_name)
    except GitCommandError as exc:
        raise GitOperationError(f"Failed to create branch '{branch_name}': {exc}") from exc
    return branch_name


def status(repo_path: Path) -> list[str]:
    repo = ensure_repo(repo_path)
    return [item.a_path for item in repo.index.diff(None)] + repo.untracked_files


def diff(repo_path: Path) -> str:
    repo = ensure_repo(repo_path)
    return repo.git.diff()


def commit(repo_path: Path, message: str, files: list[str] | None = None) -> CommitInfo:
    repo = ensure_repo(repo_path)
    try:
        if files:
            repo.index.add(files)
        else:
            repo.git.add(A=True)
        commit_obj = repo.index.commit(message)
    except GitCommandError as exc:
        raise GitOperationError(f"Commit failed: {exc}") from exc
    return CommitInfo(hexsha=commit_obj.hexsha, message=message, branch=repo.active_branch.name)
