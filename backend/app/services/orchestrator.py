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
from app.core.llm_reliability import LLMOutputError
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
from app.services.codegen.codegen import ChangeGenerationLimitError, ChangeGenerationResult, generate_changes
from app.services.codegen.diffing import (
    PatchConflictError,
    apply_patch,
    count_patch_lines,
    make_new_file_diff,
    make_unified_diff,
)
from app.services.git import git_ops
from app.services.guardrails import engine as guardrails
from app.services.github import github_ops
from app.services.greenfield import service as greenfield
from app.services.greenfield.schemas import ProjectDesign
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
    if target == WorkflowState.FAILED:
        workflow.failed_from = workflow.state.value  # where to resume from
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
    repository.source_file_count = stats.source_file_count
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
        workflow.failed_from = "INPUT_REFUSED"
        session.add(workflow)
        session.commit()
        blocking = [c for c in classification.checks if c.status == GuardrailStatus.BLOCKED.value]
        detail = "; ".join(f"[{c.guardrail_id}] {c.name}: {c.trigger_condition}" for c in blocking)
        reason = (
            f"Input classified {classification.classification} — workflow creation refused. {detail} "
            "Recovery action: rewrite the request; destructive, production-targeting, injection-shaped, or "
            "secret-bearing requests are never accepted."
        )
        log_event(session, workflow.id, AuditEventType.WORKFLOW_FAILED, stage="intent", message=reason)
        raise OrchestratorError(reason)

    # ---- DEPLOYMENT / INFRASTRUCTURE guardrails: verify the execution environment ----
    for result in (
        guardrails.check_environment_verification("workflow_creation", workflow.environment.value),
        guardrails.check_production_block("workflow_creation", workflow.environment.value),
        guardrails.check_environment_isolation("workflow_creation", workflow.environment.value),
    ):
        guardrails.record(session, workflow.id, result)
        if result.action in (GuardrailAction.BLOCK.value, GuardrailAction.ABORT.value):
            workflow.state = WorkflowState.FAILED
            workflow.failed_from = "INPUT_REFUSED"
            session.add(workflow)
            session.commit()
            reason = (
                f"Guardrail [{result.guardrail_id}] {result.name} BLOCKED workflow creation: {result.trigger_condition} "
                "Recovery action: recreate the workflow with environment=sandbox|test|staging|production-simulation|local."
            )
            log_event(session, workflow.id, AuditEventType.WORKFLOW_FAILED, stage="intent", message=reason)
            raise OrchestratorError(reason)
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
    try:
        # A missing/unreadable folder must not be mistaken for an empty repository.
        if not Path(repository.local_path).is_dir():
            raise FileNotFoundError(f"Repository folder not found: {repository.local_path}")
        run_indexing_for_repository(session, repository)
    except Exception as exc:
        session.rollback()
        reason = (
            f"Indexing failed ({type(exc).__name__}: {str(exc)[:300]}). This is an error reading or indexing the "
            "repository, not an empty repository. Check that the path exists and is readable, then start a new workflow."
        )
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="indexing", message=reason)
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(reason) from exc

    workflow.indexing_ms = int((time.monotonic() - start) * 1000)
    # No usable source code -> design and generate the project from scratch.
    workflow.project_mode = "greenfield" if repository.source_file_count == 0 else "existing"
    parent = session.get(Workflow, workflow.revision_of) if workflow.revision_of else None
    if json.loads(workflow.revision_addons or "[]"):
        # Built-in add-ons applied to the code on staging (no model needed).
        workflow.project_mode = "addon"
    elif parent is not None and parent.project_mode == "greenfield" and settings.is_mock:
        # Mock mode revising a project it generated: rebuild it from its
        # templates with the fix, as changes to the files that are there now.
        # (With a live model a revision edits the existing code instead.)
        workflow.project_mode = "greenfield"
    session.add(workflow)
    session.commit()
    log_event(
        session,
        workflow_id,
        AuditEventType.INDEXING_COMPLETED,
        stage="indexing",
        metadata={
            "file_count": repository.file_count,
            "source_file_count": repository.source_file_count,
            "chunk_count": repository.chunk_count,
            "project_mode": workflow.project_mode,
        },
    )
    _set_state(session, workflow, WorkflowState.INDEXED)
    return workflow


def run_planning(session: Session, workflow_id: str, provider: LLMProvider) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")
    if workflow.project_mode == "greenfield":
        return _run_greenfield_planning(session, workflow, repository, provider)
    if workflow.project_mode == "addon":
        return _run_addon_planning(session, workflow, repository)

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
    _add_containerization_to_plan(repository, plan)
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
    # Risks are derived from the plan, so the reviewer sees them before approving.
    _run_follow_up(session, workflow_id, "risk_analysis", run_risk_analysis)
    return workflow


def _existing_files(repository: Repository, limit: int = 300) -> list[str]:
    root = Path(repository.local_path)
    files: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(root).parts:
            files.append(p.relative_to(root).as_posix())
            if len(files) >= limit:
                break
    return files


