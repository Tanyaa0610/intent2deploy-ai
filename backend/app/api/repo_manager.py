"""Repository Manager endpoints: create/connect/clone repositories, track
their status, and browse/search them. Registered before `repositories.router`
so its fixed paths (e.g. /managed) win over `/{repository_id}`."""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.deps import get_session
from app.core.config import settings
from app.models.models import Project, Repository, Workflow
from app.schemas.api import (
    ConnectGitHubRepositoryRequest,
    ConnectLocalRepositoryRequest,
    CreateLocalRepositoryRequest,
    ManagedRepositoryResponse,
    SyncRepositoryRequest,
    WorkflowResponse,
)
from app.services.rag.indexer import index_repository
from app.services.repos import manager as rm
from app.services.repos.manager import RepoManagerError

router = APIRouter(prefix="/api/repositories", tags=["repository-manager"])

BUSY_STATES = {"cloning", "indexing", "syncing"}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _get_managed(session: Session, repository_id: str) -> Repository:
    repo = session.get(Repository, repository_id)
    if repo is None or not repo.managed:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _related_repo_ids(session: Session, repo: Repository) -> list[str]:
    """Workflow runs started from the New Workflow page register their own
    Repository row for the same folder; treat those as the same repository."""
    key = _norm(repo.local_path) if repo.local_path else None
    return [r.id for r in session.exec(select(Repository)).all() if r.id == repo.id or (key and _norm(r.local_path) == key)]


def _to_response(session: Session, repo: Repository, detailed: bool = False) -> ManagedRepositoryResponse:
    path = Path(repo.local_path) if repo.local_path else None
    accessible = bool(path) and rm.is_accessible(path)
    info = rm.git_info(path, include_dirty=detailed) if accessible else rm.GitInfo(is_git=False)
    ids = _related_repo_ids(session, repo)
    workflows = list(session.exec(select(Workflow).where(Workflow.repository_id.in_(ids))).all()) if ids else []
    return ManagedRepositoryResponse(
        id=repo.id,
        project_id=repo.project_id,
        name=repo.name,
        kind=repo.kind,
        source=repo.source,
        local_path=repo.local_path,
        remote_url=repo.remote_url,
        is_private=repo.is_private,
        status=repo.status,
        status_detail=repo.status_detail,
        connected_at=repo.connected_at,
        indexed_at=repo.indexed_at,
        file_count=repo.file_count,
        chunk_count=repo.chunk_count,
        source_file_count=repo.source_file_count,
        accessible=accessible,
        is_git=info.is_git,
        branch=info.branch,
        head=info.head,
        dirty=info.dirty,
        workflow_count=len(workflows),
        last_workflow_at=max((w.created_at for w in workflows), default=None),
    )


def _new_managed(session: Session, *, name: str, kind: str, source: str, local_path: str, **extra) -> Repository:
    project = Project(name=name)
    session.add(project)
    session.commit()
    session.refresh(project)
    repo = Repository(
        project_id=project.id,
        name=name,
        kind=kind,
        source=source,
        local_path=local_path,
        managed=True,
        connected_at=datetime.utcnow(),
        **extra,
    )
    repo.collection_name = f"repo_{repo.id}"
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo


def _ensure_not_connected(session: Session, path: Path) -> None:
    key = _norm(str(path))
    for r in session.exec(select(Repository).where(Repository.managed == True)).all():  # noqa: E712
        if r.local_path and _norm(r.local_path) == key:
            raise HTTPException(status_code=409, detail=f"Already connected as '{r.name}'.")


def _resolve_token(token: str, use_server_token: bool) -> str | None:
    if token.strip():
        return token.strip()
    if use_server_token:
        if not settings.github_token:
            raise HTTPException(status_code=400, detail="No GITHUB_TOKEN is configured on the server.")
        return settings.github_token
    return None


# ---------------------------------------------------------------------------
# Background jobs. They open their own session on the request's engine so
# they work with test dependency overrides too.
# ---------------------------------------------------------------------------
def _set_status(session: Session, repo: Repository, status: str, detail: str = "") -> None:
    repo.status = status
    repo.status_detail = detail
    session.add(repo)
    session.commit()


def _index(session: Session, repo: Repository) -> None:
    _set_status(session, repo, "indexing")
    stats = index_repository(Path(repo.local_path), repo.collection_name)
    repo.indexed_at = datetime.utcnow()
    repo.file_count = stats.file_count
    repo.chunk_count = stats.chunk_count
    repo.source_file_count = stats.source_file_count
    _set_status(session, repo, "ready")


def run_repository_job(
    engine: Engine,
    repository_id: str,
    *,
    clone_url: str | None = None,
    branch: str | None = None,
    pull: bool = False,
    token: str | None = None,
    index: bool = True,
) -> None:
    with Session(engine) as session:
        repo = session.get(Repository, repository_id)
        if repo is None:
            return
        try:
            if clone_url:
                _set_status(session, repo, "cloning")
                rm.clone_github(clone_url, Path(repo.local_path), branch, token)
            elif pull:
                _set_status(session, repo, "syncing")
                rm.pull_github(Path(repo.local_path), token)
            if index:
                _index(session, repo)
            else:
                _set_status(session, repo, "ready")
        except RepoManagerError as exc:
            _set_status(session, repo, "error", str(exc))
        except Exception as exc:  # surface unexpected failures instead of leaving a stuck status
            msg = str(exc)
            if token:
                msg = msg.replace(token, "***")
            _set_status(session, repo, "error", f"{type(exc).__name__}: {msg[:300]}")


