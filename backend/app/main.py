from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, dashboard, evaluation, guardrails, projects, repo_manager, repositories, risks, simulation, workflows
from app.core.config import settings
from app.core.db import init_db

app = FastAPI(title="Intent2Deploy AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Any local dev port, so the frontend still works when 5173 is taken.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        repo_manager.recover_interrupted_jobs(session)


@app.on_event("shutdown")
def on_shutdown() -> None:
    # Deployments are tracked in memory; don't leave their apps running orphaned.
    from app.services import preview

    for key in list(preview._DEPLOYMENTS):
        preview.stop(key)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "llm_mode": settings.llm_mode,
        "is_mock": settings.is_mock,
    }


app.include_router(projects.router)
app.include_router(alerts.router)
app.include_router(repo_manager.router)  # before repositories.router: fixed paths win over /{repository_id}
app.include_router(repositories.router)
app.include_router(repositories.search_router)
app.include_router(workflows.router)
app.include_router(evaluation.router)
app.include_router(dashboard.router)
app.include_router(guardrails.router)
app.include_router(risks.router)
app.include_router(simulation.router)
