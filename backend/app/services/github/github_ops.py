"""Optional GitHub integration (master spec §19, §53).

Every action here is externally visible and must only be called after
the orchestrator has recorded an explicit human approval for it.

The target repository is the one the workflow actually runs on: the
connected GitHub repository, or the GitHub `origin` of a local repository.
GITHUB_OWNER/GITHUB_REPO are only a fallback for repositories with neither.
A token (GITHUB_TOKEN, or one supplied for a single request) is required;
it is passed to git through the environment and never written to a remote
URL, .git/config, the database or a response. Without a target or token,
these functions raise GitHubNotConfiguredError and the caller falls back to
LOCAL VALIDATION only — never fabricated CI results.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from app.core.config import settings


class GitHubNotConfiguredError(Exception):
    pass


class GitHubOperationError(Exception):
    pass


_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


@dataclass
class GitHubTarget:
    owner: str
    repo: str
    source: str  # "connected repository" | "local origin remote" | "server settings"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"

    @property
    def clone_url(self) -> str:
        return f"{self.url}.git"


def parse_github_remote(url: str) -> tuple[str, str] | None:
    match = _GITHUB_REMOTE_RE.match((url or "").strip())
    return (match.group("owner"), match.group("repo")) if match else None


def settings_target() -> GitHubTarget | None:
    if settings.github_owner and settings.github_repo:
        return GitHubTarget(settings.github_owner, settings.github_repo, "server settings")
    return None


def resolve_target(repository) -> GitHubTarget | None:
    """Where this workflow's branch belongs on GitHub."""
    for candidate in (getattr(repository, "remote_url", ""), getattr(repository, "source", "")):
        parsed = parse_github_remote(candidate)
        if parsed:
            return GitHubTarget(*parsed, "connected repository")
    try:
        repo = Repo(repository.local_path)
        origin = next((r for r in repo.remotes if r.name == "origin"), None)
        if origin is not None:
            for url in origin.urls:
                parsed = parse_github_remote(url)
                if parsed:
                    return GitHubTarget(*parsed, "local origin remote")
    except (InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError):
        pass
    return settings_target()


def is_configured() -> bool:
    return bool(settings.github_token and settings_target())


def _resolve_token(token: str | None) -> str:
    token = (token or "").strip() or settings.github_token
    if not token:
        raise GitHubNotConfiguredError(
            "A GitHub token with write access is needed. Set GITHUB_TOKEN on the server or enter a token. "
            "Local validation results remain valid and are labeled LOCAL VALIDATION."
        )
    return token


def _require_target(target: GitHubTarget | None) -> GitHubTarget:
    if target is None:
        raise GitHubNotConfiguredError(
            "This workflow's repository is not linked to GitHub (no GitHub URL or origin remote). "
            "Connect it from GitHub, add a GitHub origin remote, or set GITHUB_OWNER/GITHUB_REPO."
        )
    return target


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def push_branch(repo_path: Path, branch_name: str, target: GitHubTarget | None, token: str | None = None) -> str:
    """Push a local branch to the target repository. Returns the branch name."""
    from app.services.repos.manager import _git_env  # credential-free env: header auth, no prompts

    from app.services.git.git_ops import protected_branches

    # Feature changes never go straight to main/staging: only feature branches are pushed.
    if branch_name in protected_branches():
        raise GitHubOperationError(
            f"Refusing to push to protected branch '{branch_name}'. Changes reach it only by merging a pull request."
        )
    target = _require_target(target)
    token = _resolve_token(token)
    try:
        repo = Repo(repo_path)
        with repo.git.custom_environment(**_git_env(token)):
            repo.git.push(target.clone_url, f"refs/heads/{branch_name}:refs/heads/{branch_name}")
    except GitCommandError as exc:
        detail = _scrub(f"{exc.stderr or exc}", token).strip()
        raise GitHubOperationError(f"Push to {target.full_name} failed: {detail[-400:]}") from exc
    return branch_name


