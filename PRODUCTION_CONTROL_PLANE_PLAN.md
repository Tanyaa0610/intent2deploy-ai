# Production Control Plane Upgrade — Implementation Plan

This document is required by the upgrade spec (Part X) before touching code. It
records what already existed, what is being added, and in what order.

## 1. Current capabilities (before this upgrade)

Backend (FastAPI + SQLModel + SQLite, `backend/app`):

- Real workflow state machine (`services/state_machine.py`, `models/enums.py`) with
  explicit allowed transitions from `CREATED` through `COMPLETED`/`FAILED`.
- Real RAG pipeline: chunking, Chroma vector store, hybrid retrieval
  (`services/rag/*`), used to ground planning — the planner strips any file the
  LLM references that was not actually retrieved (`services/planner/planner.py`),
  which is already a primitive evidence gate.
- LLM provider abstraction (`services/providers/*`) with a real Anthropic/OpenAI
  provider and a deterministic `LocalProvider` for `LLM_MODE=mock` demo mode.
- Codegen with hard `MAX_FILES_CHANGED` / `MAX_PATCH_LINES` enforcement
  (`services/codegen/codegen.py`).
- Sandbox execution with a command allowlist and dangerous-token rejection
  (`core/security.py`, `services/validation/sandbox.py`) — no LLM-generated shell
  command ever runs unvalidated.
- Secret-pattern scanner (`core/security.py: scan_for_secrets/strip_potential_secrets`),
  not yet wired into every choke point.
- Validation pipeline (syntax/lint/tests/build/security via `ruff --select S`),
  bounded repair loop (`MAX_REPAIR_ATTEMPTS`), Git/GitHub operations gated behind
  explicit `approved` flags end-to-end, audit trail (`AuditEvent`), a real
  evaluation harness with 10 benchmark tasks and a results directory that the
  dashboard reads verbatim (never fabricates numbers).
- Frontend (React + Vite): Dashboard, New Workflow, Workflow Detail (tabs: Plan,
  Repository Intelligence, Changes, Tests, CI/CD, Report), Evaluation page.

What's missing relative to this upgrade: guardrails are scattered as ad-hoc
limits, not a named, auditable, uniformly-modeled engine; no risk model; no
chaos/resilience simulation; no production-readiness decision; no production
environment concept; no guardrail/risk/resilience dashboards; no dedicated
Code Review / CI-CD / Architecture / Simulation pages.

## 2. Design decision: additive, not a rewrite

The existing `WorkflowState` enum and its transition table are exercised by
existing tests (`tests/unit/test_state_machine.py`,
`tests/integration/test_orchestrator_e2e.py`) and the evaluation harness. Rather
than expanding the enum with 10+ new states (Architecture Analysis, Risk
Analysis, Resilience Testing, Chaos Simulation, Production Readiness — none of
which gate a state *transition*, they gate *information*), this upgrade adds
them as **data-driven virtual pipeline stages**: new tables populated by new
engines, exposed through `/api/workflows/{id}/pipeline`, which the frontend
renders as the full 19-stage visualization. This keeps the state machine's
proven transition guarantees intact while satisfying the spec's pipeline
requirement.

## 3. Guardrail engine (`services/guardrails/engine.py`) — REWORKED

> **2026-09-23 rework:** the original flat 18-guardrail (G01-G18) design
> described below in the initial plan was **fully replaced**, not layered
> on top of. See `AI_DEVOPS_GUARDRAILS.md` for the authoritative current
> reference. Summary of the current architecture:
>
> Every guardrail belongs to exactly one of **8 categories** — `SECURITY`,
> `INFRASTRUCTURE`, `CI_CD`, `DEPLOYMENT`, `COST`, `AI_LLM`, `INPUT`,
> `OUTPUT` — and is a pure function returning a `GuardrailCheckResult`
> (`guardrail_id`, `category`, `name`, `description`, `purpose`,
> `trigger_condition`, `enforcement_point`, `severity`, `status`, `action`,
> `evidence`, `remediation`, `configurable_threshold`, `enabled`).
> Persistence moved from `GuardrailEvent` to `GuardrailCheck` (old table
> dropped on startup, not kept in parallel). Statuses are
> `PASSED/WARNING/BLOCKED/FAILED/NOT_APPLICABLE/NOT_IMPLEMENTED`; actions
> are `ALLOW/WARN/REQUIRE_APPROVAL/BLOCK/ABORT`. `enforce()` raises
> `GuardrailBlockedError` when a result's action is `BLOCK`/`ABORT`, which
> orchestrator call sites convert into an explanatory `OrchestratorError`.
> The catalog holds 64 definitions across the 8 categories (`GET
> /api/guardrails`); several concepts are deliberately evaluated under more
> than one category id where the spec itself lists them twice (e.g. secret
> detection is both `SEC-01` and `OUTPUT-03`; the repair-loop budget is
> both `COST-03` and `AI-08`) — this is intentional overlap, not a
> duplicate engine. Checks with no honest way to evaluate in this
> repository (live CVE/dependency-vulnerability lookup, deep
> auth/TLS/rate-limit analysis) are marked `NOT_IMPLEMENTED` in their
> remediation text rather than faked.

