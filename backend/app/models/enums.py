from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    CREATED = "CREATED"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    PLAN_REJECTED = "PLAN_REJECTED"
    CHANGES_GENERATING = "CHANGES_GENERATING"
    CHANGES_READY = "CHANGES_READY"
    AWAITING_CHANGE_APPROVAL = "AWAITING_CHANGE_APPROVAL"
    CHANGES_REJECTED = "CHANGES_REJECTED"
    TESTS_GENERATING = "TESTS_GENERATING"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REPAIRING = "REPAIRING"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    AWAITING_COMMIT_APPROVAL = "AWAITING_COMMIT_APPROVAL"
    COMMITTED = "COMMITTED"
    CI_RUNNING = "CI_RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Explicit allowed transitions. Any transition not listed here is rejected.
ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.CREATED: {WorkflowState.INDEXING, WorkflowState.FAILED},
    WorkflowState.INDEXING: {WorkflowState.INDEXED, WorkflowState.FAILED},
    WorkflowState.INDEXED: {WorkflowState.PLANNING, WorkflowState.FAILED},
    WorkflowState.PLANNING: {WorkflowState.PLAN_READY, WorkflowState.FAILED},
    WorkflowState.PLAN_READY: {WorkflowState.AWAITING_PLAN_APPROVAL, WorkflowState.FAILED},
    WorkflowState.AWAITING_PLAN_APPROVAL: {
        WorkflowState.CHANGES_GENERATING,
        WorkflowState.PLAN_REJECTED,
        WorkflowState.FAILED,
    },
    WorkflowState.PLAN_REJECTED: {WorkflowState.PLANNING, WorkflowState.FAILED},
    WorkflowState.CHANGES_GENERATING: {WorkflowState.CHANGES_READY, WorkflowState.FAILED},
    WorkflowState.CHANGES_READY: {WorkflowState.AWAITING_CHANGE_APPROVAL, WorkflowState.FAILED},
    WorkflowState.AWAITING_CHANGE_APPROVAL: {
        WorkflowState.TESTS_GENERATING,
        WorkflowState.CHANGES_REJECTED,
        WorkflowState.FAILED,
    },
    WorkflowState.CHANGES_REJECTED: {WorkflowState.CHANGES_GENERATING, WorkflowState.FAILED},
    WorkflowState.TESTS_GENERATING: {WorkflowState.VALIDATING, WorkflowState.FAILED},
    WorkflowState.VALIDATING: {
        WorkflowState.VALIDATION_PASSED,
        WorkflowState.VALIDATION_FAILED,
        WorkflowState.FAILED,
    },
    WorkflowState.VALIDATION_FAILED: {
        WorkflowState.REPAIRING,
        WorkflowState.AWAITING_COMMIT_APPROVAL,  # user may accept failure and stop, or override
        WorkflowState.FAILED,
    },
    WorkflowState.REPAIRING: {WorkflowState.VALIDATING, WorkflowState.FAILED},
    WorkflowState.VALIDATION_PASSED: {WorkflowState.AWAITING_COMMIT_APPROVAL, WorkflowState.FAILED},
    WorkflowState.AWAITING_COMMIT_APPROVAL: {
        WorkflowState.COMMITTED,
        WorkflowState.FAILED,
    },
    WorkflowState.COMMITTED: {WorkflowState.CI_RUNNING, WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.CI_RUNNING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: set(),
    WorkflowState.FAILED: set(),
}


class AuditEventType(str, Enum):
    WORKFLOW_CREATED = "WORKFLOW_CREATED"
    INDEXING_STARTED = "INDEXING_STARTED"
    INDEXING_COMPLETED = "INDEXING_COMPLETED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    PLAN_GENERATED = "PLAN_GENERATED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_REJECTED = "PLAN_REJECTED"
    PATCH_GENERATED = "PATCH_GENERATED"
    PATCH_APPROVED = "PATCH_APPROVED"
    PATCH_REJECTED = "PATCH_REJECTED"
    TESTS_GENERATED = "TESTS_GENERATED"
    VALIDATION_STARTED = "VALIDATION_STARTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REPAIR_ATTEMPTED = "REPAIR_ATTEMPTED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    COMMIT_APPROVED = "COMMIT_APPROVED"
    COMMIT_CREATED = "COMMIT_CREATED"
    PUSH_APPROVED = "PUSH_APPROVED"
    PUSH_COMPLETED = "PUSH_COMPLETED"
    PR_APPROVED = "PR_APPROVED"
    PR_CREATED = "PR_CREATED"
    CI_STARTED = "CI_STARTED"
    CI_PASSED = "CI_PASSED"
    CI_FAILED = "CI_FAILED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"


class ChunkType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    TEST = "test"
    CONFIG = "config"
    DOC = "doc"
    OTHER = "other"
