from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_session
from app.models.models import Repository
from app.schemas.api import AskRequest, IndexRepositoryRequest, RepositoryResponse, SearchRequest
from app.services import orchestrator as orch
from app.services.orchestrator import OrchestratorError
from app.services.rag.retriever import retrieve

router = APIRouter(prefix="/api/repositories", tags=["repositories"])
search_router = APIRouter(prefix="/api/repository", tags=["repository-intelligence"])


@router.post("/index", response_model=RepositoryResponse)
def index_repository_endpoint(payload: IndexRepositoryRequest, session: Session = Depends(get_session)) -> Repository:
    try:
        repo = orch.register_repository(session, payload.project_id, payload.path)
        repo = orch.run_indexing_for_repository(session, repo)
    except OrchestratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return repo


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: str, session: Session = Depends(get_session)) -> Repository:
    repo = session.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(project_id: str | None = None, session: Session = Depends(get_session)) -> list[Repository]:
    stmt = select(Repository)
    if project_id:
        stmt = stmt.where(Repository.project_id == project_id)
    return list(session.exec(stmt).all())


@search_router.post("/search")
def search_repository(payload: SearchRequest, session: Session = Depends(get_session)) -> dict:
    repo = session.get(Repository, payload.repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    results = retrieve(repo.collection_name, payload.query, top_k=payload.top_k)
    return {
        "results": [
            {
                "file": r.file,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "score": r.score,
                "reason": r.reason,
                "chunk_type": r.chunk_type,
                "symbol": r.symbol,
                "retrieval_method": r.retrieval_method,
                "content_preview": r.content_preview,
            }
            for r in results
        ]
    }


@search_router.post("/ask")
def ask_repository(payload: AskRequest, session: Session = Depends(get_session)) -> dict:
    from app.core.llm_reliability import structured_call
    from app.core.prompts import load_prompt
    from app.services.providers.factory import get_provider
    from app.services.rag.formatting import format_retrieved_context, to_context_dicts
    from pydantic import BaseModel, Field

    class _Answer(BaseModel):
        answer: str
        cited_files: list[str] = Field(default_factory=list)

    repo = session.get(Repository, payload.repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    retrieved = retrieve(repo.collection_name, payload.question, top_k=6)
    prompt = load_prompt("code_explanation")
    rendered = prompt.render(question=payload.question, retrieved_context=format_retrieved_context(retrieved))
    provider = get_provider()
    result = structured_call(
        provider,
        "code_explanation",
        rendered,
        {"question": payload.question, "retrieved": to_context_dicts(retrieved)},
        schema=_Answer,
    )
    return {"answer": result.parsed.answer, "cited_files": result.parsed.cited_files, "evidence": to_context_dicts(retrieved)}
