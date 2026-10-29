"""Push/PR/CI target the workflow's own repository, the workspace keeps the
repository's git history (so the branch is pushable / PR-able), and tokens
never end up in git config."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from git import Actor, Repo

from app.core import config
from app.services.git import git_ops
from app.services.github import github_ops
from app.services.github.github_ops import GitHubTarget, parse_github_remote, resolve_target
from app.services.validation.sandbox import create_workspace

AUTHOR = Actor("Test", "test@example.com")


def _git_repo_with_commit(path):
    path.mkdir()
    repo = Repo.init(path, initial_branch="main")
    (path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    repo.index.add(["app.py"])
    commit = repo.index.commit("initial", author=AUTHOR, committer=AUTHOR)
    return repo, commit


def test_parse_github_remote_variants():
    assert parse_github_remote("https://github.com/acme/shop") == ("acme", "shop")
    assert parse_github_remote("https://github.com/acme/shop.git") == ("acme", "shop")
    assert parse_github_remote("git@github.com:acme/shop.git") == ("acme", "shop")
    assert parse_github_remote("https://x-access-token:abc@github.com/acme/shop.git") == ("acme", "shop")
    assert parse_github_remote("https://gitlab.com/acme/shop") is None
    assert parse_github_remote("") is None


def test_target_is_the_workflows_repository_not_server_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "github_owner", "someone-else")
    monkeypatch.setattr(config.settings, "github_repo", "other-repo")

    connected = SimpleNamespace(remote_url="https://github.com/acme/shop.git", source="", local_path=str(tmp_path))
    target = resolve_target(connected)
    assert (target.full_name, target.source) == ("acme/shop", "connected repository")

    repo, _ = _git_repo_with_commit(tmp_path / "local")
    repo.create_remote("origin", "git@github.com:acme/local-app.git")
    local = SimpleNamespace(remote_url="", source=str(tmp_path / "local"), local_path=str(tmp_path / "local"))
    target = resolve_target(local)
    assert (target.full_name, target.source) == ("acme/local-app", "local origin remote")

    plain = SimpleNamespace(remote_url="", source="", local_path=str(tmp_path))
    assert resolve_target(plain).source == "server settings"  # fallback only
    monkeypatch.setattr(config.settings, "github_owner", "")
    assert resolve_target(plain) is None


def test_workspace_keeps_history_so_branch_builds_on_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspaces_dir", str(tmp_path / "ws"))
    src, original = _git_repo_with_commit(tmp_path / "src")

    workspace = create_workspace("wf1", tmp_path / "src")
    git_ops.create_branch(workspace, "wf1", "main")
    with Repo(workspace) as ws_repo:  # close it: an open repo locks files on Windows
        assert ws_repo.active_branch.name == "intent2deploy/wf1"
        assert ws_repo.head.commit.hexsha == original.hexsha  # same history as the source
    src.close()

    create_workspace("wf1", tmp_path / "src")  # re-creating removes read-only git objects
    assert Repo(tmp_path / "src").active_branch.name == "main"  # source repository untouched


def test_push_uses_env_token_and_never_writes_it_to_git_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspaces_dir", str(tmp_path / "ws"))
    _git_repo_with_commit(tmp_path / "src")
    bare = Repo.init(tmp_path / "remote.git", bare=True)
    workspace = create_workspace("wf2", tmp_path / "src")
    git_ops.create_branch(workspace, "wf2", "main")
    (workspace / "new.py").write_text("x = 1\n", encoding="utf-8")
    git_ops.commit(workspace, "change")

    class LocalTarget(GitHubTarget):
        @property
        def clone_url(self) -> str:  # a local bare repo stands in for GitHub
            return str(tmp_path / "remote.git")

    secret = "ghp_" + "S" * 36
    github_ops.push_branch(workspace, "intent2deploy/wf2", LocalTarget("acme", "shop", "connected repository"), secret)
    assert "intent2deploy/wf2" in [h.name for h in bare.heads]
    assert secret not in (workspace / ".git" / "config").read_text(encoding="utf-8")


def test_push_without_target_or_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "github_token", "")
    with pytest.raises(github_ops.GitHubNotConfiguredError, match="not linked"):
        github_ops.push_branch(tmp_path, "b", None, "tok")
    with pytest.raises(github_ops.GitHubNotConfiguredError, match="token"):
        github_ops.push_branch(tmp_path, "b", GitHubTarget("a", "b", "connected repository"), "")


def test_ci_status_endpoint_reports_each_situation_and_feeds_pipeline(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import Session, SQLModel, create_engine

    from app.api.deps import get_session
    from app.main import app
    from app.models.models import Project, Repository, Workflow
    from app.models.enums import WorkflowState
    from app.services.pipeline_view import build_pipeline

    monkeypatch.setattr(config.settings, "github_token", "")
    monkeypatch.setattr(config.settings, "github_owner", "")
    engine = create_engine(f"sqlite:///{tmp_path / 'ci.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        p = Project(name="p")
        s.add(p)
        s.commit()
        gh = Repository(project_id=p.id, source="https://github.com/acme/shop", local_path=str(tmp_path), remote_url="https://github.com/acme/shop.git")
        local = Repository(project_id=p.id, source=str(tmp_path), local_path=str(tmp_path))
        s.add(gh)
        s.add(local)
        s.commit()
        wf_gh = Workflow(project_id=p.id, repository_id=gh.id, intent="x", branch_name="intent2deploy/a", state=WorkflowState.COMMITTED)
        wf_local = Workflow(project_id=p.id, repository_id=local.id, intent="x", branch_name="intent2deploy/b", state=WorkflowState.COMMITTED)
        s.add(wf_gh)
        s.add(wf_local)
        s.commit()
        ids = (wf_gh.id, wf_local.id)

    def _override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    seen = {}

    def fake_status(target, branch, token=None):
        seen.update(repo=target.full_name, branch=branch, token=token)
        return github_ops.BranchCIStatus("success", "CI: completed (success)", "https://github.com/acme/shop/actions/runs/1", 1)

    monkeypatch.setattr(github_ops, "get_branch_ci_status", fake_status)
    try:
        client = TestClient(app)
        assert client.post(f"/api/workflows/{ids[1]}/github/ci", json={}).json()["status"] == "not_linked"
        assert client.post(f"/api/workflows/{ids[0]}/github/ci", json={}).json()["status"] == "needs_token"

        body = client.post(f"/api/workflows/{ids[0]}/github/ci", json={"token": "tok"}).json()
        assert body["status"] == "success" and body["repository"] == "acme/shop"
        assert seen == {"repo": "acme/shop", "branch": "intent2deploy/a", "token": "tok"}  # the workflow's own repo/branch
        assert "tok" not in str(body)

        with Session(engine) as s:
            stage = next(x for x in build_pipeline(s, ids[0])["stages"] if x["name"] == "CI/CD")
        assert stage["status"] == "PASSED" and "GitHub Actions" in stage["output"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_workflow_is_not_reported_complete_while_its_pull_request_is_open(db_session, demo_repo_copy):
    """Local CI passing doesn't deliver anything: the final report waits for the merge."""
    from app.models.enums import WorkflowState
    from app.models.models import GitOperation, Repository
    from app.services import orchestrator as orch
    from app.services.pipeline_view import build_pipeline

    project = orch.create_project(db_session, "Delivery")
    repo = orch.register_repository(db_session, project.id, str(demo_repo_copy))
    row = db_session.get(Repository, repo.id)
    row.remote_url = "https://github.com/acme/shop.git"
    wf = orch.create_workflow(db_session, project.id, repo.id, "Add password reset functionality with appropriate tests.")
    wf.state, wf.base_branch = WorkflowState.COMPLETED, "main"
    db_session.add_all([row, wf, GitOperation(workflow_id=wf.id, operation="pr_created", detail="u", ref="3", approved=True)])
    db_session.commit()

    def stage(name):
        return next(s for s in build_pipeline(db_session, wf.id)["stages"] if s["name"] == name)

    assert stage("GitHub / PR")["status"] == "AWAITING_APPROVAL"
    report = stage("Final Report")
    assert report["status"] == "PENDING" and "approved and merged" in report["output"]

    db_session.add(GitOperation(workflow_id=wf.id, operation="merged", detail="PR #3", ref="abc12345", approved=True))
    db_session.commit()
    assert stage("Final Report")["status"] == "PASSED"