def initialize_empty_remote(repo_path: Path, base_branch: str, target: GitHubTarget | None, token: str | None = None) -> bool:
    """For a repository with no branches at all, push the base branch's
    initial commit so a pull request has something to target. Verifies the
    remote is empty first and never overwrites an existing branch. Returns
    True if it initialized the remote."""
    from app.services.git.git_ops import remote_heads
    from app.services.repos.manager import _git_env

    target = _require_target(target)
    token = _resolve_token(token)
    try:
        repo = Repo(repo_path)
        with repo.git.custom_environment(**_git_env(token)):
            heads, _ = remote_heads(repo, target.clone_url)
            if heads:
                return False
            # Plain push (no --force): fails rather than overwrite if a branch appeared meanwhile.
            repo.git.push(target.clone_url, f"refs/heads/{base_branch}:refs/heads/{base_branch}")
    except GitCommandError as exc:
        detail = _scrub(f"{exc.stderr or exc}", token).strip()
        raise GitHubOperationError(f"Could not initialize {base_branch} on {target.full_name}: {detail[-400:]}") from exc
    return True


@dataclass
class PullRequestInfo:
    number: int
    url: str
    state: str


def _client_repo(target: GitHubTarget, token: str):
    try:
        from github import Github
    except ImportError as exc:
        raise GitHubOperationError("PyGithub is not installed.") from exc
    try:
        return Github(token).get_repo(target.full_name)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Cannot access {target.full_name}: {_scrub(str(exc), token)}") from exc


def create_pull_request(
    target: GitHubTarget | None, branch_name: str, base_branch: str, title: str, body: str, token: str | None = None
) -> PullRequestInfo:
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        base = base_branch
        try:
            gh_repo.get_branch(base)
        except Exception:
            base = gh_repo.default_branch
            gh_repo.get_branch(base)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(
            f"{target.full_name} has no base branch to open a pull request against (it may be empty). "
            f"The branch '{branch_name}' is pushed; merge it or make it the default branch on GitHub."
        ) from exc
    if base == branch_name:
        raise GitHubOperationError(
            f"'{branch_name}' is the default (and only) branch of {target.full_name} — the repository was empty, so "
            "this branch became its main line. There is no other branch to open a pull request against; the code is "
            "already the repository's default branch on GitHub."
        )
    try:
        pr = gh_repo.create_pull(title=title, body=body, head=branch_name, base=base)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Pull request creation failed: {_scrub(str(exc), token)}") from exc
    return PullRequestInfo(number=pr.number, url=pr.html_url, state=pr.state)


@dataclass
class WorkflowRunInfo:
    run_id: int
    status: str
    conclusion: str
    url: str


def get_latest_workflow_run(
    target: GitHubTarget | None = None, token: str | None = None, workflow_file: str = "ai-devops.yml", branch: str = ""
) -> WorkflowRunInfo | None:
    target = _require_target(target or settings_target())
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        workflow = gh_repo.get_workflow(workflow_file)
        runs = workflow.get_runs(branch=branch) if branch else workflow.get_runs()
        latest = runs[0] if runs.totalCount > 0 else None
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Failed to fetch workflow runs: {_scrub(str(exc), token)}") from exc
    if latest is None:
        return None
    return WorkflowRunInfo(
        run_id=latest.id, status=latest.status, conclusion=latest.conclusion or "", url=latest.html_url
    )


@dataclass
class BranchCIStatus:
    """Latest GitHub Actions result for one branch of the target repository."""

    state: str  # no_workflows | not_pushed | pending | queued | in_progress | success | failure | cancelled | ...
    detail: str
    url: str = ""
    run_id: int | None = None