def recover_interrupted_jobs(session: Session) -> None:
    """Called at startup: a job running when the server stopped will never
    finish, so mark it failed instead of showing it as in progress forever."""
    for repo in session.exec(select(Repository).where(Repository.status.in_(BUSY_STATES))).all():
        repo.status = "error"
        repo.status_detail = "Interrupted by a server restart. Retry the operation."
        session.add(repo)
    session.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/roots")
def get_allowed_roots() -> dict:
    return {"roots": [str(r) for r in rm.allowed_roots()], "server_token_configured": bool(settings.github_token)}


@router.get("/managed", response_model=list[ManagedRepositoryResponse])
def list_managed(session: Session = Depends(get_session)) -> list[ManagedRepositoryResponse]:
    repos = session.exec(select(Repository).where(Repository.managed == True)).all()  # noqa: E712
    repos = sorted(repos, key=lambda r: r.connected_at or datetime.min, reverse=True)
    return [_to_response(session, r) for r in repos]


@router.post("/create", response_model=ManagedRepositoryResponse)
def create_repository(
    payload: CreateLocalRepositoryRequest, background: BackgroundTasks, session: Session = Depends(get_session)
) -> ManagedRepositoryResponse:
    try:
        target = rm.resolve_allowed_path(payload.path)
    except RepoManagerError as exc:
        raise _bad(exc) from exc
    _ensure_not_connected(session, target)
    name = payload.name.strip()[:100] or target.name
    try:
        path = rm.create_local_repository(payload.path, payload.git_init, payload.readme, name)
    except RepoManagerError as exc:
        raise _bad(exc) from exc
    repo = _new_managed(session, name=name, kind="created", source=str(path), local_path=str(path))
    if payload.index:
        _set_status(session, repo, "indexing")
        background.add_task(run_repository_job, session.get_bind(), repo.id)
    return _to_response(session, repo)


@router.post("/connect-local", response_model=ManagedRepositoryResponse)
def connect_local(
    payload: ConnectLocalRepositoryRequest, background: BackgroundTasks, session: Session = Depends(get_session)
) -> ManagedRepositoryResponse:
    try:
        path = rm.validate_existing_directory(payload.path)
    except RepoManagerError as exc:
        raise _bad(exc) from exc
    _ensure_not_connected(session, path)
    name = payload.name.strip()[:100] or path.name
    repo = _new_managed(session, name=name, kind="local", source=str(path), local_path=str(path))
    if payload.index:
        _set_status(session, repo, "indexing")
        background.add_task(run_repository_job, session.get_bind(), repo.id)
    return _to_response(session, repo)