def _run_greenfield_planning(session: Session, workflow: Workflow, repository: Repository, provider: LLMProvider) -> Workflow:
    """Requirements analysis + architecture design for a repository with no
    usable source code. Retrieval and existing-code analysis are skipped:
    there is no code to retrieve from."""
    workflow_id = workflow.id
    _set_state(session, workflow, WorkflowState.PLANNING)
    start = time.monotonic()
    try:
        port, preview = _project_port(repository)
        result = greenfield.design_project(
            provider, workflow.intent, _existing_files(repository), port, preview, revision=bool(workflow.revision_of)
        )
    except (greenfield.GreenfieldError, LLMOutputError) as exc:
        reason = f"Project design failed: {exc}"
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="planning", message=reason)
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(reason) from exc

    design = result.design
    workflow.planning_ms = int((time.monotonic() - start) * 1000)
    workflow.greenfield_design_json = design.model_dump_json()
    workflow.llm_call_count += 1
    workflow.llm_estimated_tokens += result.llm_estimated_tokens
    workflow.llm_estimated_cost_usd += (result.llm_estimated_tokens / 1000) * settings.cost_per_1k_tokens_usd
    session.add(workflow)

    guardrails.record(session, workflow_id, guardrails.check_model_output_validation("planning", True, "ProjectDesign parsed successfully via Pydantic schema."))
    guardrails.record(session, workflow_id, guardrails.check_model_usage("planning", provider.name, settings.model_name, result.prompt_version, 1, result.llm_estimated_tokens))
    guardrails.record(session, workflow_id, guardrails.check_llm_call_limit("planning", workflow.llm_call_count))
    guardrails.record(session, workflow_id, guardrails.check_llm_token_limit("planning", workflow.llm_estimated_tokens))
    guardrails.record(session, workflow_id, guardrails.check_workflow_budget("planning", workflow.llm_estimated_cost_usd))

    plan = greenfield.design_to_plan(design)
    if workflow.revision_note:
        plan.summary = f"Revision — fixing what was reported on staging: \"{workflow.revision_note}\". {plan.summary}"
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
        prompt_version=result.prompt_version,
        raw_llm_output=result.raw_llm_output,
    )
    session.add(plan_row)
    session.commit()
    session.refresh(plan_row)
    log_event(
        session,
        workflow_id,
        AuditEventType.PLAN_GENERATED,
        stage="planning",
        message="Greenfield: requirements analyzed and architecture designed (repository had no source code).",
        metadata={"plan_id": plan_row.id, "project_mode": "greenfield", "files": len(design.files), "stack": design.stack},
    )
    _set_state(session, workflow, WorkflowState.PLAN_READY)
    _set_state(session, workflow, WorkflowState.AWAITING_PLAN_APPROVAL)
    _run_follow_up(session, workflow_id, "risk_analysis", run_risk_analysis)
    return workflow


def _run_addon_planning(session: Session, workflow: Workflow, repository: Repository) -> Workflow:
    """Plan for a revision made of built-in add-ons: exactly which files each
    one changes, worked out now from the code on staging."""
    from app.services import addons

    _set_state(session, workflow, WorkflowState.PLANNING)
    start = time.monotonic()
    ids = json.loads(workflow.revision_addons)
    original, changed, used = addons.apply_all(Path(repository.local_path), ids)
    if not used or not changed:
        reason = "None of the selected add-ons can be applied to the code on staging any more (already applied or not supported)."
        log_event(session, workflow.id, AuditEventType.WORKFLOW_FAILED, stage="planning", message=reason)
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(reason)
    steps = []
    for i, addon_id in enumerate(used, start=1):
        addon = addons.catalog.BY_ID[addon_id]
        files = sorted(addons.catalog.BY_ID[addon_id].apply(original))  # this add-on's own files
        steps.append({"id": f"S{i}", "description": f"{addon.title}: {addon.description}", "files": files})
    plan_row = Plan(
        workflow_id=workflow.id,
        summary=f"Revision — fixing what was reported on staging: \"{workflow.revision_note}\". "
        f"Applies the built-in add-on(s) {', '.join(addons.catalog.BY_ID[a].title for a in used)} to the code on staging.",
        assumptions_json=json.dumps(["The code on staging is the project Intent2Deploy generated (its files are recognised)."]),
        acceptance_criteria_json=json.dumps([addons.catalog.BY_ID[a].description for a in used]
                                            + ["The project's existing tests and the add-on tests pass."]),
        steps_json=json.dumps(steps),
        files_json=json.dumps(sorted(changed)),
        dependencies_json="[]",
        test_strategy_json=json.dumps(["Run the project's test suite, including the tests each add-on adds."]),
        risks_json=json.dumps(["Changes existing files on staging: review the diff before approving. "
                               "Validation runs the full test suite and the live production checks."]),
        prompt_version="addons-v1",
        raw_llm_output="",
    )
    session.add(plan_row)
    workflow.planning_ms = int((time.monotonic() - start) * 1000)
    session.add(workflow)
    session.commit()
    log_event(session, workflow.id, AuditEventType.PLAN_GENERATED, stage="planning",
              message=f"Add-on plan: {', '.join(used)}", metadata={"plan_id": plan_row.id, "files": len(changed)})
    _set_state(session, workflow, WorkflowState.PLAN_READY)
    _set_state(session, workflow, WorkflowState.AWAITING_PLAN_APPROVAL)
    _run_follow_up(session, workflow.id, "risk_analysis", run_risk_analysis)
    return workflow


