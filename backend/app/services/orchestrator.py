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
from app.models.enums import AuditEventType, Environment, GuardrailAction, GuardrailStatus, Severity, WorkflowState
from app.models.models import (
    ChangeApprovalRecord,
    ChaosExperiment,
    GeneratedTest,
    GitOperation,
    GuardrailCheck,
    Plan,
    ProductionReadinessAssessment,
    Project,
    ProposedChange,
    RepairAttempt,
    Repository,
    RetrievedDocument,
    RiskItem,
    ValidationResult,
    Workflow,
)
from app.services.architecture.engine import analyze as analyze_architecture
from app.services.architecture.engine import dependents_of
from app.services.audit import log_event
from app.services.chaos.engine import run_experiments
from app.services.codegen.codegen import ChangeGenerationLimitError, generate_changes
from app.services.codegen.diffing import apply_patch, count_patch_lines
from app.services.git import git_ops
from app.services.guardrails import engine as guardrails
from app.services.guardrails.engine import GuardrailBlockedError
from app.services.planner.category_metadata import CATEGORY_METADATA
from app.services.planner.intent_classifier import classify_intent
from app.services.planner.planner import generate_plan
from app.services.providers.base import LLMProvider
from app.services.rag.indexer import index_repository
from app.services.rag.retriever import retrieve_multi
from app.services.readiness.engine import ReadinessInput, assess as assess_readiness
from app.services.risk.engine import derive_risks, highest_severity
from app.services.state_machine import InvalidTransitionError, transition
from app.services.testing.mock_test_strategies import STRATEGIES as MOCK_TEST_STRATEGIES
from app.services.validation.pipeline import run_pipeline, overall_status
from app.services.validation.repair import diagnose_failure, propose_repair
from app.services.validation.sandbox import create_workspace, run_command, workspace_path

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
    environment: str = Environment.SANDBOX.value,
) -> Workflow:
    workflow = Workflow(
        project_id=project_id,
        repository_id=repository_id,
        intent=intent,
        base_branch=base_branch,
        test_command=test_command,
        build_command=build_command,
        environment=Environment(environment) if environment in (e.value for e in Environment) else Environment.SANDBOX,
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    log_event(session, workflow.id, AuditEventType.WORKFLOW_CREATED, message=f"intent={intent!r}")

    # ---- INPUT guardrails: run BEFORE the workflow proceeds any further ----
    classification = guardrails.classify_input(intent)
    for check in classification.checks:
        guardrails.record(session, workflow.id, check)
    if classification.classification in ("BLOCKED", "UNSAFE"):
        workflow.state = WorkflowState.FAILED
        session.add(workflow)
        session.commit()
        blocking = [c for c in classification.checks if c.status == GuardrailStatus.BLOCKED.value]
        detail = "; ".join(f"[{c.guardrail_id}] {c.name}: {c.trigger_condition}" for c in blocking)
        raise OrchestratorError(
            f"Input classified {classification.classification} — workflow creation refused. {detail} "
            "Recovery action: rewrite the request; destructive, production-targeting, injection-shaped, or "
            "secret-bearing requests are never accepted."
        )

    # ---- DEPLOYMENT / INFRASTRUCTURE guardrails: verify the execution environment ----
    for result in (
        guardrails.check_environment_verification("workflow_creation", workflow.environment.value),
        guardrails.check_production_block("workflow_creation", workflow.environment.value),
        guardrails.check_environment_isolation("workflow_creation", workflow.environment.value),
    ):
        guardrails.record(session, workflow.id, result)
        if result.action in (GuardrailAction.BLOCK.value, GuardrailAction.ABORT.value):
            workflow.state = WorkflowState.FAILED
            session.add(workflow)
            session.commit()
            raise OrchestratorError(
                f"Guardrail [{result.guardrail_id}] {result.name} BLOCKED workflow creation: {result.trigger_condition} "
                "Recovery action: recreate the workflow with environment=sandbox|test|staging|production-simulation|local."
            )
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

    # ---- AI/LLM guardrails: repository content is DATA, never instructions ----
    retrieved_texts = {r.file: r.content_preview for r in result.retrieved}
    guardrails.record(session, workflow_id, guardrails.check_prompt_injection("planning", retrieved_texts))
    guardrails.record(session, workflow_id, guardrails.check_context_boundary("planning", {"retrieved_context": result.retrieved_context_text, "intent": workflow.intent}))
    guardrails.record(session, workflow_id, guardrails.check_model_output_validation("planning", True, "PlanOutput parsed successfully via Pydantic schema."))

    workflow.llm_call_count += result.llm_call_count
    workflow.llm_estimated_tokens += result.llm_estimated_tokens
    workflow.llm_estimated_cost_usd += (result.llm_estimated_tokens / 1000) * settings.cost_per_1k_tokens_usd
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_model_usage("planning", provider.name, settings.model_name, result.prompt_versions.get("implementation_planning", ""), result.llm_call_count, result.llm_estimated_tokens),
    )
    guardrails.record(session, workflow_id, guardrails.check_llm_call_limit("planning", workflow.llm_call_count))
    guardrails.record(session, workflow_id, guardrails.check_llm_token_limit("planning", workflow.llm_estimated_tokens))
    guardrails.record(session, workflow_id, guardrails.check_workflow_budget("planning", workflow.llm_estimated_cost_usd))

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

    unverified_claims = [] if plan.risks else ["Plan states no risks — treat absence of stated risk as UNVERIFIED, not as evidence of low risk."]
    evidence_result = guardrails.check_hallucination_evidence("planning", result.invented_files_removed, unverified_claims)
    guardrails.record(session, workflow_id, evidence_result)

    session.add(workflow)
    session.commit()

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

    # Plan approval is enforced by the workflow state machine and recorded
    # via AuditEvent PLAN_APPROVED/PLAN_REJECTED above/below — it is a
    # workflow-lifecycle concern, not one of the 8 guardrail categories.

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
        guardrails.record(
            session,
            workflow_id,
            guardrails.GuardrailCheckResult(
                guardrail_id="OUTPUT-05",
                category=guardrails.CAT.OUTPUT.value,
                name="Scope Validation",
                description="Enforces MAX_FILES_CHANGED/MAX_PATCH_LINES and plan-file scope.",
                purpose="Generated output must not silently grow beyond what was reviewed.",
                enforcement_point="codegen",
                trigger_condition=str(exc),
                severity=Severity.HIGH.value,
                status=GuardrailStatus.BLOCKED.value,
                action=GuardrailAction.BLOCK.value,
                remediation="Revise the plan to touch fewer files, or raise MAX_FILES_CHANGED/MAX_PATCH_LINES with human sign-off.",
            ),
        )
        log_event(session, workflow_id, AuditEventType.PATCH_GENERATED, stage="codegen", message=f"REJECTED: {exc}")
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(
            f"Guardrail [OUTPUT-05] Scope Validation BLOCKED code generation: {exc} "
            "Recovery action: revise the plan to touch fewer files, or raise MAX_FILES_CHANGED/MAX_PATCH_LINES with human sign-off."
        ) from exc

    workflow.codegen_ms = int((time.monotonic() - start) * 1000)
    workflow.llm_call_count += 1
    workflow.llm_estimated_tokens += result.llm_estimated_tokens
    workflow.llm_estimated_cost_usd += (result.llm_estimated_tokens / 1000) * settings.cost_per_1k_tokens_usd
    session.add(workflow)

    changed_files = [c.file for c in result.changeset.changes]
    patch_lines = {c.file: count_patch_lines(c.patch) for c in result.changeset.changes}
    approved_scope = sorted(set(target_files) | set(json.loads(plan_row.files_json)))

    # ---- AI/LLM guardrails ----
    guardrails.record(session, workflow_id, guardrails.check_context_boundary("codegen", {"code_context": result.context_text}))
    guardrails.record(session, workflow_id, guardrails.check_model_output_validation("codegen", True, "ChangeSetOutput parsed successfully via Pydantic schema."))
    guardrails.record(session, workflow_id, guardrails.check_model_usage("codegen", provider.name, settings.model_name, result.prompt_version, 1, result.llm_estimated_tokens))
    guardrails.record(session, workflow_id, guardrails.check_llm_call_limit("codegen", workflow.llm_call_count))
    guardrails.record(session, workflow_id, guardrails.check_llm_token_limit("codegen", workflow.llm_estimated_tokens))
    guardrails.record(session, workflow_id, guardrails.check_workflow_budget("codegen", workflow.llm_estimated_cost_usd))
    guardrails.record(session, workflow_id, guardrails.check_ai_confidence("codegen", [c.confidence for c in result.changeset.changes], []))

    # ---- OUTPUT + SECURITY guardrails on the generated change set ----
    sibling_results: list[guardrails.GuardrailCheckResult] = []

    scope_result = guardrails.check_output_scope_validation("codegen", len(changed_files), patch_lines, approved_scope, changed_files)
    sibling_results.append(scope_result)
    try:
        guardrails.enforce(session, workflow_id, scope_result)
    except GuardrailBlockedError as exc:
        raise OrchestratorError(
            f"Codegen blocked: {exc} Recovery action: either revise the approved plan to include these files, "
            "or regenerate changes scoped to the original plan and configured limits."
        ) from exc

    generated_texts = {c.file: (c.patch + " " + c.reason) for c in result.changeset.changes}
    repo_root = Path(repository.local_path)

    # ---- native SECURITY category checks (in addition to their OUTPUT-xx mirrors) ----
    guardrails.record(session, workflow_id, guardrails.check_secret_detection("codegen", generated_texts))
    guardrails.record(session, workflow_id, guardrails.check_code_security("codegen", generated_texts))
    guardrails.record(session, workflow_id, guardrails.check_dependency_security("codegen", changed_files))
    guardrails.record(session, workflow_id, guardrails.check_security_configuration("codegen", generated_texts))
    dockerfile_texts = {
        str(p.relative_to(repo_root)): p.read_text(encoding="utf-8", errors="ignore")
        for p in repo_root.glob("**/Dockerfile*")
        if p.is_file() and "node_modules" not in p.parts
    }
    guardrails.record(session, workflow_id, guardrails.check_container_security("codegen", dockerfile_texts))

    secret_result = guardrails.check_output_secret_detection("codegen", generated_texts)
    sibling_results.append(secret_result)
    try:
        guardrails.enforce(session, workflow_id, secret_result)
    except GuardrailBlockedError as exc:
        raise OrchestratorError(
            f"Codegen blocked: {exc} Recovery action: the proposed patch was withheld; do not retry with the "
            "same content. Review the target file for accidentally-committed secrets."
        ) from exc

    security_result = guardrails.check_output_security_validation("codegen", generated_texts)
    sibling_results.append(security_result)
    try:
        guardrails.enforce(session, workflow_id, security_result)
    except GuardrailBlockedError as exc:
        raise OrchestratorError(
            f"Codegen blocked: {exc} Recovery action: rework the flagged construct using a safe API before retrying."
        ) from exc

    unsafe_cmd_result = guardrails.check_output_unsafe_command("codegen", generated_texts)
    sibling_results.append(unsafe_cmd_result)
    guardrails.record(session, workflow_id, unsafe_cmd_result)

    dep_result = guardrails.check_output_dependency_change("codegen", changed_files)
    sibling_results.append(dep_result)
    guardrails.record(session, workflow_id, dep_result)

    migration_result = guardrails.check_output_database_migration("codegen", changed_files)
    sibling_results.append(migration_result)
    guardrails.record(session, workflow_id, migration_result)

    infra_result = guardrails.check_output_infrastructure_change("codegen", changed_files)
    sibling_results.append(infra_result)
    guardrails.record(session, workflow_id, infra_result)

    config_drift_result = guardrails.check_configuration_drift("codegen", changed_files)
    sibling_results.append(config_drift_result)
    guardrails.record(session, workflow_id, config_drift_result)

    for c in result.changeset.changes:
        old_content = (repo_root / c.file).read_text(encoding="utf-8", errors="ignore") if (repo_root / c.file).is_file() else ""
        try:
            new_content = apply_patch(old_content, c.patch) if c.patch else old_content
        except Exception:  # noqa: BLE001 - best-effort compatibility scan only
            new_content = old_content
        api_result = guardrails.check_output_api_compatibility("codegen", c.file, old_content, new_content)
        sibling_results.append(api_result)
        guardrails.record(session, workflow_id, api_result)

    architecture = analyze_architecture(repo_root)
    dependents = dependents_of(architecture, changed_files)
    affected_modules = sorted({Path(f).parent.as_posix() for f in changed_files})
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_infrastructure_blast_radius("codegen", changed_files, affected_modules, dependents),
    )

    guardrails.record(session, workflow_id, guardrails.check_output_policy_compliance("codegen", sibling_results))

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

    guardrails.record(session, workflow_id, guardrails.check_deployment_approval("implementation_to_apply", approved, comment))

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

    # CICD Regression Gate groundwork: capture whether the PRE-change test
    # suite passes, so a post-change failure can be told apart from a
    # pre-existing failure later.
    baseline_command = workflow.test_command.strip() or "python3 -m pytest -q"
    cmd_result = guardrails.check_command_safety("approve_changes.baseline", [baseline_command])
    guardrails.record(session, workflow_id, cmd_result)
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_tool_permission_control("approve_changes.baseline", classified_count=1, executed_count=1),
    )
    baseline_result = run_command(workspace, baseline_command)
    workflow.baseline_tests_passed = baseline_result.exit_code == 0 if baseline_result.rejected_reason == "" else None
    session.add(workflow)
    session.commit()

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

    validated_commands = [s.result.command for s in stages if s.result.command]
    guardrails.record(session, workflow_id, guardrails.check_command_safety("validation", validated_commands))
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_tool_permission_control("validation", classified_count=len(validated_commands), executed_count=len(validated_commands)),
    )

    unit_test_stage = next((s for s in stages if s.stage == "unit_tests"), None)
    final_unit_tests_passed = (unit_test_stage.result.status == "passed") if unit_test_stage else None
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_regression_gate("validation", workflow.baseline_tests_passed, final_unit_tests_passed),
    )

    stage_statuses = {s.stage: s.result.status for s in stages}
    guardrails.record(session, workflow_id, guardrails.check_test_gate("validation", stage_statuses))

    build_stage = next((s for s in stages if s.stage == "build"), None)
    guardrails.record(session, workflow_id, guardrails.check_build_gate("validation", bool(workflow.build_command.strip()), build_stage.result.status if build_stage else None))

    security_stage = next((s for s in stages if s.stage == "security"), None)
    security_findings = security_stage.result.stdout.count("\n") if security_stage and security_stage.result.status != "passed" else 0
    guardrails.record(session, workflow_id, guardrails.check_security_scan_gate("validation", security_stage.result.status if security_stage else None, security_findings))

    guardrails.record(session, workflow_id, guardrails.check_failure_gate("validation", stage_statuses))

    stages_have_evidence = all(s.result.command for s in stages) and bool(stages)
    guardrails.record(
        session,
        workflow_id,
        guardrails.check_ci_evidence_gate("validation", stages_have_evidence, f"{len(stages)} stage(s) executed with recorded command/duration/exit_code"),
    )

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
    guardrails.record(session, workflow_id, guardrails.check_repair_loop_limit("repair", workflow.repair_attempts, guardrail_id="AI-08", category=guardrails.CAT.AI_LLM.value, name="Retry/Repair Limit"))
    guardrails.record(session, workflow_id, guardrails.check_ci_cost_awareness("repair", workflow.repair_attempts, workflow.repair_attempts + 1))
    try:
        guardrails.enforce(session, workflow_id, guardrails.check_repair_loop_limit("repair", workflow.repair_attempts))
    except GuardrailBlockedError as exc:
        raise OrchestratorError(
            f"Guardrail [COST-03] Repair Loop Cost Limit BLOCKED further repair attempts: {exc} "
            "Recovery action: a human must diagnose the failure manually; this workflow cannot self-repair further."
        ) from exc

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

    guardrails.record(session, workflow_id, guardrails.check_deployment_approval("apply_to_commit", approved, comment))

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

    guardrails.record(
        session,
        workflow_id,
        guardrails.check_deployment_evidence("commit", workflow.environment.value, commit_info.hexsha, branch_name, "not_deployed_yet"),
    )

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