@router.post("/connect-github", response_model=ManagedRepositoryResponse)
def connect_github(
    payload: ConnectGitHubRepositoryRequest, background: BackgroundTasks, session: Session = Depends(get_session)
) -> ManagedRepositoryResponse:
    try:
        owner, name, clean_url = rm.clean_github_url(payload.url)
    except RepoManagerError as exc:
        raise _bad(exc) from exc
    branch = payload.branch.strip() or None
    if branch and (branch.startswith("-") or any(c in branch for c in " ~^:?*[\\")):
        raise HTTPException(status_code=400, detail="Invalid branch name.")
    token = _resolve_token(payload.token, payload.use_server_token) if payload.private else None
    if payload.private and not token:
        raise HTTPException(status_code=400, detail="Private repositories need a token.")

    existing = session.exec(
        select(Repository).where(Repository.managed == True, Repository.remote_url == clean_url)  # noqa: E712
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Already connected as '{existing.name}'.")

    repo = _new_managed(
        session,
        name=f"{owner}/{name}",
        kind="github",
        source=f"https://github.com/{owner}/{name}",
        local_path="",
        remote_url=clean_url,
        is_private=payload.private,
        status="cloning",
    )
    repo.local_path = str((Path(settings.cloned_repos_dir) / f"{owner}__{name}-{repo.id}").resolve())
    session.add(repo)
    session.commit()
    session.refresh(repo)
    background.add_task(
        run_repository_job, session.get_bind(), repo.id, clone_url=clean_url, branch=branch, token=token, index=payload.index
    )
    return _to_response(session, repo)


@router.get("/{repository_id}/details", response_model=ManagedRepositoryResponse)
def repository_details(repository_id: str, session: Session = Depends(get_session)) -> ManagedRepositoryResponse:
    return _to_response(session, _get_managed(session, repository_id), detailed=True)


@router.post("/{repository_id}/reindex", response_model=ManagedRepositoryResponse)
def reindex(repository_id: str, background: BackgroundTasks, session: Session = Depends(get_session)) -> ManagedRepositoryResponse:
    repo = _get_managed(session, repository_id)
    if repo.status in BUSY_STATES:
        raise HTTPException(status_code=409, detail=f"Repository is busy ({repo.status}).")
    if not rm.is_accessible(Path(repo.local_path)):
        raise HTTPException(status_code=400, detail=f"Path is not accessible: {repo.local_path}")
    _set_status(session, repo, "indexing")
    background.add_task(run_repository_job, session.get_bind(), repo.id)
    return _to_response(session, repo)


@router.post("/{repository_id}/sync", response_model=ManagedRepositoryResponse)
def sync(
    repository_id: str, payload: SyncRepositoryRequest, background: BackgroundTasks, session: Session = Depends(get_session)
) -> ManagedRepositoryResponse:
    repo = _get_managed(session, repository_id)
    if repo.kind != "github":
        raise HTTPException(status_code=400, detail="Only GitHub repositories can be synced.")
    if repo.status in BUSY_STATES:
        raise HTTPException(status_code=409, detail=f"Repository is busy ({repo.status}).")
    token = _resolve_token(payload.token, payload.use_server_token) if repo.is_private else None
    if repo.is_private and not token:
        raise HTTPException(status_code=400, detail="Private repositories need a token to sync.")
    if not (Path(repo.local_path) / ".git").is_dir() or rm.git_info(Path(repo.local_path)).head is None:
        # Clone never completed, or it was cloned while the remote was empty
        # (nothing to fast-forward from): clone it again.
        from app.services.validation.sandbox import _force_rmtree

        if Path(repo.local_path).exists():
            _force_rmtree(Path(repo.local_path))
        _set_status(session, repo, "cloning")
        background.add_task(
            run_repository_job, session.get_bind(), repo.id, clone_url=repo.remote_url, token=token, index=payload.reindex
        )
    else:
        _set_status(session, repo, "syncing")
        background.add_task(run_repository_job, session.get_bind(), repo.id, pull=True, token=token, index=payload.reindex)
    return _to_response(session, repo)


@router.delete("/{repository_id}")
def disconnect(repository_id: str, session: Session = Depends(get_session)) -> dict:
    """Removes the repository from the manager. Never deletes user files; an
    app-owned GitHub clone is deleted only if no workflow run references it."""
    repo = _get_managed(session, repository_id)
    if repo.status in BUSY_STATES:
        raise HTTPException(status_code=409, detail=f"Repository is busy ({repo.status}).")
    removed_clone = False
    has_workflows = session.exec(select(Workflow).where(Workflow.repository_id == repo.id)).first() is not None
    if repo.kind == "github" and repo.local_path and not has_workflows:
        clone_root = Path(settings.cloned_repos_dir).resolve()
        path = Path(repo.local_path).resolve()
        if path != clone_root and clone_root in path.parents and path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed_clone = True
    try:
        from app.services.rag.vectorstore import reset_collection

        if not has_workflows and repo.collection_name:
            reset_collection(repo.collection_name)
    except Exception:
        pass
    repo.managed = False
    repo.status = "disconnected"
    session.add(repo)
    session.commit()
    return {"status": "disconnected", "removed_clone": removed_clone}


@router.get("/{repository_id}/tree")
def tree(repository_id: str, path: str = "", session: Session = Depends(get_session)) -> dict:
    repo = _get_managed(session, repository_id)
    try:
        return {"path": path.strip("/"), "entries": rm.list_directory(Path(repo.local_path), path)}
    except RepoManagerError as exc:
        raise _bad(exc) from exc


@router.get("/{repository_id}/file")
def file(repository_id: str, path: str, session: Session = Depends(get_session)) -> dict:
    repo = _get_managed(session, repository_id)
    try:
        return rm.read_file(Path(repo.local_path), path)
    except RepoManagerError as exc:
        raise _bad(exc) from exc


@router.get("/{repository_id}/grep")
def grep(
    repository_id: str,
    q: str = Query(..., max_length=200),
    case_sensitive: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    repo = _get_managed(session, repository_id)
    if not rm.is_accessible(Path(repo.local_path)):
        raise HTTPException(status_code=400, detail="Repository path is not accessible.")
    try:
        return rm.search_text(Path(repo.local_path), q, case_sensitive)
    except RepoManagerError as exc:
        raise _bad(exc) from exc


@router.get("/{repository_id}/insights")
def insights(repository_id: str, session: Session = Depends(get_session)) -> dict:
    repo = _get_managed(session, repository_id)
    if not repo.indexed_at:
        return {"indexed": False}
    return {"indexed": True, "indexed_at": repo.indexed_at, **rm.index_insights(repo.collection_name)}


@router.get("/{repository_id}/workflows", response_model=list[WorkflowResponse])
def repository_workflows(repository_id: str, session: Session = Depends(get_session)) -> list[Workflow]:
    repo = _get_managed(session, repository_id)
    ids = _related_repo_ids(session, repo)
    stmt = select(Workflow).where(Workflow.repository_id.in_(ids)).order_by(Workflow.created_at.desc())
    return list(session.exec(stmt).all())