def _addon_changes(repository: Repository, workflow: Workflow) -> ChangeGenerationResult:
    from app.schemas.change import ChangeSetOutput, ProposedChangeItem
    from app.services import addons
    from app.services.codegen.diffing import make_new_file_diff, make_unified_diff

    original, changed, used = addons.apply_all(Path(repository.local_path), json.loads(workflow.revision_addons))
    owner = {}
    for addon_id in used:
        for path in addons.catalog.BY_ID[addon_id].apply(original):
            owner.setdefault(path, addons.catalog.BY_ID[addon_id].title)
    changes = []
    for path, content in sorted(changed.items()):
        old = original.get(path)
        changes.append(ProposedChangeItem(
            file=path,
            operation="create" if old is None else "modify",
            reason=f"{owner.get(path, 'Add-on')}: {'new file' if old is None else 'updated'}",
            patch=make_new_file_diff(path, content) if old is None else make_unified_diff(path, old, content),
            confidence=0.9,
        ))
    return ChangeGenerationResult(changeset=ChangeSetOutput(changes=changes), prompt_version="addons-v1",
                                  raw_llm_output="", context_text="", llm_estimated_tokens=0)


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

    # Regenerating after a rejection re-enters CHANGES_GENERATING first; any
    # other state is refused before anything is generated or recorded.
    if workflow.state == WorkflowState.CHANGES_REJECTED:
        _set_state(session, workflow, WorkflowState.CHANGES_GENERATING)
    elif workflow.state != WorkflowState.CHANGES_GENERATING:
        raise OrchestratorError(f"Cannot generate changes while the workflow is {workflow.state.value}.")

    target_files: list[str] = json.loads(plan_row.files_json)
    step_descriptions = [s.get("description", "") for s in json.loads(plan_row.steps_json)]

    start = time.monotonic()
    try:
        if workflow.project_mode == "addon":
            result = _addon_changes(repository, workflow)
        elif workflow.project_mode == "greenfield":
            design = ProjectDesign.model_validate_json(workflow.greenfield_design_json)
            result = greenfield.generate_project(
                provider, workflow.intent, design, _existing_files(repository),
                revise_root=Path(repository.local_path) if workflow.revision_of else None,
            )
        else:
            result = generate_changes(
                provider,
                Path(repository.local_path),
                target_files,
                workflow.intent,
                plan_row.summary,
                step_descriptions,
            )
    except (greenfield.GreenfieldError, LLMOutputError) as exc:
        # Retryable: the workflow stays in CHANGES_GENERATING.
        raise OrchestratorError(f"Project generation failed: {exc} Retry, or start a new workflow.") from exc
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
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="codegen", message=f"Scope limits exceeded: {exc}")
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

    if not any(c.patch.strip() for c in result.changeset.changes):
        # Nothing to review (no changes, or only empty patches): waiting for a
        # change approval would dead-end, and regenerating gives the same result.
        provider_note = next((c.reason for c in result.changeset.changes if c.reason), "")
        if workflow.revision_of and provider.is_mock:
            from app.services import revision_check

            found = revision_check.check(Path(repository.local_path), workflow.revision_note)
            missing = [f.capability for f in found.findings if not f.present]
            if found.findings and not missing:
                reason = (
                    f"Nothing to change: what was reported (\"{workflow.revision_note[:200]}\") is already in the code on "
                    "staging, so rebuilding the project gives exactly the same files. " + found.summary().replace("\n", " · ")
                )
            else:
                reason = (
                    f"Mock mode can't make this change (\"{workflow.revision_note[:200]}\"): it only rebuilds projects "
                    "from its built-in templates, and rebuilding gives exactly the code already on staging. "
                    + (f"Still missing: {', '.join(missing)}. " if missing else "")
                    + "Make the change by hand (push a branch and open a PR into staging), or use the live AI."
                )
        elif provider.is_mock and workflow.project_mode == "existing":
            # The common trap: a request for a new app against a repo/branch that already has code.
            reason = (
                "Code generation produced no changes: this repository already contains code (it was analysed as an existing "
                f"project{f' on branch {settings.staging_branch}' if settings.staging_branch else ''}), and mock mode "
                "cannot rewrite an existing codebase for this request — it only builds new projects into a repository "
                "with no code, plus a few built-in changes for the bundled demo repository. To get a new project, remove "
                "the existing code (on GitHub: delete the staging/feature branches and leave main empty), or set "
                "LLM_MODE=live with an API key to change existing code. Then start a new workflow."
            )
        else:
            reason = (
                "Code generation produced no changes, so there is nothing to review. "
                + (provider_note or "The plan targets no existing files (e.g. the repository is empty) or the provider proposed nothing.")
            )
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="codegen", message=reason)
        _set_state(session, workflow, WorkflowState.FAILED)
        if workflow.revision_of and provider.is_mock:
            # Resuming would rebuild the same files again: the UI offers no resume for this.
            workflow.failed_from = "NO_CHANGES"
            session.add(workflow)
            session.commit()
        raise OrchestratorError(reason)

    if workflow.project_mode not in ("greenfield", "addon"):
        _append_docker_changes(repository, result.changeset.changes)

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

    # Platform-added Docker files don't count against the change-size limit;
    # a generated project has its own (larger) limit.
    from app.services.containerize import PLATFORM_DOCKER_FILES

    feature_files = [f for f in changed_files if f not in PLATFORM_DOCKER_FILES]
    scope_result = guardrails.check_output_scope_validation(
        "codegen", len(feature_files), patch_lines, approved_scope, changed_files,
        max_files=settings.max_greenfield_files if workflow.project_mode == "greenfield" else None,
    )
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

    # A regenerated change set replaces the rejected one.
    for existing in session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow_id)).all():
        session.delete(existing)

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
    # Re-derive risks from the files actually changed, not just the plan's guess.
    _run_follow_up(session, workflow_id, "risk_analysis", run_risk_analysis)
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
    # Feature-branch workflow: main is never changed directly. The change gets
    # its own branch, started from the LATEST main (fetched from GitHub when
    # the repository is linked), and reaches main only through a reviewed PR.
    workspace = create_workspace(workflow_id, Path(repository.local_path))
    branch = git_ops.feature_branch_name(workflow_id, workflow.intent)
    target = github_ops.resolve_target(repository)
    fetch_note = ""
    try:
        from app.services.repos.manager import _git_env

        info = git_ops.prepare_feature_branch(
            workspace,
            branch,
            target.clone_url if target else None,
            _git_env(settings.github_token or None),
            prefer=settings.staging_branch or None,
        )
    except git_ops.GitOperationError as exc:
        if target is None:
            raise OrchestratorError(str(exc)) from exc
        # Could not reach the remote (offline / private without token): branch
        # from the local copy and say so; the PR's mergeability check on
        # GitHub still protects main.
        fetch_note = f" (latest main could not be fetched from {target.full_name}: {str(exc)[:160]})"
        info = git_ops.prepare_feature_branch(workspace, branch, None)
    workflow.branch_name = branch
    # PR target: the integration branch (staging) for GitHub repositories —
    # it is created from main on first publish if missing — otherwise the
    # branch the feature was cut from.
    workflow.base_branch = settings.staging_branch if (target and settings.staging_branch) else info.base_branch
    session.add(
        GitOperation(
            workflow_id=workflow_id,
            operation="branch_created",
            detail=f"{branch} from {info.base_branch}@{(info.sha or '')[:8]}"
            + (" (latest from GitHub)" if info.fetched else "")
            + (f" — {info.note}" if info.note else "")
            + fetch_note,
            ref=branch,
            approved=True,
        )
    )
    session.commit()

    # CICD Regression Gate groundwork: capture whether the PRE-change test
    # suite passes, so a post-change failure can be told apart from a
    # pre-existing failure later.
    baseline_command = workflow.test_command.strip() or "python3 -m pytest -q"
    if workflow.project_mode == "greenfield":
        # No pre-existing code means no pre-change test suite to baseline.
        workflow.baseline_tests_passed = None
    else:
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
    # Strict: the changes were generated from an earlier snapshot; if main has
    # moved under them, stop with a conflict instead of mis-applying them.
    conflicts: list[str] = []
    updated: dict[Path, str] = {}
    for change in changes:
        if not change.patch:
            continue
        path = workspace / change.file
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            updated[path] = apply_patch(old_content, change.patch, strict=True)
        except PatchConflictError as exc:
            conflicts.append(f"{change.file}: {exc}")
    if conflicts:
        reason = (
            f"Merge conflict: {info.base_branch} changed since these changes were generated ("
            + "; ".join(conflicts)
            + "). Nothing was committed and main is unchanged. Start a new workflow — it will be generated from the latest "
            + f"{info.base_branch}."
        )
        log_event(session, workflow_id, AuditEventType.WORKFLOW_FAILED, stage="codegen", message=reason)
        _set_state(session, workflow, WorkflowState.FAILED)
        raise OrchestratorError(reason)
    for path, content in updated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

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
    if workflow.project_mode in ("greenfield", "addon"):
        return _record_greenfield_tests(session, workflow, start)

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