## 4. Risk engine (`services/risk/engine.py`)

Deterministic, evidence-based (not invented): combines the LLM plan's own
`risks` list, the intent category's known risk metadata
(`services/planner/category_metadata.py`), and static signals from the
proposed changes (which files touch auth/payment/db-shaped paths) into
`RiskItem` rows with severity/likelihood/blast radius/detection/mitigation/
validation method/status. No risk is invented that isn't traceable to one of
those three evidence sources.

## 5. Resilience / Chaos engine (`services/chaos/engine.py`) + Production
   Simulation (`services/simulation/engine.py`)

The chaos engine only runs experiments relevant to the architecture actually
detected in the target repository (e.g. "Dependency unavailable" only if an
external-service client exists). Each experiment inspects real source for a
resilience signal (timeout config, retry/backoff, idempotency key, try/except
around the dependency call) rather than executing real fault injection against
a live system — this is explicitly a **simulation**, labeled as such, per
Guardrail 11. The Production Simulation engine holds an in-memory simulated
service graph (api/db/payment/cache/worker/queue/monitoring) with inject/
restore endpoints for the demo UI; it never touches the real demo repository
process.

## 6. Production readiness gate (`services/readiness/engine.py`)

Composite decision over: validation status, regression gate, CI gate, blocking
guardrails, open CRITICAL/HIGH risks, chaos pass rate, rollback presence →
`READY` / `READY_WITH_WARNINGS` / `NOT_READY`, each with an explicit reasons list
(never a bare label).

## 7. New database models

`GuardrailCheck` (see §3 — replaces the retired `GuardrailEvent`), `RiskItem`,
`ChaosExperiment`, `ProductionReadinessAssessment`, plus `Workflow.environment`
(default `sandbox`), `Workflow.baseline_tests_passed`, and
`Workflow.llm_call_count`/`llm_estimated_tokens`/`llm_estimated_cost_usd` (Cost
category tracking — real per-call estimates from actual prompt/response text
length, never fabricated numbers). All under `backend/app/models/models.py`;
new enums under `backend/app/models/enums.py`.

## 8. New API surface

`app/api/guardrails.py` (`GET /api/guardrails`, `GET /api/guardrails/{workflow_id}`
with category/severity/status/checkpoint filters, `/summary`, `/timeline`,
`POST /evaluate`, `POST /approve`), `app/api/risks.py`, `app/api/simulation.py`,
`app/api/dashboard.py`; new endpoints under `app/api/workflows.py` for
pipeline/readiness/architecture/risk-analysis/chaos-run. All read real
persisted data; empty states return `"No data yet"`, never fabricated numbers.

## 9. Frontend

New pages under the Part O sidebar: Workflows, Repository Intelligence,
Architecture, Risks, Guardrails & Safety, Resilience Lab, Production
Simulation, Code Review, Tests & Validation, CI/CD, Reports — reusing the
existing card/grid/table/badge/tab CSS system for visual consistency. Dashboard
home gains the pipeline visualization and the 8 KPI cards (Part A1), each
falling back to "No data yet" rather than 0%.

## 10. Testing strategy

New unit tests per guardrail (`tests/unit/test_guardrails.py`), risk engine,
chaos engine, readiness engine; a new integration test exercising the Part N
payment-timeout scenario end-to-end. Existing tests must keep passing
unmodified — the state machine and orchestrator public functions are extended,
not changed, wherever avoidable.

## 11. Implementation order

Guardrail engine → production context/environment → risk engine → dashboard
backend APIs → dashboard frontend → chaos/resilience engine → production
readiness gate → CI/CD surfacing → evaluation enrichment → documentation →
end-to-end verification (`pytest`, `npm run build`, manual run).

## 12. Known scope limits (stated up front, not discovered at the end)

- Chaos/resilience "experiments" are static-analysis-based simulations of
  failure handling, not live fault injection against a running process — there
  is no live target service to inject faults into in this repo, and doing so
  against real infrastructure is exactly what Guardrail 02/11 forbid.
  Production Simulation's inject/restore buttons mutate an in-memory simulated
  service graph for demo purposes.
- API-compatibility and configuration-safety gates use heuristic pattern
  matching over patches, not a full OpenAPI diff — documented as such in
  `AI_DEVOPS_GUARDRAILS.md`.
- GitHub Actions CI stays `NOT_CONFIGURED` unless real `GITHUB_TOKEN`/owner/repo
  are set, exactly as before — never faked.
