"""Git integration (master spec §18): branch creation, status, diff, commit.

Uses GitPython. Commit only happens after explicit human approval
(enforced by the orchestrator's state machine, not here). Push is a
separate, also-gated operation in github/github_ops.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo


class GitOperationError(Exception):
    pass


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
