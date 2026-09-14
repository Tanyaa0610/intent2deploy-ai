from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import evaluation, projects, repositories, workflows
from app.core.config import settings
from app.core.db import init_db

app = FastAPI(title="Intent2Deploy AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "llm_mode": settings.llm_mode,
        "is_mock": settings.is_mock,
    }


app.include_router(projects.router)
app.include_router(repositories.router)
app.include_router(repositories.search_router)
app.include_router(workflows.router)
app.include_router(evaluation.router)