def _record_greenfield_tests(session: Session, workflow: Workflow, start: float) -> Workflow:
    """A generated project ships with its own test suite (already applied to
    the workspace with the rest of the project); record it rather than adding
    tests written for some other codebase."""
    changes = session.exec(select(ProposedChange).where(ProposedChange.workflow_id == workflow.id)).all()
    test_changes = [c for c in changes if c.file.startswith("tests/") or Path(c.file).name.startswith("test_")]
    workspace = workspace_path(workflow.id)
    for c in test_changes:
        applied = workspace / c.file  # the file as it is after the approved changes (new or modified)
        session.add(
            GeneratedTest(
                workflow_id=workflow.id,
                file=c.file,
                content=applied.read_text(encoding="utf-8") if applied.is_file() else apply_patch("", c.patch),
                rationale="Generated with the project to cover its acceptance criteria.",
                category="happy_path",
            )
        )
    workflow.testgen_ms = int((time.monotonic() - start) * 1000)
    session.add(workflow)
    session.commit()
    log_event(
        session,
        workflow.id,
        AuditEventType.TESTS_GENERATED,
        stage="testing",
        metadata={"project_mode": "greenfield", "generated_tests": len(test_changes)},
    )
    return workflow


def run_validation(session: Session, workflow_id: str) -> Workflow:
    workflow = get_workflow(session, workflow_id)
    current_attempt = workflow.repair_attempts

    if workflow.state in (WorkflowState.TESTS_GENERATING,):
        _set_state(session, workflow, WorkflowState.VALIDATING)
    elif workflow.state == WorkflowState.REPAIRING:
        _set_state(session, workflow, WorkflowState.VALIDATING)
    elif workflow.state == WorkflowState.VALIDATION_FAILED:
        # Re-run of the same attempt: its new results replace the failed ones.
        for old in session.exec(
            select(ValidationResult).where(
                ValidationResult.workflow_id == workflow_id, ValidationResult.attempt == current_attempt
            )
        ).all():
            session.delete(old)
        session.commit()
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

    # Production stages run the app itself (fixed argv, not a shell command),
    # so only sandbox commands go through the command-safety classifier.
    validated_commands = [s.result.command for s in stages if s.result.command and not s.stage.startswith("prod_")]
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

    failed_live = [s.stage for s in stages if s.stage.startswith("prod_") and s.result.status in ("failed", "error")]
    if failed_live:
        from app.services import alerts
        from app.services.validation.production import STAGE_TITLES

        alerts.raise_alert(
            "WARNING", "validation",
            f"Production checks failed: {', '.join(STAGE_TITLES.get(s, s) for s in failed_live)}",
            f"Workflow '{workflow.intent[:120]}' did not pass its live checks, so it cannot be released. "
            "Nothing was deployed; open the workflow's Validation panel for the report.",
            workflow_id=workflow_id,
        )

    status = overall_status(stages)
    if status == "passed":
        log_event(session, workflow_id, AuditEventType.VALIDATION_PASSED, stage="validation", metadata={"attempt": current_attempt})
        for pending in session.exec(
            select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id, RepairAttempt.approved == None)  # noqa: E711
        ).all():
            pending.result = "superseded"
            session.add(pending)
        session.commit()
        _set_state(session, workflow, WorkflowState.VALIDATION_PASSED)
        _set_state(session, workflow, WorkflowState.AWAITING_COMMIT_APPROVAL)
    else:
        log_event(session, workflow_id, AuditEventType.VALIDATION_FAILED, stage="validation", metadata={"attempt": current_attempt})
        _set_state(session, workflow, WorkflowState.VALIDATION_FAILED)
    # Resilience and readiness are evaluated against the validated workspace.
    _run_follow_up(session, workflow_id, "chaos_simulation", run_chaos_simulation)
    _run_follow_up(session, workflow_id, "production_readiness", run_production_readiness)
    session.refresh(workflow)
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

    pending = session.exec(
        select(RepairAttempt).where(RepairAttempt.workflow_id == workflow_id, RepairAttempt.approved == None)  # noqa: E711
    ).first()
    if pending is not None:
        return pending

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

    workflow = run_validation(session, workflow_id)
    session.refresh(repair)
    repair.result = "passed" if workflow.state == WorkflowState.AWAITING_COMMIT_APPROVAL else "failed"
    session.add(repair)
    session.commit()
    return workflow


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
        log_event(
            session,
            workflow_id,
            AuditEventType.WORKFLOW_FAILED,
            stage="commit",
            message=f"Commit rejected by reviewer.{' ' + comment if comment else ''}",
        )
        _set_state(session, workflow, WorkflowState.FAILED)
        return workflow

    log_event(session, workflow_id, AuditEventType.COMMIT_APPROVED, stage="commit", message=comment)
    workspace = workspace_path(workflow_id)
    if not (workspace / "Dockerfile").is_file():
        raise OrchestratorError(
            "Every project must be containerized before it is committed, but this one has no Dockerfile. "
            "Intent2Deploy adds one automatically for Python (FastAPI/Flask), Node and static-site projects; for other "
            "project types add a Dockerfile to the repository, then resume or start a new workflow."
        )
    # Commit on the feature branch only — never on main.
    branch_name = workflow.branch_name or git_ops.feature_branch_name(workflow_id, workflow.intent)
    if branch_name in git_ops.protected_branches():
        raise OrchestratorError(f"Refusing to commit directly to protected branch '{branch_name}'.")
    git_ops.checkout_branch(workspace, branch_name)
    commit_info = git_ops.commit(
        workspace,
        f"{git_ops.change_title(workflow.intent)}\n\nGenerated by Intent2Deploy AI (workflow {workflow_id}).",
    )

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


