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
    project_mode: str = "existing"
    greenfield_design_json: str = ""
    revision_of: str | None = None
    revision_note: str = ""
    revision_attachments: str = "[]"
    revision_addons: str = "[]"
    failed_from: str = ""
    indexing_ms: int | None
    retrieval_ms: int | None
    planning_ms: int | None
    codegen_ms: int | None
    testgen_ms: int | None
    validation_ms: int | None
    total_ms: int | None


class RevisionRequest(BaseModel):
    problem: str
    screenshots: list[str] = []  # data URLs (PNG/JPEG/GIF/WebP), validated by their bytes
    force: bool = False  # plan a fix even if the code on staging already seems to do this
    addons: list[str] = []  # built-in add-on ids to apply (see GET /api/workflows/{id}/addons)


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
    # Used only for this push (never stored); GITHUB_TOKEN is used when empty.
    token: str = ""


class GitHubTokenRequest(BaseModel):
    token: str = ""  # used only for this call; GITHUB_TOKEN is used when empty


class ReleaseMergeRequest(BaseModel):
    approved: bool
    verified_on_staging: bool  # the person ran and checked the staging build
    comment: str = ""
    token: str = ""


class MergeRequest(BaseModel):
    approved: bool
    comment: str = ""
    token: str = ""


class CIStatusRequest(BaseModel):
    token: str = ""  # used only for this check; GITHUB_TOKEN is used when empty


class PRApprovalRequest(BaseModel):
    approved: bool
    title: str = ""
    body: str = ""
    token: str = ""


class PlanStepUpdate(BaseModel):
    id: str
    description: str
    files: list[str] = []


class UpdatePlanRequest(BaseModel):
    """Allows the user to edit plan fields before approving.
    Only fields that are explicitly provided are updated.
    """
    summary: str | None = None
    assumptions: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    steps: list[PlanStepUpdate] | None = None
    files_likely_to_change: list[str] | None = None
    test_strategy: list[str] | None = None


class WorkflowSummaryResponse(BaseModel):
    """Concise per-workflow summary for attentional dashboard use-cases."""
    id: str
    intent: str
    state: str
    project_name: str
    repository_name: str
    updated_at: datetime
    repair_attempts: int
    human_intervention_count: int
    awaiting_action: str | None  # human-readable next action label or None


# ---------------------------------------------------------------------------
# Repository Manager
# ---------------------------------------------------------------------------
class CreateLocalRepositoryRequest(BaseModel):
    path: str
    name: str = ""
    git_init: bool = True
    readme: bool = True
    index: bool = True


class ConnectLocalRepositoryRequest(BaseModel):
    path: str
    name: str = ""
    index: bool = True


class ConnectGitHubRepositoryRequest(BaseModel):
    url: str
    branch: str = ""
    private: bool = False
    # Used only for this clone; never stored or returned. If empty and
    # `use_server_token` is set, the backend's GITHUB_TOKEN is used.
    token: str = ""
    use_server_token: bool = False
    index: bool = True


class SyncRepositoryRequest(BaseModel):
    token: str = ""
    use_server_token: bool = False
    reindex: bool = True


class ManagedRepositoryResponse(BaseModel):
    id: str
    project_id: str
    name: str
    kind: str
    source: str
    local_path: str
    remote_url: str
    is_private: bool
    status: str
    status_detail: str
    connected_at: datetime | None
    indexed_at: datetime | None
    file_count: int
    chunk_count: int
    source_file_count: int = 0
    accessible: bool
    is_git: bool
    branch: str | None = None
    head: str | None = None
    dirty: bool | None = None
    workflow_count: int = 0
    last_workflow_at: datetime | None = None