def get_branch_ci_status(target: GitHubTarget | None, branch: str, token: str | None = None) -> BranchCIStatus:
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        try:
            gh_repo.get_branch(branch)
        except Exception:
            return BranchCIStatus("not_pushed", f"Branch '{branch}' is not on {target.full_name} yet — push it first.")
        if gh_repo.get_workflows().totalCount == 0:
            return BranchCIStatus(
                "no_workflows",
                f"{target.full_name} has no GitHub Actions workflow (.github/workflows/*.yml), so pushes run no CI.",
            )
        runs = gh_repo.get_workflow_runs(branch=branch)
        if runs.totalCount == 0:
            return BranchCIStatus("pending", "Pushed; GitHub Actions has not started a run for this branch yet.")
        run = runs[0]
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Failed to read CI status from {target.full_name}: {_scrub(str(exc), token)}") from exc
    state = run.conclusion if run.status == "completed" and run.conclusion else run.status
    return BranchCIStatus(state, f"{run.name}: {run.status}" + (f" ({run.conclusion})" if run.conclusion else ""), run.html_url, run.id)


# ---------------------------------------------------------------------------
# Pull-request lifecycle for the feature-branch workflow
# ---------------------------------------------------------------------------
def find_or_create_pull_request(
    target: GitHubTarget | None, branch: str, base: str, title: str, body: str, token: str | None = None
) -> PullRequestInfo:
    """Open a PR from `branch` into `base`, or return the open one that exists."""
    target = _require_target(target)
    token = _resolve_token(token)
    if branch == base:
        raise GitHubOperationError(f"Head and base are both '{base}'; a feature branch is required.")
    gh_repo = _client_repo(target, token)
    try:
        for pr in gh_repo.get_pulls(state="open", head=f"{target.owner}:{branch}", base=base):
            pr.edit(body=body)  # keep the summary current
            return PullRequestInfo(number=pr.number, url=pr.html_url, state=pr.state)
        pr = gh_repo.create_pull(title=title, body=body, head=branch, base=base)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Pull request creation failed: {_scrub(str(exc), token)}") from exc
    return PullRequestInfo(number=pr.number, url=pr.html_url, state=pr.state)


@dataclass
class CheckItem:
    name: str
    status: str  # queued | in_progress | completed
    conclusion: str  # success | failure | neutral | skipped | cancelled | timed_out | ... | ""
    url: str = ""
    id: int = 0  # check-run id (== Actions job id); 0 for commit statuses
    event: str = ""  # what triggered the run: push | pull_request | ...


@dataclass
class PullRequestStatus:
    number: int
    url: str
    title: str
    state: str  # open | closed
    merged: bool
    merge_sha: str
    base: str
    head: str
    head_sha: str
    mergeable: bool | None  # None while GitHub is still computing it
    mergeable_state: str  # clean | dirty | behind | blocked | unstable | unknown | draft | has_hooks
    checks: list[CheckItem]
    viewer: str
    viewer_can_merge: bool

    @property
    def checks_pending(self) -> list[CheckItem]:
        return [c for c in self.checks if c.status != "completed"]

    @property
    def checks_failed(self) -> list[CheckItem]:
        return [c for c in self.checks if c.status == "completed" and c.conclusion not in ("success", "neutral", "skipped")]


def get_pull_request_status(target: GitHubTarget | None, number: int, token: str | None = None) -> PullRequestStatus:
    target = _require_target(target)
    token = _resolve_token(token)
    try:
        from github import Github
    except ImportError as exc:
        raise GitHubOperationError("PyGithub is not installed.") from exc
    try:
        gh = Github(token)
        gh_repo = gh.get_repo(target.full_name)
        pr = gh_repo.get_pull(number)
        commit = gh_repo.get_commit(pr.head.sha)
        run_events: dict[str, str] = {}

        def _event(details_url: str) -> str:
            match = re.search(r"/actions/runs/(\d+)", details_url or "")
            if not match:
                return ""
            run_id = match.group(1)
            if run_id not in run_events:
                try:
                    run_events[run_id] = gh_repo.get_workflow_run(int(run_id)).event
                except Exception:
                    run_events[run_id] = ""
            return run_events[run_id]

        checks = [
            CheckItem(r.name, r.status, r.conclusion or "", r.html_url or "", r.id, _event(r.details_url or r.html_url or ""))
            for r in commit.get_check_runs()
        ]
        checks += [
            CheckItem(s.context, "completed" if s.state != "pending" else "in_progress",
                      {"success": "success", "pending": ""}.get(s.state, "failure"), s.target_url or "")
            for s in commit.get_combined_status().statuses
        ]
        perms = gh_repo.permissions
        can_merge = bool(perms and (perms.push or getattr(perms, "maintain", False) or perms.admin))
        viewer = gh.get_user().login
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Could not read pull request #{number}: {_scrub(str(exc), token)}") from exc
    return PullRequestStatus(
        number=pr.number, url=pr.html_url, title=pr.title, state=pr.state, merged=pr.merged,
        merge_sha=pr.merge_commit_sha or "", base=pr.base.ref, head=pr.head.ref, head_sha=pr.head.sha,
        mergeable=pr.mergeable, mergeable_state=pr.mergeable_state or "unknown", checks=checks,
        viewer=viewer, viewer_can_merge=can_merge,
    )