_STAGE_TO_STATE = {
    "intent": "INPUT_REFUSED",
    "indexing": WorkflowState.INDEXING.value,
    "planning": WorkflowState.PLANNING.value,
    "codegen": WorkflowState.CHANGES_GENERATING.value,
    "commit": WorkflowState.AWAITING_COMMIT_APPROVAL.value,
}


def failure_point(session: Session, workflow: Workflow) -> str:
    """Where a failed workflow stopped (recorded, or inferred from its audit
    trail for workflows that failed before this was recorded)."""
    if workflow.failed_from:
        return workflow.failed_from
    from app.models.models import AuditEvent

    event = session.exec(
        select(AuditEvent)
        .where(AuditEvent.workflow_id == workflow.id, AuditEvent.event_type == AuditEventType.WORKFLOW_FAILED.value)
        .order_by(AuditEvent.timestamp.desc())
    ).first()
    return _STAGE_TO_STATE.get(event.stage, "") if event else ""


def _refresh_repository_copy(repository: Repository) -> str:
    """Re-download app-owned GitHub clones; user folders are read as they are."""
    target = github_ops.resolve_target(repository)
    local = Path(repository.local_path).resolve()
    cache = Path(settings.cloned_repos_dir).resolve()
    if target is None or cache not in local.parents:
        return "repository folder re-read"
    from app.services.repos.manager import _git_env

    git_ops.refresh_clone(local, target.clone_url, _git_env(settings.github_token or None))
    return f"re-downloaded {target.full_name}"


REVISABLE_STATES = {WorkflowState.COMMITTED, WorkflowState.CI_RUNNING, WorkflowState.COMPLETED}


class AlreadySatisfied(OrchestratorError):
    """What the report asks for is already in the code on staging."""

    def __init__(self, result, upgrades: list[dict] | None = None) -> None:  # noqa: ANN001 - revision_check.CheckResult
        self.result = result
        self.upgrades = upgrades or []  # built-in add-ons that could still be applied
        super().__init__("Everything this asks for is already in the code on staging:\n" + result.summary())


class NothingToChange(AlreadySatisfied):
    """Mock mode would rebuild exactly the code that is on staging."""

    def __init__(self, result, upgrades: list[dict] | None = None) -> None:  # noqa: ANN001 - revision_check.CheckResult
        super().__init__(result, upgrades)
        missing = [f.capability for f in result.findings if not f.present]
        self.args = ((
            "Nothing to change: rebuilding the project with this request gives exactly the code already on staging."
            + (f" Still missing: {', '.join(missing)} — that needs the live AI or a change made by hand." if missing else "")
        ),)


