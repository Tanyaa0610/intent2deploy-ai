"""Workflow orchestrator: ties the state machine, persistence, and every
subsystem (RAG, planning, codegen, testing, validation, repair, git,
GitHub) together. Every externally-visible or workspace-mutating action
is behind an explicit approval call (master spec §13).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.models.enums import AuditEventType, WorkflowState
from app.models.models import (
    ChangeApprovalRecord,
    GeneratedTest,
    GitOperation,
    Plan,
    Project,
    ProposedChange,
    RepairAttempt,
    Repository,
    RetrievedDocument,
    ValidationResult,
    Workflow,
)
from app.services.audit import log_event
from app.services.codegen.codegen import ChangeGenerationLimitError, generate_changes
from app.services.codegen.diffing import apply_patch
from app.services.git import git_ops
from app.services.planner.intent_classifier import classify_intent
from app.services.planner.planner import generate_plan
from app.services.providers.base import LLMProvider
from app.services.rag.indexer import index_repository
from app.services.rag.retriever import retrieve_multi
from app.services.state_machine import InvalidTransitionError, transition
from app.services.testing.mock_test_strategies import STRATEGIES as MOCK_TEST_STRATEGIES
from app.services.validation.pipeline import run_pipeline, overall_status
from app.services.validation.repair import diagnose_failure, propose_repair
from app.services.validation.sandbox import create_workspace, workspace_path

REPOS_ROOT = Path(settings.workspaces_dir).parent  # projects may reference local paths anywhere; validated separately


class OrchestratorError(Exception):
    pass


def _set_state(session: Session, workflow: Workflow, target: WorkflowState) -> None:
    try:
        transition(workflow.state, target)
    except InvalidTransitionError as exc:
        raise OrchestratorError(str(exc)) from exc
    workflow.state = target
    from datetime import datetime

    workflow.updated_at = datetime.utcnow()
    session.add(workflow)
    session.commit()


# ---------------------------------------------------------------------------
# Project / Repository
# ---------------------------------------------------------------------------
def create_project(session: Session, name: str) -> Project:
    project = Project(name=name)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def register_repository(session: Session, project_id: str, source_path: str) -> Repository:
    resolved = Path(source_path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise OrchestratorError(f"Repository path does not exist or is not a directory: {resolved}")
    repo = Repository(
        project_id=project_id,
        source=source_path,
        local_path=str(resolved),
        collection_name=f"repo_{resolved.name}_{project_id}",
    )
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return repo


def run_indexing_for_repository(session: Session, repository: Repository) -> Repository:
    stats = index_repository(Path(repository.local_path), repository.collection_name)
    from datetime import datetime

    repository.indexed_at = datetime.utcnow()
    repository.file_count = stats.file_count
    repository.chunk_count = stats.chunk_count
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return repository


# ---------------------------------------------------------------------------
# Workflow lifecycle
# ---------------------------------------------------------------------------
def create_workflow(
    session: Session,
    project_id: str,
    repository_id: str,
    intent: str,
    base_branch: str = "main",
    test_command: str = "",
    build_command: str = "",
) -> Workflow:
    workflow = Workflow(
        project_id=project_id,
        repository_id=repository_id,
        intent=intent,
        base_branch=base_branch,
        test_command=test_command,
        build_command=build_command,
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    log_event(session, workflow.id, AuditEventType.WORKFLOW_CREATED, message=f"intent={intent!r}")
    return workflow


def get_workflow(session: Session, workflow_id: str) -> Workflow:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise OrchestratorError(f"Workflow '{workflow_id}' not found.")
    return workflow


def run_indexing(session: Session, workflow_id: str) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    _set_state(session, workflow, WorkflowState.INDEXING)
    log_event(session, workflow_id, AuditEventType.INDEXING_STARTED, stage="indexing")
    start = time.monotonic()
    run_indexing_for_repository(session, repository)
    workflow.indexing_ms = int((time.monotonic() - start) * 1000)
    session.add(workflow)
    session.commit()
    log_event(
        session,
        workflow_id,
        AuditEventType.INDEXING_COMPLETED,
        stage="indexing",
        metadata={"file_count": repository.file_count, "chunk_count": repository.chunk_count},
    )
    _set_state(session, workflow, WorkflowState.INDEXED)
    return workflow


def run_planning(session: Session, workflow_id: str, provider: LLMProvider) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    _set_state(session, workflow, WorkflowState.PLANNING)
    start = time.monotonic()
    result = generate_plan(provider, repository.collection_name, workflow.intent)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    workflow.planning_ms = elapsed_ms
    workflow.retrieval_ms = elapsed_ms  # retrieval happens inside planning in this pipeline

    # Persist retrieved evidence
    for r in result.retrieved:
        session.add(
            RetrievedDocument(
                workflow_id=workflow_id,
                file=r.file,
                start_line=r.start_line,
                end_line=r.end_line,
                score=r.score,
                reason=r.reason,
                chunk_type=r.chunk_type,
                symbol=r.symbol,
                retrieval_method=r.retrieval_method,
                content_preview=r.content_preview,
            )
        )

    plan = result.plan
    plan_row = Plan(
        workflow_id=workflow_id,
        summary=plan.summary,
        assumptions_json=json.dumps(plan.assumptions),
        acceptance_criteria_json=json.dumps(plan.acceptance_criteria),
        steps_json=json.dumps([s.model_dump() for s in plan.steps]),
        files_json=json.dumps(plan.files_likely_to_change),
        dependencies_json=json.dumps(plan.dependencies),
        test_strategy_json=json.dumps(plan.test_strategy),
        risks_json=json.dumps(plan.risks),
        prompt_version=result.prompt_versions.get("implementation_planning", ""),
        raw_llm_output=result.raw_llm_output,
    )
    session.add(plan_row)
    session.add(workflow)
    session.commit()
    session.refresh(plan_row)

    log_event(
        session,
        workflow_id,
        AuditEventType.RETRIEVAL_COMPLETED,
        stage="retrieval",
        metadata={"documents_retrieved": len(result.retrieved)},
    )
    log_event(
        session,
        workflow_id,
        AuditEventType.PLAN_GENERATED,
        stage="planning",
        metadata={"plan_id": plan_row.id, "prompt_versions": result.prompt_versions, "invented_files_removed": result.invented_files_removed},
    )
    _set_state(session, workflow, WorkflowState.PLAN_READY)
    _set_state(session, workflow, WorkflowState.AWAITING_PLAN_APPROVAL)
    return workflow


def approve_plan(session: Session, workflow_id: str, approved: bool, comment: str = "") -> Workflow:
    workflow = get_workflow(session, workflow_id)
    plan_row = session.exec(
        select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())
    ).first()
    if plan_row is None:
        raise OrchestratorError("No plan found for this workflow.")

    plan_row.approved = approved
    plan_row.approval_comment = comment
    session.add(plan_row)
    workflow.human_intervention_count += 1
    session.add(workflow)
    session.commit()

    if approved:
        log_event(session, workflow_id, AuditEventType.PLAN_APPROVED, stage="planning", message=comment)
        _set_state(session, workflow, WorkflowState.CHANGES_GENERATING)
    else:
        log_event(session, workflow_id, AuditEventType.PLAN_REJECTED, stage="planning", message=comment)
        _set_state(session, workflow, WorkflowState.PLAN_REJECTED)
    return workflow


def run_codegen(session: Session, workflow_id: str, provider: LLMProvider) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    plan_row = session.exec(
        select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())
    ).first()
    if repository is None or plan_row is None:
        raise OrchestratorError("Repository or plan not found.")

    target_files: list[str] = json.loads(plan_row.files_json)
    step_descriptions = [s.get("description", "") for s in json.loads(plan_row.steps_json)]

    start = time.monotonic()
    try:
        result = generate_changes(
            provider,
            Path(repository.local_path),
            target_files,
            workflow.intent,
            plan_row.summary,
            step_descriptions,
        )
    except ChangeGenerationLimitError as exc:
        log_event(session, workflow_id, AuditEventType.PATCH_GENERATED, stage="codegen", message=f"REJECTED: {exc}")
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(str(exc)) from exc

    workflow.codegen_ms = int((time.monotonic() - start) * 1000)
    session.add(workflow)

    for c in result.changeset.changes:
        session.add(
            ProposedChange(
                workflow_id=workflow_id,
                file=c.file,
                operation=c.operation,
                reason=c.reason,
                patch=c.patch,
                confidence=c.confidence,
                risks_json=json.dumps(c.risks),
                acceptance_criterion=c.acceptance_criterion,
            )
        )
    session.commit()

    log_event(
        session,
        workflow_id,
        AuditEventType.PATCH_GENERATED,
        stage="codegen",
        metadata={"files_changed": [c.file for c in result.changeset.changes], "prompt_version": result.prompt_version},
    )
    _set_state(session, workflow, WorkflowState.CHANGES_READY)
    _set_state(session, workflow, WorkflowState.AWAITING_CHANGE_APPROVAL)
    return workflow


def approve_changes(session: Session, workflow_id: str, approved: bool, comment: str = "") -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    session.add(ChangeApprovalRecord(workflow_id=workflow_id, approved=approved, comment=comment))
    workflow.human_intervention_count += 1
    session.add(workflow)
    session.commit()

    if not approved:
        log_event(session, workflow_id, AuditEventType.PATCH_REJECTED, stage="codegen", message=comment)
        _set_state(session, workflow, WorkflowState.CHANGES_REJECTED)
        return workflow

    log_event(session, workflow_id, AuditEventType.PATCH_APPROVED, stage="codegen", message=comment)

    # Workspace mutation happens ONLY after this approval (Checkpoint 2).
    workspace = create_workspace(workflow_id, Path(repository.local_path))
    workflow.branch_name = git_ops.branch_name_for_workflow(workflow_id)
    try:
        git_ops.create_branch(workspace, workflow_id, workflow.base_branch)
        # Baseline commit of the pristine snapshot so the eventual commit
        # (after tests are generated and validation passes) captures a
        # clean, reviewable diff of only what Intent2Deploy AI changed.
        git_ops.commit(workspace, "Baseline snapshot (pre-Intent2Deploy AI changes)")
    except Exception:
        pass  # best-effort; absence of a baseline commit does not block the workflow

    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    for change in changes:
        if not change.patch:
            continue
        target = workspace / change.file
        old_content = target.read_text(encoding="utf-8") if target.exists() else ""
        new_content = apply_patch(old_content, change.patch)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")

    session.add(workflow)
    session.commit()
    _set_state(session, workflow, WorkflowState.TESTS_GENERATING)
    return workflow


def run_test_generation(session: Session, workflow_id: str, provider: LLMProvider) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    start = time.monotonic()
    category = classify_intent(workflow.intent)
    strategy = MOCK_TEST_STRATEGIES.get(category)
    mock_tests = strategy() if strategy and provider.is_mock else []

    workspace = workspace_path(workflow_id)
    existing_tests = list((Path(repository.local_path)).rglob("test_*.py"))

    tests_persisted = []
    for t in mock_tests:
        target = workspace / t.file
        if target.exists():
            existing_content = target.read_text(encoding="utf-8")
            addition = t.content
            if "pytest." in addition and "import pytest" not in existing_content:
                addition = "import pytest\n" + addition
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(addition)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = t.content
            if "pytest." in content and "import pytest" not in content:
                content = "import pytest\n" + content
            target.write_text(content, encoding="utf-8")
        row = GeneratedTest(workflow_id=workflow_id, file=t.file, content=t.content, rationale=t.rationale, category=t.category)
        session.add(row)
        tests_persisted.append(row)

    workflow.testgen_ms = int((time.monotonic() - start) * 1000)
    session.add(workflow)
    session.commit()

    log_event(
        session,
        workflow_id,
        AuditEventType.TESTS_GENERATED,
        stage="testing",
        metadata={
            "existing_tests_found": len(existing_tests),
            "generated_tests": len(tests_persisted),
        },
    )
    return workflow


def run_validation(session: Session, workflow_id: str) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    current_attempt = workflow.repair_attempts

    if workflow.state in (WorkflowState.TESTS_GENERATING,):
        _set_state(session, workflow, WorkflowState.VALIDATING)
    elif workflow.state == WorkflowState.REPAIRING:
        _set_state(session, workflow, WorkflowState.VALIDATING)
    else:
        raise OrchestratorError(f"Cannot validate from state {workflow.state.value}")

    log_event(session, workflow_id, AuditEventType.VALIDATION_STARTED, stage="validation", metadata={"attempt": current_attempt})
    start = time.monotonic()
    changed_files = [c.file for c in session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()]
    stages = run_pipeline(workflow_id, changed_files, test_command=workflow.test_command, build_command=workflow.build_command)
    workflow.validation_ms = int((time.monotonic() - start) * 1000)

    for s in stages:
        session.add(
            ValidationResult(
                workflow_id=workflow_id,
                stage=s.stage,
                status=s.result.status,
                duration_ms=s.result.duration_ms,
                exit_code=s.result.exit_code,
                stdout=s.result.stdout,
                stderr=s.result.stderr,
                attempt=current_attempt,
                command=s.result.command,
            )
        )
    session.add(workflow)
    session.commit()

    status = overall_status(stages)
    if status == "passed":
        log_event(session, workflow_id, AuditEventType.VALIDATION_PASSED, stage="validation", metadata={"attempt": current_attempt})
        _set_state(session, workflow, WorkflowState.VALIDATION_PASSED)
        _set_state(session, workflow, WorkflowState.AWAITING_COMMIT_APPROVAL)
    else:
        log_event(session, workflow_id, AuditEventType.VALIDATION_FAILED, stage="validation", metadata={"attempt": current_attempt})
        _set_state(session, workflow, WorkflowState.VALIDATION_FAILED)
    return workflow


def propose_repair_for_workflow(session: Session, workflow_id: str, provider: LLMProvider) -> RepairAttempt:
    workflow = get_workflow(session, workflow_id)
    if workflow.state != WorkflowState.VALIDATION_FAILED:
        raise OrchestratorError("Repair can only be proposed after a failed validation.")
    if workflow.repair_attempts >= settings.max_repair_attempts:
        raise OrchestratorError(f"MAX_REPAIR_ATTEMPTS ({settings.max_repair_attempts}) already reached.")

    repository = session.get(Repository, workflow.repository_id)
    failing = session.exec(
        select(ValidationResult)
        .where(ValidationResult.workflow_id == workflow_id, ValidationResult.status != "passed")
        .order_by(ValidationResult.timestamp.desc())
    ).first()
    stdout = failing.stdout if failing else ""
    stderr = failing.stderr if failing else ""
    stage = failing.stage if failing else "unknown"

    retrieved = retrieve_multi(repository.collection_name, [workflow.intent, stderr[-200:]], top_k=6)
    diagnosis = diagnose_failure(provider, stage, stdout, stderr, retrieved)
    repair = propose_repair(provider, diagnosis, retrieved)

    attempt_number = workflow.repair_attempts + 1
    row = RepairAttempt(
        workflow_id=workflow_id,
        attempt_number=attempt_number,
        diagnosis=diagnosis.diagnosis,
        repair_patch=repair.proposal.repair_patch,
        result="pending",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    log_event(
        session,
        workflow_id,
        AuditEventType.REPAIR_ATTEMPTED,
        stage="repair",
        metadata={"attempt_number": attempt_number, "diagnosis": diagnosis.diagnosis[:300]},
    )
    return row


def approve_repair(session: Session, workflow_id: str, repair_id: str, approved: bool) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repair = session.get(RepairAttempt, repair_id)
    if repair is None:
        raise OrchestratorError("Repair attempt not found.")

    repair.approved = approved
    workflow.human_intervention_count += 1

    if not approved or not repair.repair_patch:
        repair.result = "failed"
        session.add(repair)
        session.add(workflow)
        session.commit()
        return workflow

    workflow.repair_attempts += 1
    session.add(workflow)
    session.commit()

    _set_state(session, workflow, WorkflowState.REPAIRING)
    workspace = workspace_path(workflow_id)
    # Apply repair patch to each file it touches; a well-formed patch names
    # its target via the diff header, so parse the first "+++ b/<file>" line.
    for line in repair.repair_patch.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[len("+++ b/") :]
            target = workspace / file_path
            if target.exists():
                old_content = target.read_text(encoding="utf-8")
                new_content = apply_patch(old_content, repair.repair_patch)
                target.write_text(new_content, encoding="utf-8")
            break

    repair.result = "pending"
    session.add(repair)
    session.commit()

    return run_validation(session, workflow_id)


def approve_commit(session: Session, workflow_id: str, approved: bool, comment: str = "") -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    workflow.human_intervention_count += 1
    session.add(workflow)
    session.commit()

    if not approved:
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="commit", message=comment)
        _set_state(session, workflow, WorkflowState.FAILED)
        return workflow

    log_event(session, workflow_id, AuditEventType.COMMIT_APPROVED, stage="commit", message=comment)
    workspace = workspace_path(workflow_id)
    branch_name = git_ops.create_branch(workspace, workflow_id, workflow.base_branch)
    commit_info = git_ops.commit(workspace, f"Intent2Deploy AI: {workflow.intent[:72]}")

    session.add(GitOperation(workflow_id=workflow_id, operation="branch_created", detail=branch_name, ref=branch_name, approved=True))
    session.add(GitOperation(workflow_id=workflow_id, operation="commit", detail=commit_info.message, ref=commit_info.hexsha, approved=True))
    workflow.branch_name = branch_name
    session.add(workflow)
    session.commit()

    log_event(session, workflow_id, AuditEventType.COMMIT_CREATED, stage="commit", metadata={"hexsha": commit_info.hexsha, "branch": branch_name})
    _set_state(session, workflow, WorkflowState.COMMITTED)
    return workflow


def finalize_workflow(session: Session, workflow_id: str) -> Workflow:
    """Complete the workflow when no further GitHub CI step is requested."""
    workflow = get_workflow(session, workflow_id)

    if workflow.total_ms is None:
        total = 0
        for field in ("indexing_ms", "planning_ms", "codegen_ms", "testgen_ms", "validation_ms"):
            total += getattr(workflow, field) or 0
        workflow.total_ms = total
    session.add(workflow)
    session.commit()
    log_event(session, workflow_id, AuditEventType.WORKFLOW_COMPLETED, stage="complete")
    _set_state(session, workflow, WorkflowState.COMPLETED)
    return workflow