def update_pull_request_branch(target: GitHubTarget | None, number: int, token: str | None = None) -> None:
    """Merge the latest base into the PR branch on GitHub (no force-push)."""
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        ok = gh_repo.get_pull(number).update_branch()
    except Exception as exc:  # pragma: no cover - network dependent
        text = _scrub(str(exc), token)
        if "conflict" in text.lower() or "422" in text:
            raise GitHubOperationError(
                "The branch has merge conflicts with the base branch and cannot be updated automatically. "
                "Resolve them on GitHub, or start a new workflow (it will be generated from the latest main)."
            ) from exc
        raise GitHubOperationError(f"Could not update the branch: {text}") from exc
    if not ok:
        raise GitHubOperationError("GitHub did not accept the branch update.")


def merge_pull_request(
    target: GitHubTarget | None,
    number: int,
    expected_head_sha: str,
    title: str,
    message: str,
    token: str | None = None,
    method: str = "squash",
) -> str:
    """Merge the PR (squash by default), but only if its head is still the commit whose
    checks were verified (GitHub rejects the merge otherwise). Returns the
    merge commit SHA."""
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        result = gh_repo.get_pull(number).merge(
            commit_title=title, commit_message=message, merge_method=method, sha=expected_head_sha
        )
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Merge was refused by GitHub: {_scrub(str(exc), token)}") from exc
    if not result.merged:
        raise GitHubOperationError(f"Merge was not completed: {result.message}")
    return result.sha


# ---------------------------------------------------------------------------
# Check details: steps, per-step output and individual test results
# ---------------------------------------------------------------------------
_TS_RE = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TEST_LINE_RE = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b")
_TEST_SUMMARY_RE = re.compile(r"(\d+ (?:passed|failed|errors?)\b[^=\n]*? in [\d.]+s)")


def parse_actions_log(text: str, tail: int = 25) -> dict:
    """Split a GitHub Actions job log into per-command output sections and
    extract pytest results (names with `pytest -v`, a summary otherwise)."""
    sections: list[dict] = []
    current: dict | None = None
    in_header = False
    tests: list[dict] = []
    summary = ""
    for raw in text.splitlines():
        line = _ANSI_RE.sub("", _TS_RE.sub("", raw)).rstrip()
        if line.startswith("##[group]"):
            title = line[len("##[group]"):].strip()
            current = {"title": title, "output": []} if title.startswith("Run ") else None
            if current is not None:
                sections.append(current)
            in_header = True
            continue
        if line.startswith("##[endgroup]"):
            in_header = False
            continue
        if in_header or current is None:
            continue
        if line.startswith("##[error]"):
            line = "ERROR: " + line[len("##[error]"):]
        if line.strip():
            current["output"].append(line)
        test = _TEST_LINE_RE.match(line.strip())
        if test:
            tests.append({"name": test.group(1), "outcome": test.group(2)})
        found = _TEST_SUMMARY_RE.search(line)
        if found:
            summary = found.group(1)
    for sec in sections:
        sec["output"] = sec["output"][-tail:]
    return {"sections": sections, "tests": tests, "test_summary": summary}


