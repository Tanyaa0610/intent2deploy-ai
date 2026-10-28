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


def integration_branch_on_remote(url: str, env: dict | None = None) -> str | None:
    """The staging branch name if the remote has it (None otherwise or on error)."""
    from git.cmd import Git

    from app.core.config import settings

    if not settings.staging_branch:
        return None
    git = Git()
    try:
        with git.custom_environment(**(env or {})):
            out = git.ls_remote("--heads", url, settings.staging_branch)
    except GitCommandError:
        return None
    return settings.staging_branch if out.strip() else None


def refresh_clone(dest: Path, clone_url: str, env: dict | None = None) -> None:
    """Re-download an app-owned clone in place (latest staging if present,
    else the default branch), so a resumed workflow sees the repository as
    it is now — e.g. after branches were deleted or code was pushed."""
    from app.services.validation.sandbox import _force_rmtree

    branch = integration_branch_on_remote(clone_url, env)
    if dest.exists():
        _force_rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    extra = {"branch": branch} if branch else {}
    try:
        Repo.clone_from(clone_url, dest, depth=1, single_branch=True, env=env or {}, **extra)
    except GitCommandError as exc:
        raise GitOperationError(f"Could not re-download {clone_url}: {(exc.stderr or str(exc)).strip()[-300:]}") from exc


def clone_github_repository(url: str, cache_root: Path) -> Path:
    """Shallow-clone a public GitHub repository into `cache_root` for
    indexing. Always clones fresh: a cached clone goes stale (e.g. one made
    while the repository was still empty would never see later pushes).
    Never accepts anything other than a plain github.com HTTPS URL, and
    never carries a token."""
    from app.services.repos.manager import _git_env  # no prompts, no stored credential helpers
    from app.services.validation.sandbox import _force_rmtree

    owner, repo = parse_github_url(url)
    dest = cache_root / f"{owner}__{repo}"
    if dest.exists():
        _force_rmtree(dest)

    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        # Analyse the branch features are built from (staging, when it exists),
        # so planning and code generation see the same code the change lands on.
        branch = integration_branch_on_remote(url, _git_env(None))
        extra = {"branch": branch} if branch else {}
        Repo.clone_from(url, dest, depth=1, single_branch=True, env=_git_env(None), **extra)
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


# ---------------------------------------------------------------------------
# Feature-branch workflow: main stays stable; every change lives on its own
# branch created from the latest main and reaches main only through a PR.
# ---------------------------------------------------------------------------
PROTECTED_BRANCHES = {"main", "master"}


def protected_branches() -> set[str]:
    """Branches that only ever change through a merged pull request."""
    from app.core.config import settings

    return PROTECTED_BRANCHES | ({settings.staging_branch} if settings.staging_branch else set())


def feature_branch_name(workflow_id: str, intent: str) -> str:
    """'Add password reset' -> 'feature/add-password-reset-1a2b3c'."""
    words = re.findall(r"[a-z0-9]+", intent.lower())[:6]
    slug = "-".join(words)[:40].strip("-") or "change"
    return f"feature/{slug}-{workflow_id[:6]}"


def change_title(intent: str, limit: int = 65) -> str:
    """'Build a **Self-Healing** CI pipeline …' -> 'feat: Build a Self-Healing CI pipeline'."""
    text = re.sub(r"[*_`#>\[\]]", "", intent.strip().splitlines()[0] if intent.strip() else "change")
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return f"feat: {text}"


@dataclass
class BaseBranchInfo:
    base_branch: str
    sha: str | None  # commit the feature branch starts from (None: repository has no commits)
    fetched: bool  # True if taken from the remote's latest state
    remote_empty: bool = False
    note: str = ""


def remote_heads(repo: Repo, remote_url: str) -> tuple[list[str], str | None]:
    """Branch names on the remote and its default branch (from HEAD)."""
    out = repo.git.ls_remote("--symref", remote_url)
    heads: list[str] = []
    default = None
    for line in out.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default = line[len("ref: refs/heads/") : -len("\tHEAD")]
        elif "\trefs/heads/" in line:
            heads.append(line.split("\trefs/heads/", 1)[1])
    return heads, default


def pick_base(heads: list[str], default: str | None) -> str | None:
    if "main" in heads:
        return "main"
    if default and default in heads:
        return default
    return "master" if "master" in heads else (heads[0] if heads else None)


def prepare_feature_branch(
    repo_path: Path, branch: str, remote_url: str | None, env: dict | None = None, prefer: str | None = None
) -> BaseBranchInfo:
    """Check out `branch` in the workspace, starting from the latest `main`.

    With a remote, `main` (or the default branch if there is no `main`) is
    fetched fresh, so the feature never starts from a stale copy. If the
    remote is empty, a local `main` is initialized with the current files as
    its first commit (pushed later only as that initialization). Without a
    remote, the local `main`/current branch is used.
    """
    repo = ensure_repo(repo_path)
    # Keep validation by-products (caches) out of commits without adding a
    # tracked file: .git/info/exclude is local to this workspace.
    exclude = Path(repo.git_dir) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as fh:
        fh.write("\n__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n.mypy_cache/\n")
    try:
        if remote_url:
            with repo.git.custom_environment(**(env or {})):
                heads, default = remote_heads(repo, remote_url)
                # Start from the integration branch (staging) when it exists, else main.
                base = prefer if prefer and prefer in heads else pick_base(heads, default)
                if base:
                    repo.git.fetch("--depth", "50", remote_url, f"+refs/heads/{base}:refs/remotes/upstream/{base}")
            if base:
                repo.git.checkout("-f", "-B", branch, f"refs/remotes/upstream/{base}")
                repo.git.clean("-fd")  # the branch must contain exactly latest main
                return BaseBranchInfo(base, repo.head.commit.hexsha, fetched=True)
            remote_empty = True
        else:
            remote_empty = False

        if not repo.head.is_valid():
            # No commits at all: the current files become main's first commit.
            repo.git.checkout("-b", "main")
            repo.git.add(A=True)
            repo.git.commit("--allow-empty", "-m", "Initialize repository")
            base = "main"
        else:
            # Branch from the current commit; switching branches here could
            # fail on (or drop) uncommitted work copied from a local folder.
            base = repo.active_branch.name
        repo.git.checkout("-B", branch)
        if repo.is_dirty(untracked_files=True):
            repo.git.add(A=True)
            repo.git.commit("-m", "Baseline snapshot (pre-Intent2Deploy AI changes)")
        note = "Remote repository is empty: main was initialized locally." if remote_empty else "No remote: branched from local main."
        return BaseBranchInfo(base, repo.head.commit.hexsha, fetched=False, remote_empty=remote_empty, note=note)
    except GitCommandError as exc:
        raise GitOperationError(f"Could not prepare branch '{branch}' from main: {exc.stderr or exc}") from exc


def checkout_branch(repo_path: Path, branch: str) -> None:
    repo = ensure_repo(repo_path)
    try:
        if branch in repo.heads:
            repo.heads[branch].checkout()
        else:
            repo.git.checkout("-b", branch)
    except GitCommandError as exc:
        raise GitOperationError(f"Could not check out '{branch}': {exc}") from exc


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
