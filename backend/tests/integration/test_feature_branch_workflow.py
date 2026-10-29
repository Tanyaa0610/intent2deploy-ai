"""Feature-branch workflow: changes go on a branch cut from the latest main,
reach main only via a PR merged after checks + explicit approval, and main
is never pushed to directly. A local bare repository stands in for GitHub."""
from __future__ import annotations

import pytest
from git import Actor, Repo
from sqlmodel import select

from app.models.enums import WorkflowState
from app.models.models import GitOperation
from app.services import orchestrator as orch
from app.services.git import git_ops
from app.services.github import delivery, github_ops
from app.services.github.github_ops import CheckItem, GitHubTarget, PullRequestStatus
from app.services.providers.local_provider import LocalProvider
from app.services.validation.sandbox import workspace_path

AUTHOR = Actor("Dev", "dev@example.com")
INTENT = "Add password reset functionality with appropriate tests."


class BareTarget(GitHubTarget):
    """GitHubTarget whose clone URL is a local bare repository."""

    bare_path = ""

    @property
    def clone_url(self) -> str:
        return self.bare_path


def _remote_with_demo(tmp_path, demo_repo_copy):
    """A 'GitHub' remote whose main holds the demo repository, plus the
    local clone a workflow would index."""
    bare = tmp_path / "remote.git"
    Repo.init(bare, bare=True, initial_branch="main").close()
    seed = Repo.init(demo_repo_copy, initial_branch="main")
    seed.git.add(A=True)
    seed.index.commit("initial", author=AUTHOR, committer=AUTHOR)
    seed.git.push(str(bare), "main:main")
    seed.close()
    clone = tmp_path / "clone"
    Repo.clone_from(str(bare), clone).close()
    return bare, clone


def _commit_on_remote(tmp_path, bare, edit):
    other = tmp_path / f"other-{len(list(tmp_path.iterdir()))}"
    repo = Repo.clone_from(str(bare), other)
    edit(other)
    repo.git.add(A=True)
    repo.index.commit("someone else's change", author=AUTHOR, committer=AUTHOR)
    repo.git.push("origin", "main")
    sha = repo.head.commit.hexsha
    repo.close()
    return sha


def _run_to_change_approval(db_session, clone, monkeypatch, bare):
    target = BareTarget("acme", "shop", "connected repository")
    target.bare_path = str(bare)
    monkeypatch.setattr(github_ops, "resolve_target", lambda repository: target)
    provider = LocalProvider()
    project = orch.create_project(db_session, "Feature branches")
    repo = orch.register_repository(db_session, project.id, str(clone))
    wf = orch.create_workflow(db_session, project.id, repo.id, INTENT)
    orch.run_indexing(db_session, wf.id)
    orch.run_planning(db_session, wf.id, provider)
    orch.approve_plan(db_session, wf.id, True)
    orch.run_codegen(db_session, wf.id, provider)
    return wf, target


def test_feature_branch_starts_from_latest_main_and_main_is_untouched(db_session, tmp_path, demo_repo_copy, monkeypatch):
    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, target = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    # main moves on after the code was generated, in an unrelated file.
    latest = _commit_on_remote(tmp_path, bare, lambda p: (p / "NOTES.md").write_text("new\n", encoding="utf-8"))

    wf = orch.approve_changes(db_session, wf.id, True)
    assert wf.branch_name.startswith("feature/add-password-reset")
    assert wf.base_branch == "staging"  # feature PRs target the integration branch
    with Repo(workspace_path(wf.id)) as ws:
        assert ws.active_branch.name == wf.branch_name
        assert ws.is_ancestor(latest, ws.head.commit.hexsha)  # built on the latest main
        assert (workspace_path(wf.id) / "NOTES.md").exists()

    orch.run_test_generation(db_session, wf.id, LocalProvider())
    wf = orch.run_validation(db_session, wf.id)
    wf = orch.approve_commit(db_session, wf.id, True)
    assert wf.state == WorkflowState.COMMITTED

    monkeypatch.setattr(github_ops, "find_or_create_pull_request",
                        lambda t, branch, base, title, body, token=None: github_ops.PullRequestInfo(7, "https://x/pull/7", "open"))
    result = delivery.publish(db_session, wf.id, "tok")
    assert (result["number"], result["base"], result["head"]) == (7, "staging", wf.branch_name)
    assert result["staging_created"] is True
    with Repo(bare) as remote:
        assert remote.heads["main"].commit.hexsha == latest  # main unchanged by publishing
        assert remote.heads["staging"].commit.hexsha == latest  # staging created from main, no feature code
        assert wf.branch_name in [h.name for h in remote.heads]


def test_conflict_with_newer_main_stops_safely(db_session, tmp_path, demo_repo_copy, monkeypatch):
    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, _ = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    target_file = "src/shopflow/services/auth_service.py"

    def rewrite(p):
        path = p / target_file
        path.write_text(path.read_text(encoding="utf-8").replace("def ", "def  ", 3), encoding="utf-8")

    before = _commit_on_remote(tmp_path, bare, rewrite)
    with pytest.raises(orch.OrchestratorError, match="Merge conflict"):
        orch.approve_changes(db_session, wf.id, True)
    db_session.refresh(wf)
    assert wf.state == WorkflowState.FAILED
    with Repo(bare) as remote:
        assert remote.heads["main"].commit.hexsha == before