def _rebuild_changes_nothing(repository: Repository, intent: str, provider: LLMProvider) -> bool:
    """True when mock mode's rebuild of a generated project equals what is on staging."""
    try:
        existing = _existing_files(repository)
        port, preview = _project_port(repository)
        design = greenfield.design_project(provider, intent, existing, port, preview, revision=True).design
        result = greenfield.generate_project(provider, intent, design, existing, revise_root=Path(repository.local_path))
    except Exception:  # noqa: BLE001 - when in doubt, let the normal flow decide
        return False
    return not any(c.patch.strip() for c in result.changeset.changes)


def create_revision(
    session: Session, workflow_id: str, problem: str, provider: LLMProvider, screenshots: list[str] | None = None,
    force: bool = False, addon_ids: list[str] | None = None,
) -> Workflow:
    """A person tested the result (normally on staging) and found a problem:
    start a follow-up workflow that fixes it. It goes through the same plan ->
    approval -> changes -> validation -> PR-into-staging flow; nothing on
    staging changes until its PR is approved and merged."""
    from app.services import addons

    parent = get_workflow(session, workflow_id)
    problem = " ".join(problem.split())
    if not problem and addon_ids:
        problem = "Add: " + ", ".join(addons.catalog.BY_ID[a].title for a in addon_ids if a in addons.catalog.BY_ID)
    if len(problem) < 5:
        raise OrchestratorError("Describe the problem in a few words so it can be fixed.")
    if len(problem) > 2000:
        raise OrchestratorError("Keep the problem description under 2000 characters.")
    from app.services import attachments

    try:
        images = attachments.decode(screenshots or [])  # every image is checked before anything is created
    except attachments.AttachmentError as exc:
        raise OrchestratorError(str(exc)) from exc
    if parent.state not in REVISABLE_STATES:
        raise OrchestratorError(
            f"This workflow is {parent.state.value}; problems can be reported once its changes are committed."
        )
    repository = session.get(Repository, parent.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")
    try:
        refreshed = _refresh_repository_copy(repository)  # build the fix on the latest staging
    except git_ops.GitOperationError as exc:
        raise OrchestratorError(f"Could not download the latest code to revise: {exc}") from exc

    # Built-in add-ons: asked for by id (a button) or recognised in the description.
    available = {s["id"]: s for s in addons.statuses(Path(repository.local_path))}
    if addon_ids:
        unknown = [a for a in addon_ids if a not in available]
        if unknown:
            raise OrchestratorError(f"Unknown add-on(s): {', '.join(unknown)}.")
        not_ready = [f"{available[a]['title']} ({available[a]['status'].replace('_', ' ')})"
                     for a in addon_ids if available[a]["status"] != "available"]
        if not_ready:
            raise OrchestratorError(f"Can't apply: {'; '.join(not_ready)}.")
        chosen = list(dict.fromkeys(addon_ids))
    else:
        chosen = [a for a in addons.matching(problem) if available[a]["status"] == "available"]

    if not force and not chosen:
        from app.services import revision_check

        result = revision_check.check(Path(repository.local_path), problem)
        if result.already_satisfied:
            log_event(session, parent.id, AuditEventType.REVISION_REQUESTED, stage="report",
                      message=f"Problem reported: {problem} — already satisfied by the code on staging",
                      metadata={"findings": result.summary()})
            raise AlreadySatisfied(result, [s for s in available.values() if s["status"] == "available"])

    root_intent = parent.intent.split("\n\nFix requested after testing on staging:")[0].strip()
    intent = f"{root_intent}\n\nFix requested after testing on staging: {problem}"

    # Mock mode rebuilds a generated project from its templates, which is
    # deterministic: find out now whether that would change anything, instead
    # of creating a fix workflow that can only end in "nothing to change".
    available_upgrades = [s for s in available.values() if s["status"] == "available"]
    if not chosen and provider.is_mock and parent.project_mode == "greenfield" and _rebuild_changes_nothing(
        repository, intent, provider
    ):
        from app.services import revision_check

        result = revision_check.check(Path(repository.local_path), problem)
        log_event(session, parent.id, AuditEventType.REVISION_REQUESTED, stage="report",
                  message=f"Problem reported: {problem} — rebuilding gives the code already on staging",
                  metadata={"findings": result.summary()})
        raise NothingToChange(result, available_upgrades)

    revision = create_workflow(
        session, parent.project_id, parent.repository_id, intent, parent.base_branch,
        parent.test_command, parent.build_command, parent.environment.value,
    )
    revision.revision_of, revision.revision_note = parent.id, problem
    revision.revision_addons = json.dumps(chosen)
    if images:
        revision.revision_attachments = json.dumps(attachments.save(revision.id, images))
    session.add(revision)
    session.commit()
    log_event(session, parent.id, AuditEventType.REVISION_REQUESTED, stage="report",
              message=f"Problem reported: {problem}", metadata={"revision_id": revision.id, "repository": refreshed})
    log_event(session, revision.id, AuditEventType.REVISION_REQUESTED, stage="intent",
              message=f"Revision of workflow {parent.id}: {problem}",
              metadata={"revision_of": parent.id, "screenshots": len(images), "addons": chosen})
    if revision.state == WorkflowState.FAILED:  # the input guardrails refused the description
        return revision
    run_indexing(session, revision.id)
    run_planning(session, revision.id, provider)
    session.refresh(revision)
    return revision


def list_revisions(session: Session, workflow_id: str) -> list[Workflow]:
    return list(session.exec(
        select(Workflow).where(Workflow.revision_of == workflow_id).order_by(Workflow.created_at.desc())
    ).all())


def resume_workflow(session: Session, workflow_id: str, provider: LLMProvider) -> Workflow:
    """Continue a failed workflow from the step that failed, after the cause
    was fixed. An explicit, audited human action: FAILED stays terminal for
    the normal state machine.

    - Commit rejected -> back to commit approval.
    - Anything else -> the repository is refreshed and re-indexed first (the
      fix is often there: branches deleted, code pushed). If the repository
      changed kind (e.g. now empty) or the failure was during indexing/
      planning or a conflict while applying changes, a fresh plan is
      prepared for approval; otherwise the already-approved plan is kept and
      code generation is retried.
    """
    workflow = get_workflow(session, workflow_id)
    if workflow.state != WorkflowState.FAILED:
        raise OrchestratorError("Only a failed workflow can be resumed.")
    point = failure_point(session, workflow)
    if point == "NO_CHANGES":
        # A revision mock mode couldn't make. With a live model it can: a fresh
        # plan that edits the existing code (indexing picks that mode).
        if settings.is_mock:
            raise OrchestratorError(
                "Resuming would rebuild the same files again: mock mode can't make this change. Set LLM_MODE=live with "
                "an API key in .env, restart the backend, then resume — the AI will then edit the code on staging."
            )
        point = WorkflowState.PLANNING.value
    if point in ("INPUT_REFUSED", ""):
        raise OrchestratorError(
            "This workflow can't be resumed: the request itself was refused by a guardrail (or where it stopped is "
            "unknown). Start a new workflow with a different request."
        )
    repository = session.get(Repository, workflow.repository_id)
    if repository is None:
        raise OrchestratorError("Repository not found.")

    def _enter(state: WorkflowState, detail: str) -> None:
        workflow.state = state
        workflow.failed_from = ""
        session.add(workflow)
        session.commit()
        log_event(session, workflow_id, AuditEventType.WORKFLOW_RESUMED, stage="resume",
                  message=f"Resumed from {point}: {detail}")

    if point == WorkflowState.AWAITING_COMMIT_APPROVAL.value:
        _enter(WorkflowState.AWAITING_COMMIT_APPROVAL, "back to commit approval")
        return workflow

    try:
        refreshed = _refresh_repository_copy(repository)
    except git_ops.GitOperationError as exc:
        raise OrchestratorError(f"Could not refresh the repository before resuming: {exc}") from exc
    old_mode = workflow.project_mode
    _enter(WorkflowState.CREATED, f"{refreshed}; re-indexing")
    workflow = run_indexing(session, workflow_id)  # fails clearly again if indexing is still broken

    plan_row = session.exec(select(Plan).where(Plan.workflow_id == workflow_id).order_by(Plan.created_at.desc())).first()
    needs_new_plan = (
        point in (WorkflowState.INDEXING.value, WorkflowState.PLANNING.value, WorkflowState.AWAITING_CHANGE_APPROVAL.value)
        or workflow.project_mode != old_mode
        or plan_row is None
        or plan_row.approved is not True
    )
    if needs_new_plan:
        # Plan must match the repository as it is now; it comes back for approval.
        return run_planning(session, workflow_id, provider)

    workflow.state = WorkflowState.CHANGES_GENERATING
    session.add(workflow)
    session.commit()
    log_event(session, workflow_id, AuditEventType.WORKFLOW_RESUMED, stage="resume",
              message="Approved plan kept; retrying code generation.")
    return run_codegen(session, workflow_id, provider)


def _project_port(repository: Repository) -> tuple[int, bool]:
    """Where a project runs: for GitHub repositories, the port its staging
    preview uses (stable per repository); otherwise the default 8010."""
    from app.services import preview
    from app.services.containerize import HOST_PORT

    target = github_ops.resolve_target(repository)
    if target is None or not settings.staging_branch:
        return HOST_PORT, False
    return preview.preferred_port(f"{target.full_name}@{settings.staging_branch}"), True


def _docker_plan_files(repository: Repository) -> dict[str, str] | None:
    """Docker files to add to a repository that has no Dockerfile: None if it
    already has one, {} if its type can't be containerized automatically."""
    from app.services import containerize

    files = containerize.read_project_files(Path(repository.local_path))
    if containerize.has_dockerfile(files):
        return None
    spec = containerize.detect(files)
    if spec is None:
        return {}
    port, preview = _project_port(repository)
    return containerize.docker_files(spec, files, repository.name or Path(repository.local_path).name, port, preview)


def _add_containerization_to_plan(repository: Repository, plan) -> None:
    from app.schemas.plan import PlanStep

    docker = _docker_plan_files(repository)
    if docker is None:
        return
    if not docker:
        plan.risks.append(
            "The project has no Dockerfile and its type isn't recognised for automatic containerization; "
            "a Dockerfile must be added before the change can be committed."
        )
        return
    paths = sorted(docker)
    plan.steps.append(PlanStep(
        id=f"S{len(plan.steps) + 1}",
        description="Containerize the project: add a Dockerfile, .dockerignore, docker-compose.yml, a CI workflow "
        "that builds the image and health-checks the container, and Docker build/run instructions in the README.",
        files=paths,
    ))
    plan.files_likely_to_change += [p for p in paths if p not in plan.files_likely_to_change]


def _append_docker_changes(repository: Repository, changes: list) -> None:
    from app.schemas.change import ProposedChangeItem

    docker = _docker_plan_files(repository)
    if not docker:
        return
    root = Path(repository.local_path)
    already = {c.file for c in changes}
    for path, text in docker.items():
        if path in already:
            continue
        current = root / path
        if current.is_file():
            old = current.read_text(encoding="utf-8", errors="ignore")
            patch, op = make_unified_diff(path, old, text), "modify"
        else:
            patch, op = make_new_file_diff(path, text), "create"
        changes.append(ProposedChangeItem(file=path, operation=op, reason="Containerization (Docker).", patch=patch,
                                          confidence=0.8, risks=[], acceptance_criterion=""))


def delete_workflow(session: Session, workflow_id: str) -> dict:
    """Permanently remove a workflow: its history rows (plan, changes, tests,
    validation, guardrails, audit events, ...) and its local workspace folder.
    Never touches the user's repository or anything already on GitHub."""
    from sqlalchemy import delete as sa_delete
    from sqlmodel import SQLModel

    from app.services.validation.sandbox import _force_rmtree

    workflow = get_workflow(session, workflow_id)  # error if unknown

    # Folder first: if an app is still running from it (files locked on
    # Windows), stop here rather than leave history half-deleted.
    workspace = workspace_path(workflow_id)
    workspace_removed = workspace.exists()
    if workspace_removed:
        try:
            _force_rmtree(workspace)
        except OSError as exc:
            raise OrchestratorError(
                f"Could not delete the workspace folder {workspace}: it is in use ({exc.strerror or exc}). "
                "Stop any app or terminal running from that folder (Ctrl+C), then delete again."
            ) from exc

    removed_rows = 0
    for table in SQLModel.metadata.sorted_tables:
        if table.name != "workflow" and "workflow_id" in table.columns:
            removed_rows += session.execute(sa_delete(table).where(table.c.workflow_id == workflow_id)).rowcount or 0
    session.delete(workflow)
    session.commit()
    from app.services import attachments

    attachments.remove_all(workflow_id)  # screenshots of a problem report
    return {"deleted": workflow_id, "records_removed": removed_rows, "workspace_removed": workspace_removed}


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


def _run_follow_up(session: Session, workflow_id: str, name: str, fn) -> None:
    """Run an analysis stage that follows a lifecycle step automatically.

    These stages (risk analysis, chaos simulation, readiness) never change the
    workflow state, so a failure must not undo the step that just succeeded;
    it is recorded in the audit trail instead, and the stage can be re-run
    through its own endpoint."""
    try:
        fn(session, workflow_id)
    except Exception as exc:  # recorded, not swallowed silently
        session.rollback()
        log_event(session, workflow_id, AuditEventType.AUTO_ANALYSIS_FAILED, stage=name, message=str(exc)[:500])


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

    # A failure whose evidence lies entirely in files this change does not
    # touch is a pre-existing weakness of the repository, not a regression
    # introduced by this change: keep it visible, but don't attribute it.
    touched = {f.replace("\\", "/") for f in changed_files}
    for o in outcomes:
        if o.result == "FAILED" and o.evidence and not touched.intersection(e.replace("\\", "/") for e in o.evidence):
            o.result = "PRE_EXISTING"
            o.observed_behavior = f"Pre-existing in code this change does not touch: {o.observed_behavior}"

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


def _container_status(session: Session, workflow_id: str) -> str:
    workspace = workspace_path(workflow_id)
    if not workspace.exists():
        return "NOT_APPLICABLE"
    if not (workspace / "Dockerfile").is_file():
        return "MISSING"
    build = session.exec(
        select(ValidationResult)
        .where(ValidationResult.workflow_id == workflow_id, ValidationResult.stage == "docker_build")
        .order_by(ValidationResult.timestamp.desc())
    ).first()
    if build is None:
        return "SKIPPED"
    return {"passed": "PASSED", "skipped": "SKIPPED"}.get(build.status, "FAILED")


def _production_status(results: list[ValidationResult]) -> str:
    """PASSED / FAILED / SKIPPED for the live production stages of one attempt."""
    prod = [r for r in results if r.stage.startswith("prod_")]
    if not prod:
        return "NOT_APPLICABLE"
    if any(r.status in ("failed", "error") for r in prod):
        return "FAILED"
    return "SKIPPED" if all(r.status == "skipped" for r in prod) else "PASSED"


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
        production_status = _production_status(latest)
    else:
        production_status = "NOT_APPLICABLE"

    guardrail_checks = session.exec(select(GuardrailCheck).where(GuardrailCheck.workflow_id == workflow_id)).all()
    # A guardrail re-evaluated later (e.g. validation re-run after a broken
    # environment was fixed) supersedes its earlier result at that checkpoint.
    latest_checks: dict[tuple[str, str], GuardrailCheck] = {}
    for c in sorted(guardrail_checks, key=lambda c: c.evaluated_at):
        latest_checks[(c.guardrail_id, c.enforcement_point)] = c
    current_checks = list(latest_checks.values())
    blocked_names = sorted({c.name for c in current_checks if c.status == GuardrailStatus.BLOCKED.value})
    warning_names = sorted({c.name for c in current_checks if c.status == GuardrailStatus.WARNING.value})

    risks = session.exec(select(RiskItem).where(RiskItem.workflow_id == workflow_id)).all()
    open_critical = sum(1 for r in risks if r.severity == Severity.CRITICAL.value and r.status == "OPEN")
    open_high = sum(1 for r in risks if r.severity == Severity.HIGH.value and r.status == "OPEN")

    chaos_rows = session.exec(select(ChaosExperiment).where(ChaosExperiment.workflow_id == workflow_id)).all()
    applicable_chaos = [c for c in chaos_rows if c.result not in ("NOT_APPLICABLE", "PRE_EXISTING")]
    preexisting_chaos = sum(1 for c in chaos_rows if c.result == "PRE_EXISTING")
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
            preexisting_chaos_failures=preexisting_chaos,
            container_status=_container_status(session, workflow_id),
            production_status=production_status,
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