# ---------------------------------------------------------------------------
# Architecture / Risk / Chaos / Production Readiness (Parts B, C, F, K)
# ---------------------------------------------------------------------------
def get_architecture(session: Session, workflow_id: str) -> dict:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")
    snapshot = analyze_architecture(Path(repository.local_path))
    return {
        "components": [
            {"name": c.name, "path": c.path, "files": c.files, "functions": c.functions, "classes": c.classes}
            for c in snapshot.components
        ],
        "external_dependencies": snapshot.external_dependencies,
        "total_files": snapshot.total_files,
        "total_functions": snapshot.total_functions,
        "total_classes": snapshot.total_classes,
    }


def run_risk_analysis(session: Session, workflow_id: str) -> list[RiskItem]:
    workflow = get_workflow(session, workflow_id)
    plan_row = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    if plan_row is None:
        raise OrchestratorError("Cannot run risk analysis before a plan exists for this workflow.")

    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    changed_files = [c.file for c in changes] or json.loads(plan_row.files_json)
    category = classify_intent(workflow.intent)
    category_risks = CATEGORY_METADATA.get(category, CATEGORY_METADATA["generic"]).get("risks", [])

    derived = derive_risks(
        plan_risks=json.loads(plan_row.risks_json),
        category_risks=category_risks,
        changed_files=changed_files,
        acceptance_criteria=json.loads(plan_row.acceptance_criteria_json),
    )

    # Re-running risk analysis replaces the previous snapshot for this workflow.
    for existing in session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all():
        session.delete(existing)
    session.commit()

    rows: list[RiskItem] = []
    for r in derived:
        row = RiskItem(
            workflow_id=workflow_id,
            risk_id=r.risk_id,
            title=r.title,
            component=r.component,
            severity=r.severity,
            likelihood=r.likelihood,
            blast_radius=r.blast_radius,
            detection=r.detection,
            mitigation=r.mitigation,
            validation_method=r.validation_method,
            status=r.status,
            evidence_json=json.dumps(r.evidence),
            source=r.source,
        )
        session.add(row)
        rows.append(row)
    session.commit()

    plan_text = " ".join([plan_row.summary, *json.loads(plan_row.risks_json)])
    top_severity = highest_severity(derived)
    rollback_result = guardrails.check_rollback_requirement("risk_analysis", top_severity, plan_text)
    guardrails.record(session, workflow_id, rollback_result)

    return rows