def test_empty_remote_gets_initial_main_then_feature_branch(tmp_path):
    bare = tmp_path / "empty.git"
    Repo.init(bare, bare=True).close()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    info = git_ops.prepare_feature_branch(ws, "feature/login-abc123", str(bare))
    assert info.remote_empty and info.base_branch == "main"

    target = BareTarget("acme", "empty", "connected repository")
    target.bare_path = str(bare)
    (ws / "app.py").write_text("x = 1\n", encoding="utf-8")
    git_ops.commit(ws, "feat: login")
    assert github_ops.initialize_empty_remote(ws, "main", target, "tok") is True
    assert github_ops.initialize_empty_remote(ws, "main", target, "tok") is False  # never twice
    github_ops.push_branch(ws, "feature/login-abc123", target, "tok")
    with Repo(bare) as remote:
        main_files = remote.git.ls_tree("-r", "--name-only", "main").split()
        assert "app.py" not in main_files  # feature code is only on the feature branch
        assert "feature/login-abc123" in [h.name for h in remote.heads]


@pytest.mark.parametrize("branch", ["main", "master", "staging"])
def test_direct_push_to_protected_branch_is_refused(tmp_path, branch):
    with pytest.raises(github_ops.GitHubOperationError, match="protected"):
        github_ops.push_branch(tmp_path, branch, GitHubTarget("a", "b", "connected repository"), "tok")


def _status(**overrides) -> PullRequestStatus:
    base = dict(
        number=7, url="u", title="feat: x", state="open", merged=False, merge_sha="", base="main", head="feature/x",
        head_sha="abc", mergeable=True, mergeable_state="clean", checks=[CheckItem("CI", "completed", "success")],
        viewer="dev", viewer_can_merge=True,
    )
    base.update(overrides)
    return PullRequestStatus(**base)


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"mergeable": False, "mergeable_state": "dirty"}, "conflicts"),
        ({"mergeable_state": "behind"}, "behind"),
        ({"checks": [CheckItem("CI", "in_progress", "")]}, "still running"),
        ({"checks": [CheckItem("CI", "completed", "failure")]}, "failed"),
        ({"viewer_can_merge": False}, "write access"),
        ({"mergeable": None}, "still checking"),
        ({"mergeable_state": "blocked"}, "branch protection"),
        ({"state": "closed"}, "closed"),
    ],
)
def test_merge_blockers(db_session, overrides, fragment):
    blockers = delivery.evaluate(db_session, "wf", _status(**overrides))
    assert any(fragment in b for b in blockers), blockers


def test_merge_requires_approval_and_clean_checks(db_session, tmp_path, demo_repo_copy, monkeypatch):
    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, _ = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, LocalProvider())
    orch.run_validation(db_session, wf.id)
    orch.approve_commit(db_session, wf.id, True)
    db_session.add(GitOperation(workflow_id=wf.id, operation="pr_created", detail="u", ref="7", approved=True))
    db_session.commit()

    merged = {}
    state = {"st": _status(checks=[CheckItem("CI", "completed", "failure")])}
    monkeypatch.setattr(github_ops, "get_pull_request_status", lambda t, n, token=None: state["st"])

    def fake_merge(t, number, sha, title, message, token=None):
        merged.update(number=number, sha=sha)
        return "mergesha"

    monkeypatch.setattr(github_ops, "merge_pull_request", fake_merge)

    with pytest.raises(delivery.DeliveryError, match="explicit approval"):
        delivery.merge(db_session, wf.id, "tok", approved=False)
    with pytest.raises(delivery.DeliveryError, match="failed"):
        delivery.merge(db_session, wf.id, "tok", approved=True)
    assert not merged

    state["st"] = _status()
    result = delivery.merge(db_session, wf.id, "tok", approved=True, comment="LGTM")
    assert result["status"] == "merged" and merged == {"number": 7, "sha": "abc"}  # merges exactly the checked head
    db_session.refresh(wf)
    assert wf.state == WorkflowState.COMPLETED
    ops = {g.operation for g in db_session.exec(select(GitOperation).where(GitOperation.workflow_id == wf.id)).all()}
    assert "merged" in ops



def test_without_staging_feature_prs_target_main(db_session, tmp_path, demo_repo_copy, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "staging_branch", "")
    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, _ = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    wf = orch.approve_changes(db_session, wf.id, True)
    assert wf.base_branch == "main"


