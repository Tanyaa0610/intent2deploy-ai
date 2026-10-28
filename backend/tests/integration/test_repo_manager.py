"""Repository Manager API: path validation, no-overwrite creation, local
connect, browsing/search confinement, GitHub clone error handling and token
hygiene."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import GitCommandError
from sqlmodel import Session, SQLModel, create_engine, select

DEMO_REPO = Path(__file__).resolve().parents[3] / "demo-repository"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app.api.deps import get_session
    from app.core import config
    from app.main import app

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(config.settings, "allowed_repo_roots", str(root))
    monkeypatch.setattr(config.settings, "cloned_repos_dir", str(root / "clones"))
    monkeypatch.setattr(config.settings, "github_token", "")

    engine = create_engine(f"sqlite:///{tmp_path / 'rm.db'}")
    SQLModel.metadata.create_all(engine)

    def _override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        yield TestClient(app), root, engine
    finally:
        app.dependency_overrides.pop(get_session, None)


def _demo_copy(root: Path) -> Path:
    dest = root / "shop"
    shutil.copytree(DEMO_REPO, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (dest / ".env").write_text("SECRET=abc\n")
    return dest


# --- create ---------------------------------------------------------------
def test_create_repository_with_git_and_readme(env):
    client, root, _ = env
    target = root / "fresh"
    resp = client.post("/api/repositories/create", json={"path": str(target), "name": "Fresh", "index": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "created" and body["name"] == "Fresh"
    assert (target / "README.md").read_text().startswith("# Fresh")
    assert (target / ".git").is_dir()

    detail = client.get(f"/api/repositories/{body['id']}/details").json()
    assert detail["status"] == "ready"
    assert detail["is_git"] is True and detail["branch"]
    assert detail["indexed_at"] is not None


def test_create_never_overwrites(env):
    client, root, _ = env
    target = root / "existing"
    target.mkdir()
    (target / "README.md").write_text("mine")
    resp = client.post("/api/repositories/create", json={"path": str(target)})
    assert resp.status_code == 400
    assert "not empty" in resp.json()["detail"]
    assert (target / "README.md").read_text() == "mine"
    assert not (target / ".git").exists()

    a_file = root / "file.txt"
    a_file.write_text("x")
    assert client.post("/api/repositories/create", json={"path": str(a_file)}).status_code == 400
    assert a_file.read_text() == "x"


@pytest.mark.parametrize(
    "path_fn",
    [
        lambda root: "relative/path",
        lambda root: str(root / ".." / "escaped"),
        lambda root: str(root.parent.parent / "elsewhere"),
        lambda root: str(root / ".ssh" / "repo"),
        lambda root: str(root / "missing-parent" / "repo"),
    ],
)
def test_create_rejects_unsafe_paths(env, path_fn):
    client, root, _ = env
    path = path_fn(root)
    resp = client.post("/api/repositories/create", json={"path": path})
    assert resp.status_code == 400, resp.text
    assert not (root.parent / "escaped").exists()


# --- connect local / browse ----------------------------------------------
def test_connect_local_index_browse_search(env):
    client, root, _ = env
    repo_dir = _demo_copy(root)

    resp = client.post("/api/repositories/connect-local", json={"path": str(repo_dir)})
    assert resp.status_code == 200, resp.text
    repo_id = resp.json()["id"]

    assert client.post("/api/repositories/connect-local", json={"path": str(repo_dir)}).status_code == 409

    listed = client.get("/api/repositories/managed").json()
    assert [r["id"] for r in listed] == [repo_id]
    assert listed[0]["status"] == "ready" and listed[0]["chunk_count"] > 0

    entries = client.get(f"/api/repositories/{repo_id}/tree").json()["entries"]
    names = {e["name"]: e for e in entries}
    assert "src" in names and names["src"]["type"] == "dir"
    assert names[".env"]["restricted"] is True

    sub = client.get(f"/api/repositories/{repo_id}/tree", params={"path": "src"}).json()
    assert all(e["path"].startswith("src/") for e in sub["entries"])

    f = client.get(f"/api/repositories/{repo_id}/file", params={"path": "src/shopflow/services/payment_service.py"})
    assert f.status_code == 200 and "def " in f.json()["content"]

    for bad in ["../../etc/passwd", "..", ".env", ".git/config"]:
        r = client.get(f"/api/repositories/{repo_id}/file", params={"path": bad})
        assert r.status_code == 400, bad

    grep = client.get(f"/api/repositories/{repo_id}/grep", params={"q": "payment"}).json()
    assert grep["results"] and all(not r["file"].startswith(".env") for r in grep["results"])
    assert not any("SECRET=abc" in r["text"] for r in grep["results"])

    insights = client.get(f"/api/repositories/{repo_id}/insights").json()
    assert insights["indexed"] is True and insights["files"] > 0

    assert client.post(f"/api/repositories/{repo_id}/reindex").json()["status"] == "indexing"
    assert client.get(f"/api/repositories/{repo_id}/details").json()["status"] == "ready"

    assert client.delete(f"/api/repositories/{repo_id}").status_code == 200
    assert repo_dir.exists()  # never deletes user files
    assert client.get(f"/api/repositories/{repo_id}/details").status_code == 404


def test_connect_local_rejects_missing_and_outside(env, tmp_path):
    client, root, _ = env
    assert client.post("/api/repositories/connect-local", json={"path": str(root / "nope")}).status_code == 400
    outside = tmp_path / "outside"
    outside.mkdir()
    resp = client.post("/api/repositories/connect-local", json={"path": str(outside)})
    assert resp.status_code == 400 and "outside the allowed roots" in resp.json()["detail"]


# --- GitHub -----------------------------------------------------------------
def test_connect_github_validates_input(env):
    client, _, _ = env
    assert client.post("/api/repositories/connect-github", json={"url": "https://gitlab.com/a/b"}).status_code == 400
    assert client.post("/api/repositories/connect-github", json={"url": "https://github.com/a/b; rm -rf /"}).status_code == 400
    r = client.post("/api/repositories/connect-github", json={"url": "https://github.com/a/b", "private": True})
    assert r.status_code == 400 and "token" in r.json()["detail"].lower()
    r = client.post(
        "/api/repositories/connect-github",
        json={"url": "https://github.com/a/b", "private": True, "use_server_token": True},
    )
    assert r.status_code == 400 and "GITHUB_TOKEN" in r.json()["detail"]
    r = client.post("/api/repositories/connect-github", json={"url": "https://github.com/a/b", "branch": "--upload-pack=x"})
    assert r.status_code == 400


def test_clone_failure_is_reported_and_token_never_persisted(env, monkeypatch):
    client, root, engine = env
    from app.services.repos import manager as rm

    secret = "ghp_" + "A" * 36
    seen: dict = {}

    def fake_clone_from(url, dest, **kwargs):
        seen["url"] = url
        seen["env"] = kwargs.get("env", {})
        raise GitCommandError(
            ["git", "clone", url], 128, stderr=f"remote: Repository not found.\nfatal: Authentication failed {secret}"
        )

    monkeypatch.setattr(rm.Repo, "clone_from", staticmethod(fake_clone_from))
    resp = client.post(
        "/api/repositories/connect-github",
        json={"url": "https://github.com/acme/private-thing", "private": True, "token": secret},
    )
    assert resp.status_code == 200, resp.text
    assert secret not in resp.text
    repo_id = resp.json()["id"]

    # Token went only into the subprocess environment, base64-encoded in a header.
    assert seen["url"] == "https://github.com/acme/private-thing.git"
    assert secret not in seen["url"]
    assert "extraheader" in seen["env"]["GIT_CONFIG_KEY_1"]
    assert secret not in seen["env"]["GIT_CONFIG_VALUE_1"]

    detail = client.get(f"/api/repositories/{repo_id}/details").json()
    assert detail["status"] == "error"
    assert "token" in detail["status_detail"].lower()
    assert secret not in str(detail)

    from app.models.models import Repository

    with Session(engine) as session:
        for row in session.exec(select(Repository)).all():
            assert secret not in row.model_dump_json()

    assert client.post(
        "/api/repositories/connect-github", json={"url": "https://github.com/acme/private-thing", "private": True, "token": "x"}
    ).status_code == 409


def test_git_error_messages_are_specific():
    from app.services.repos.manager import _git_error_message

    def err(text):
        return GitCommandError(["git"], 128, stderr=text)

    assert "reach github" in _git_error_message(err("fatal: unable to access: Could not resolve host: github.com"), None)
    assert "private" in _git_error_message(err("remote: Repository not found."), None)
    assert "Branch 'dev'" in _git_error_message(err("fatal: Remote branch dev not found in upstream origin"), None, "dev")
    assert "tok123" not in _git_error_message(err("fatal: bad tok123"), "tok123")