def run_chaos_simulation(session: Session, workflow_id: str) -> list[ChaosExperiment]:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    chaos_gate = guardrails.check_environment_isolation("chaos_simulation", workflow.environment.value)
    try:
        guardrails.enforce(session, workflow_id, chaos_gate)
    except GuardrailBlockedError as exc:
        raise OrchestratorError(
            f"Guardrail [INFRA-04] Environment Isolation BLOCKED the resilience simulation: {exc} "
            "Recovery action: only run chaos experiments against local/sandbox/test/staging/production-simulation environments."
        ) from exc

    workspace = workspace_path(workflow_id)
    target_root = workspace if workspace.exists() else Path(repository.local_path)
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all()
    changed_files = [c.file for c in changes]

    outcomes = run_experiments(target_root, changed_files, workflow.intent)

    for existing in session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id)).all():
        session.delete(existing)
    session.commit()

    rows: list[ChaosExperiment] = []
    for o in outcomes:
        row = ChaosExperiment(
            workflow_id=workflow_id,
            experiment_id=o.experiment_id,
            target=o.target,
            hypothesis=o.hypothesis,
            fault=o.fault,
            expected_behavior=o.expected_behavior,
            observed_behavior=o.observed_behavior,
            result=o.result,
            environment=workflow.environment.value,
            evidence_json=json.dumps(o.evidence),
        )
        session.add(row)
        rows.append(row)
    session.commit()

    # Reconcile: a risk is only ever marked MITIGATED by real evidence — a
    # matching, passing resilience/chaos experiment against the same
    # component, never by assumption.
    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    for risk in risks:
        matching = [r for r in rows if risk.component and risk.component.rstrip("s") in r.target.lower()]
        applicable_matching = [r for r in matching if r.result != "NOT_APPLICABLE"]
        if applicable_matching and all(r.result == "PASSED" for r in applicable_matching):
            risk.status = "MITIGATED"
            session.add(risk)
    session.commit()

    return rows