def test_release_requires_staging_verification_and_approval(db_session, tmp_path, demo_repo_copy, monkeypatch):
    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, _ = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, LocalProvider())
    orch.run_validation(db_session, wf.id)
    orch.approve_commit(db_session, wf.id, True)

    with pytest.raises(delivery.DeliveryError, match="Merge the feature pull request"):
        delivery.release_open(db_session, wf.id, "tok")  # feature not in staging yet

    db_session.add(GitOperation(workflow_id=wf.id, operation="merged", detail="PR #7 into staging", ref="abc", approved=True))
    db_session.commit()
    opened = {}
    monkeypatch.setattr(github_ops, "compare_commits", lambda t, base, head, token=None: ["feat: Add password reset"])

    def fake_open(t, branch, base, title, body, token=None):
        opened.update(head=branch, base=base, body=body)
        return github_ops.PullRequestInfo(9, "https://x/pull/9", "open")

    monkeypatch.setattr(github_ops, "find_or_create_pull_request", fake_open)
    assert delivery.release_open(db_session, wf.id, "tok")["number"] == 9
    assert (opened["head"], opened["base"]) == ("staging", "main") and "Add password reset" in opened["body"]

    monkeypatch.setattr(github_ops, "get_pull_request_status",
                        lambda t, n, token=None: _status(number=9, base="main", head="staging", head_sha="rel"))
    merged = {}

    def fake_merge(t, number, sha, title, message, token=None, method="squash"):
        merged.update(number=number, sha=sha, method=method)
        return "releasesha"

    monkeypatch.setattr(github_ops, "merge_pull_request", fake_merge)
    with pytest.raises(delivery.DeliveryError, match="ran and checked"):
        delivery.release_merge(db_session, wf.id, "tok", approved=True, verified_on_staging=False)
    with pytest.raises(delivery.DeliveryError, match="explicit approval"):
        delivery.release_merge(db_session, wf.id, "tok", approved=False, verified_on_staging=True)
    assert not merged
    result = delivery.release_merge(db_session, wf.id, "tok", approved=True, verified_on_staging=True)
    assert result["status"] == "released"
    assert merged == {"number": 9, "sha": "rel", "method": "merge"}  # merge commit keeps staging & main aligned


def test_staging_preview_runs_the_branch_locally(tmp_path, monkeypatch):
    import urllib.request

    from app.core import config
    from app.services import preview
    from app.services.greenfield import templates

    monkeypatch.setattr(config.settings, "workspaces_dir", str(tmp_path / "workspaces"))
    src = tmp_path / "proj"
    src.mkdir()
    intent = "Build a REST API for managing books"
    for f in templates.files(intent, templates.design(intent)):
        p = src / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"], encoding="utf-8")
    repo = Repo.init(src, initial_branch="staging")
    repo.git.add(A=True)
    repo.index.commit("app", author=AUTHOR, committer=AUTHOR)
    repo.close()

    info = preview.start("test@staging", str(src), "staging")
    try:
        assert info["running"] and info["url"].startswith("http://127.0.0.1:81")
        with urllib.request.urlopen(info["url"] + "/health", timeout=5) as resp:
            assert resp.read() == b'{"status":"ok"}'
    finally:
        assert preview.stop("test@staging") == {"running": False}
    assert preview.info("test@staging") == {"running": False}


def test_merge_into_staging_starts_preview_and_posts_its_address(db_session, tmp_path, demo_repo_copy, monkeypatch):
    from app.services import preview

    bare, clone = _remote_with_demo(tmp_path, demo_repo_copy)
    wf, _ = _run_to_change_approval(db_session, clone, monkeypatch, bare)
    orch.approve_changes(db_session, wf.id, True)
    orch.run_test_generation(db_session, wf.id, LocalProvider())
    orch.run_validation(db_session, wf.id)
    orch.approve_commit(db_session, wf.id, True)
    db_session.add(GitOperation(workflow_id=wf.id, operation="pr_created", detail="u", ref="7", approved=True))
    db_session.commit()

    monkeypatch.setattr(github_ops, "get_pull_request_status", lambda t, n, token=None: _status(base="staging"))
    monkeypatch.setattr(github_ops, "merge_pull_request", lambda *a, **k: "mergesha")
    started = {}

    def fake_start(key, clone_url, branch, env=None, wait_seconds=8.0):
        started.update(key=key, branch=branch)
        return {"running": True, "url": "http://127.0.0.1:8137", "open_url": "http://127.0.0.1:8137/docs", "port": 8137, "sha": "abc12345"}

    comments = []
    monkeypatch.setattr(preview, "start", fake_start)
    monkeypatch.setattr(github_ops, "comment_on_pull_request",
                        lambda t, number, body, token=None: comments.append((number, body)) or "https://x/pull/7#c1")

    result = delivery.merge(db_session, wf.id, "tok", approved=True)
    assert started == {"key": "acme/shop@staging", "branch": "staging"}
    assert result["preview"]["open_url"] == "http://127.0.0.1:8137/docs"
    assert comments and comments[0][0] == 7 and "http://127.0.0.1:8137/docs" in comments[0][1]


def test_each_project_gets_a_stable_preview_port():
    from app.services.preview import PORT_RANGE, preferred_port

    assert preferred_port("acme/shop@staging") == preferred_port("acme/shop@staging")
    assert preferred_port("acme/shop@staging") in PORT_RANGE
    assert len({preferred_port(f"user/repo{i}@staging") for i in range(20)}) > 10  # spread across projects
