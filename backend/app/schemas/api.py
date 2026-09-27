"""Request/response schemas for the REST API (master spec §29)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: datetime


class IndexRepositoryRequest(BaseModel):
    project_id: str
    path: str


class CloneRepositoryRequest(BaseModel):
    project_id: str
    url: str


class RepositoryResponse(BaseModel):
    id: str
    project_id: str
    source: str
    local_path: str
    indexed_at: datetime | None
    file_count: int
    chunk_count: int


class CreateWorkflowRequest(BaseModel):
    project_id: str
    repository_id: str
    intent: str
    base_branch: str = "main"
    test_command: str = ""
    build_command: str = ""
    environment: str = "sandbox"


class WorkflowResponse(BaseModel):
    id: str
    project_id: str
    repository_id: str
    intent: str
    base_branch: str
    branch_name: str
    state: str
    environment: str
    created_at: datetime
    updated_at: datetime
    repair_attempts: int
    human_intervention_count: int
    baseline_tests_passed: bool | None = None
    indexing_ms: int | None
    retrieval_ms: int | None
    planning_ms: int | None
    codegen_ms: int | None
    testgen_ms: int | None
    validation_ms: int | None
    total_ms: int | None


class ApprovalRequest(BaseModel):
    approved: bool
    comment: str = ""


class RepairApprovalRequest(BaseModel):
    repair_id: str
    approved: bool


class SearchRequest(BaseModel):
    repository_id: str
    query: str
    top_k: int = 8


class AskRequest(BaseModel):
    repository_id: str
    question: str


class PushApprovalRequest(BaseModel):
    approved: bool


class PRApprovalRequest(BaseModel):
    approved: bool
    title: str = ""
    body: str = ""