def get_check_details(target: GitHubTarget | None, check_id: int, token: str | None = None) -> dict:
    """Steps, durations, per-step output and test results for one check."""
    import httpx

    target = _require_target(target)
    token = _resolve_token(token)
    api = f"https://api.github.com/repos/{target.full_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def _seconds(start: str | None, end: str | None) -> float | None:
        from datetime import datetime

        if not start or not end:
            return None
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds()

    try:
        # httpx drops the Authorization header on the cross-origin log redirect.
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            job = client.get(f"{api}/actions/jobs/{check_id}", headers=headers)
            if job.status_code == 404:
                run = client.get(f"{api}/check-runs/{check_id}", headers=headers)
                run.raise_for_status()
                data = run.json()
                output = data.get("output") or {}
                return {
                    "name": data.get("name", ""), "event": "", "status": data.get("status", ""),
                    "conclusion": data.get("conclusion") or "", "url": data.get("html_url", ""),
                    "steps": [], "sections": [], "tests": [],
                    "test_summary": " ".join(x for x in (output.get("title"), output.get("summary")) if x)[:500],
                    "logs_available": False,
                }
            job.raise_for_status()
            j = job.json()
            event = ""
            run = client.get(f"{api}/actions/runs/{j['run_id']}", headers=headers)
            if run.status_code == 200:
                event = run.json().get("event", "")
            logs = client.get(f"{api}/actions/jobs/{check_id}/logs", headers=headers)
            parsed = parse_actions_log(logs.text) if logs.status_code == 200 else {"sections": [], "tests": [], "test_summary": ""}
    except httpx.HTTPError as exc:
        raise GitHubOperationError(f"Could not load check details: {_scrub(str(exc), token)}") from exc

    return {
        "name": j.get("name", ""),
        "event": event,
        "status": j.get("status", ""),
        "conclusion": j.get("conclusion") or "",
        "url": j.get("html_url", ""),
        "seconds": _seconds(j.get("started_at"), j.get("completed_at")),
        "steps": [
            {"number": st.get("number"), "name": st.get("name", ""), "status": st.get("status", ""),
             "conclusion": st.get("conclusion") or "", "seconds": _seconds(st.get("started_at"), st.get("completed_at"))}
            for st in j.get("steps", [])
        ],
        **parsed,
        "logs_available": logs.status_code == 200,
    }


def create_remote_branch(
    repo_path: Path, new_branch: str, source_ref: str, target: GitHubTarget | None, token: str | None = None
) -> bool:
    """Create `new_branch` on the remote pointing at `source_ref` (e.g. the
    integration branch from main's head). Never moves an existing branch.
    Returns True if it created the branch."""
    from app.services.git.git_ops import remote_heads
    from app.services.repos.manager import _git_env

    target = _require_target(target)
    token = _resolve_token(token)
    try:
        repo = Repo(repo_path)
        with repo.git.custom_environment(**_git_env(token)):
            heads, _ = remote_heads(repo, target.clone_url)
            if new_branch in heads:
                return False
            repo.git.push(target.clone_url, f"{source_ref}:refs/heads/{new_branch}")  # no --force
    except GitCommandError as exc:
        detail = _scrub(f"{exc.stderr or exc}", token).strip()
        raise GitHubOperationError(f"Could not create '{new_branch}' on {target.full_name}: {detail[-400:]}") from exc
    return True


def compare_commits(target: GitHubTarget | None, base: str, head: str, token: str | None = None) -> list[str]:
    """First lines of the commits on `head` that are not on `base`."""
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        cmp = gh_repo.compare(base, head)
        return [c.commit.message.splitlines()[0] for c in cmp.commits]
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Could not compare {base}...{head}: {_scrub(str(exc), token)}") from exc


def comment_on_pull_request(target: GitHubTarget | None, number: int, body: str, token: str | None = None) -> str:
    """Add a comment to a PR; returns the comment URL."""
    target = _require_target(target)
    token = _resolve_token(token)
    gh_repo = _client_repo(target, token)
    try:
        comment = gh_repo.get_issue(number).create_comment(body)
    except Exception as exc:  # pragma: no cover - network dependent
        raise GitHubOperationError(f"Could not comment on #{number}: {_scrub(str(exc), token)}") from exc
    return comment.html_url
