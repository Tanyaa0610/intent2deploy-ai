"""SQLModel persistence models.

Every workflow stage, retrieved document, plan, proposed change, test
result, approval decision, metric, and audit event is persisted here so
that refreshing the UI never loses workflow state (master spec §8, §30).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.enums import Environment, WorkflowState


def gen_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.utcnow()


class Project(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow)


class Repository(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    source: str  # local path or git URL as provided by the user
    local_path: str  # resolved absolute local path used for indexing/git ops
    indexed_at: datetime | None = None
    file_count: int = 0
    chunk_count: int = 0
    collection_name: str = ""  # Chroma collection name for this repository


class Workflow(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    repository_id: str = Field(foreign_key="repository.id", index=True)
    intent: str
    base_branch: str = "main"
    branch_name: str = ""
    test_command: str = ""
    build_command: str = ""
    state: WorkflowState = Field(default=WorkflowState.CREATED)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    repair_attempts: int = 0
    human_intervention_count: int = 0
    environment: Environment = Field(default=Environment.SANDBOX)
    baseline_tests_passed: bool | None = None

    # AI/LLM cost tracking (Part 5 — COST guardrails). Token counts are
    # ESTIMATES derived from real prompt/response text length (chars // 4),
    # never invented; LLMUsage.available is False in mock mode because no
    # provider billing API is involved, so these are clearly an estimate,
    # not exact accounting.
    llm_call_count: int = 0
    llm_estimated_tokens: int = 0
    llm_estimated_cost_usd: float = 0.0

    # Timing (ms), populated as stages complete — used for metrics (§24.7)
    indexing_ms: int | None = None
    retrieval_ms: int | None = None
    planning_ms: int | None = None
    codegen_ms: int | None = None
    testgen_ms: int | None = None
    validation_ms: int | None = None
    total_ms: int | None = None


class AuditEvent(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    event_type: str
    stage: str = ""
    message: str = ""
    metadata_json: str = "{}"
    timestamp: datetime = Field(default_factory=utcnow)


class RetrievedDocument(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    file: str
    start_line: int
    end_line: int
    score: float
    reason: str
    chunk_type: str = "other"
    symbol: str = ""
    retrieval_method: str = "semantic"  # semantic | path | symbol | keyword
    content_preview: str = ""


class Plan(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    summary: str
    assumptions_json: str = "[]"
    acceptance_criteria_json: str = "[]"
    steps_json: str = "[]"
    files_json: str = "[]"
    dependencies_json: str = "[]"
    test_strategy_json: str = "[]"
    risks_json: str = "[]"
    prompt_version: str = ""
    raw_llm_output: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    approved: bool | None = None
    approval_comment: str = ""


class ProposedChange(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    file: str
    operation: str  # create | modify | delete
    reason: str
    patch: str
    confidence: float = 0.6
    risks_json: str = "[]"
    acceptance_criterion: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ChangeApprovalRecord(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    approved: bool
    comment: str = ""
    timestamp: datetime = Field(default_factory=utcnow)


class GeneratedTest(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    file: str
    content: str
    rationale: str
    category: str = "happy_path"  # happy_path | edge_case | invalid_input | regression | security
    created_at: datetime = Field(default_factory=utcnow)


class ValidationResult(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    stage: str  # syntax | lint | unit_tests | integration_tests | build | security
    status: str  # passed | failed | skipped | error
    duration_ms: int = 0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    attempt: int = 0  # 0 = initial run, 1..N = repair attempt number
    command: str = ""
    timestamp: datetime = Field(default_factory=utcnow)


class RepairAttempt(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    attempt_number: int
    diagnosis: str
    repair_patch: str
    approved: bool | None = None
    result: str = ""  # passed | failed | pending
    created_at: datetime = Field(default_factory=utcnow)


class GitOperation(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    operation: str  # branch_created | commit | push | pr_created
    detail: str = ""
    ref: str = ""  # commit hash / branch name / PR url
    approved: bool = False
    timestamp: datetime = Field(default_factory=utcnow)


class CIRun(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    provider: str  # local | github_actions
    run_id: str = ""
    status: str = "pending"  # pending | queued | in_progress | success | failure
    url: str = ""
    conclusion: str = ""
    timestamp: datetime = Field(default_factory=utcnow)


class GuardrailCheck(SQLModel, table=True):
    """One evaluation of one guardrail definition against one workflow.

    This is the ONLY guardrail persistence model in the system (it
    replaces the earlier flat `GuardrailEvent`/G01-G18 schema entirely —
    there is no parallel/legacy guardrail table). `guardrail_id` values are
    category-scoped, e.g. "SEC-01", "CICD-07", "AI-05" — see
    `app.services.guardrails.engine.GUARDRAIL_CATALOG` for the full
    definition list.
    """

    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    guardrail_id: str  # e.g. "SEC-01"
    category: str  # one of GuardrailCategory
    name: str
    description: str = ""
    purpose: str = ""
    trigger_condition: str = ""
    enforcement_point: str = ""  # which orchestrator checkpoint triggered this evaluation
    severity: str = "LOW"  # one of Severity
    status: str = "PASSED"  # one of GuardrailStatus
    action: str = "ALLOW"  # one of GuardrailAction
    evidence_json: str = "[]"
    remediation: str = ""
    configurable_threshold: str = ""  # human-readable description of the active threshold, if any
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    evaluated_at: datetime = Field(default_factory=utcnow)


class RiskItem(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    risk_id: str  # e.g. "R1"
    title: str
    component: str = ""
    severity: str = "LOW"  # LOW | MEDIUM | HIGH | CRITICAL
    likelihood: str = "LOW"  # LOW | MEDIUM | HIGH
    blast_radius: str = ""
    detection: str = ""
    mitigation: str = ""
    validation_method: str = ""
    status: str = "OPEN"  # OPEN | MITIGATED | ACCEPTED
    evidence_json: str = "[]"
    source: str = ""  # llm_plan | category_metadata | static_scan
    created_at: datetime = Field(default_factory=utcnow)


class ChaosExperiment(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    experiment_id: str
    target: str
    hypothesis: str
    fault: str
    expected_behavior: str
    observed_behavior: str = ""
    result: str = "NOT_APPLICABLE"  # PASSED | FAILED | NOT_APPLICABLE
    environment: str = "sandbox"
    evidence_json: str = "[]"
    timestamp: datetime = Field(default_factory=utcnow)


class ProductionReadinessAssessment(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", index=True)
    decision: str = "NOT_READY"  # READY | READY_WITH_WARNINGS | NOT_READY
    reasons_json: str = "[]"
    checklist_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)