def run_production_readiness(session: Session, workflow_id: str) -> ProductionReadinessAssessment:
    get_workflow(session, workflow_id)  # existence check only

    latest_validation_attempt = session.exec(
        select(ValidationResult).where(ValidationResult.workflow_id == workflow_id).order_by(ValidationResult.timestamp.desc())
    ).first()
    validation_passed: bool | None = None
    if latest_validation_attempt is not None:
        max_attempt = max(
            v.attempt for v in session.exec(select(ValidationResult).where(ValidationResult.workflow_id == workflow_id)).all()
        )
        latest = session.exec(
            select(ValidationResult).where(ValidationResult.workflow_id == workflow_id, ValidationResult.attempt == max_attempt)
        ).all()
        validation_passed = all(v.status == "passed" for v in latest if v.stage in ("syntax", "unit_tests"))

    guardrail_checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id)).all()
    blocked_names = sorted({c.name for c in guardrail_checks if c.status == GuardrailStatus.BLOCKED.value})
    warning_names = sorted({c.name for c in guardrail_checks if c.status == GuardrailStatus.WARNING.value})

    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    open_critical = sum(1 for r in risks if r.severity == Severity.CRITICAL.value and r.status == "OPEN")
    open_high = sum(1 for r in risks if r.severity == Severity.HIGH.value and r.status == "OPEN")

    chaos_rows = session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id)).all()
    applicable_chaos = [c for c in chaos_rows if c.result != "NOT_APPLICABLE"]
    pass_rate = (
        round(sum(1 for c in applicable_chaos if c.result == "PASSED") / len(applicable_chaos), 3) if applicable_chaos else None
    )

    failure_gate_event = next((c for c in reversed(guardrail_checks) if c.guardrail_id == "CICD-07"), None)
    ci_passed = None if failure_gate_event is None else failure_gate_event.status == GuardrailStatus.PASSED.value

    rollback_event = next((c for c in reversed(guardrail_checks) if c.guardrail_id == "DEPLOY-04"), None)
    rollback_status = rollback_event.status if rollback_event else "NOT_APPLICABLE"

    cost_event = next((c for c in reversed(guardrail_checks) if c.guardrail_id == "COST-07"), None)
    cost_status = cost_event.status if cost_event else "NOT_APPLICABLE"

    result = assess_readiness(
        ReadinessInput(
            validation_passed=validation_passed,
            blocked_guardrails=blocked_names,
            warning_guardrails=warning_names,
            open_critical_risks=open_critical,
            open_high_risks=open_high,
            chaos_pass_rate=pass_rate,
            rollback_status=rollback_status,
            ci_passed=ci_passed,
            cost_status=cost_status,
        )
    )

    row = ProductionReadinessAssessment(
        workflow_id=workflow_id,
        decision=result.decision,
        reasons_json=json.dumps(result.reasons),
        checklist_json=json.dumps(result.checklist),
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    # NOTE: Production Readiness is the terminal composite decision (Part K),
    # deliberately kept separate from the 8-category Guardrail Control Plane
    # — it is not itself one of SECURITY/INFRASTRUCTURE/CI_CD/DEPLOYMENT/
    # COST/AI_LLM/INPUT/OUTPUT, so it is persisted only as a
    # ProductionReadinessAssessment row, not as an additional GuardrailCheck.
    return row
