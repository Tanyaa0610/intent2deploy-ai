# AI-DevOps Guardrails

Intent2Deploy AI's guardrail system is a **Guardrail Control Plane**: every
safety/policy check the system performs belongs to exactly one of **8
categories**, is evaluated by a pure function in
`backend/app/services/guardrails/engine.py`, and is persisted as a
`GuardrailCheck` row (`backend/app/models/models.py`) — one row per
evaluation, whether it passed or blocked, so the audit trail always shows
what was actually checked.

This is the **only** guardrail engine in the system. An earlier flat
18-guardrail (G01–G18) design was fully replaced on 2026-09-23, not kept
running in parallel — see `PRODUCTION_CONTROL_PLANE_PLAN.md` §3 for the
migration record.

## Data model

Every guardrail check carries:

| Field | Meaning |
|---|---|
| `guardrail_id` | Stable id, e.g. `SEC-01`, `CICD-07`, `AI-05` |
| `category` | One of the 8 categories below |
| `name` | Human-readable name |
| `description` / `purpose` | What it checks and why |
| `trigger_condition` | The specific input that produced this result |
| `enforcement_point` | Which orchestrator checkpoint ran it (e.g. `codegen`, `validation`, `workflow_creation`) |
| `severity` | `LOW / MEDIUM / HIGH / CRITICAL` |
| `status` | `PASSED / WARNING / BLOCKED / FAILED / NOT_APPLICABLE / NOT_IMPLEMENTED` |
| `action` | `ALLOW / WARN / REQUIRE_APPROVAL / BLOCK / ABORT` |
| `evidence` | List of concrete findings (file names, matched patterns, counts) |
| `remediation` | What a human should do about it |
| `configurable_threshold` | The active limit, if any (e.g. `max_files_changed=15`) |

A result with `action` in `{BLOCK, ABORT}` causes `guardrails.enforce()` to
raise `GuardrailBlockedError`, which the orchestrator turns into an
`OrchestratorError` naming the guardrail, the reason, and the recovery
action — never a silent no-op or a generic "Failed". Results with any other
action are still persisted via `guardrails.record()`, just without halting
execution — this is how the system stays auditable even on the happy path.

Where a check cannot be honestly evaluated with this repository's tooling
(live CVE/dependency-vulnerability lookup needs network access to a package
index this environment doesn't have; deep TLS/rate-limit/auth analysis needs
a running request path that doesn't exist here), its remediation text says
so explicitly (`NOT_IMPLEMENTED in this build`) instead of reporting a
fabricated `PASSED`.

## Execution model

```
INPUT
  ↓
Input Guardrails            (workflow creation)
  ↓
Intent Analysis / Repository RAG
  ↓
AI/LLM Guardrails           (planning: prompt injection, context boundary,
  ↓                          model usage, evidence gate, cost tracking)
Architecture + Risk
  ↓
Output Guardrails           (plan)
  ↓
Approval
  ↓
Code Generation
  ↓
Output + Security Guardrails (codegen: scope, secrets, code security,
  ↓                           container security, API compat, migration,
  ↓                           infra change, blast radius, policy compliance)
Tests
  ↓
CI/CD Guardrails            (validation: test/build/security/failure/evidence gates)
  ↓
Infrastructure Validation
  ↓
Deployment Guardrails       (approve_changes/commit/push/pr: environment,
  ↓                          production block, approval, rollback, evidence)
Production Simulation       (chaos: environment isolation re-checked)
  ↓
Cost + Reliability + Security Checks
  ↓
Final Output Guardrails
  ↓
Production Readiness        (separate composite decision, not itself one
                              of the 8 categories — see Part K)
```

## 1. SECURITY

| ID | Name | What it does |
|---|---|---|
| SEC-01 | Secret Detection | Scans for API keys, tokens, passwords, private keys, credentials, connection strings before they reach the LLM, logs, Git, GitHub, reports, generated code, or the frontend. BLOCKs on a match. |
| SEC-02 | Dependency Security | Flags dependency-manifest changes (`requirements.txt`, `package.json`, ...) for review. Live CVE/vulnerability lookup is `NOT_IMPLEMENTED` (no package-index network access in this environment) — only the manifest-touch detection is real. |
| SEC-03 | Code Security | Static pattern scan for command injection, SQL injection, unsafe subprocess (`shell=True`), path traversal, unsafe deserialization (`pickle.loads`, unsafe `yaml.load`), `eval`/`exec`, and naive password comparison. BLOCKs on a match. |
| SEC-04 | Container Security | Scans any `Dockerfile*` in the repository for missing non-root `USER`, `--privileged`, and `:latest` base-image tags. `NOT_APPLICABLE` if no Dockerfile exists. |
| SEC-05 | Security Configuration | Scans for a wildcarded CORS `allow_origins=["*"]`. Deeper auth/authz/TLS/rate-limit analysis is `NOT_IMPLEMENTED` (no live request path to test against). |

## 2. INFRASTRUCTURE

| ID | Name | What it does |
|---|---|---|
| INFRA-01 | Infrastructure Change Detection | Detects touched Dockerfiles, Compose files, Kubernetes manifests, Terraform, or CI workflow files. |
| INFRA-02 | Infrastructure Dependency Check | Reverse-import-graph lookup: which files depend on what's being changed. |
| INFRA-03 | Resource Limit Check | Requires `resources`/`limits`/`cpus` keys in touched Compose/K8s manifests. |
| INFRA-04 | Environment Isolation | Never allows `environment=production`; only `local/sandbox/test/staging/production-simulation` are permitted. |
| INFRA-05 | Configuration Drift Warning | Flags `.env`/YAML/TOML/settings-module changes that may diverge from deployed configuration. |
| INFRA-06 | Infrastructure Blast Radius | Counts affected files + modules + reverse-import dependents; `REQUIRE_APPROVAL` above `MAX_BLAST_RADIUS_FILES`. |

## 3. CI/CD

| ID | Name | What it does |
|---|---|---|
| CICD-01 | Test Gate | Required stages (lint, unit tests) must be present and passed. |
| CICD-02 | Regression Gate | Compares the pre-change baseline test run to the post-change run — a workflow is never "successful" merely because new tests pass. |
| CICD-03 | Build Gate | The configured build command must succeed, if one is configured. |
| CICD-04 | Security Scan Gate | Ruff's bandit-derived `S` rule set; findings BLOCK. |
| CICD-05 | Pipeline Integrity | Detects a generated change removing a `pytest`/`ruff`/`- run:` line from a `.github/workflows/*.yml` file — an AI agent must never disable its own safety net. |
| CICD-06 | CI Configuration Protection | Any `.github/workflows/**` change requires approval. |
| CICD-07 | Failure Gate | Any failed required stage blocks deployment/readiness. |
| CICD-08 | Evidence Gate | Verifies validation stages carry real command/duration/exit-code evidence — a CI result is never fabricated. |

## 4. DEPLOYMENT

| ID | Name | What it does |
|---|---|---|
| DEPLOY-01 | Environment Verification | The target environment must be one of the recognized values. |
| DEPLOY-02 | Production Block | Real production is always BLOCKED by default. |
| DEPLOY-03 | Deployment Approval | Commit/push/PR actions require an explicit human decision. |
| DEPLOY-04 | Rollback Requirement | HIGH/CRITICAL-risk changes need a documented rollback method — BLOCK for CRITICAL with none, WARNING for HIGH. |
| DEPLOY-05 | Health Check Gate | Warns if no `/health` or `/healthz` route is detected in the repository. |
| DEPLOY-06 | Migration Safety | Any migration-shaped file change requires a preview, affected-tables list, data-loss assessment, and approval. |
| DEPLOY-07 | Deployment Scope | Only approved-plan files may be part of what's committed/deployed. |
| DEPLOY-08 | Deployment Evidence | Records environment, commit hash, branch, and health status for every commit. |

## 5. COST

Token/dollar figures are **estimates** derived from real prompt/response
text length (`chars // 4`), clearly labeled as such — mock mode has no
provider billing API to read exact usage from.

| ID | Name | What it does |
|---|---|---|
| COST-01 | LLM Token Limit | Warns above `MAX_LLM_ESTIMATED_TOKENS_PER_WORKFLOW`. |
| COST-02 | LLM Call Limit | Warns above `MAX_LLM_CALLS_PER_WORKFLOW`. |
| COST-03 | Repair Loop Cost Limit | Shares logic with AI-08 — BLOCKs at `MAX_REPAIR_ATTEMPTS`. |
| COST-04 | Model Escalation Guard | Flags a mid-workflow model change. |
| COST-05 | Infrastructure Cost Warning | Flags a large replica/instance-count bump in touched infra files. |
| COST-06 | CI Cost Awareness | Flags an unusually high number of validation re-runs. |
| COST-07 | Workflow Budget | `REQUIRE_APPROVAL` above `WORKFLOW_COST_BUDGET_USD`; `WARN` near it. |

## 6. AI / LLM

| ID | Name | What it does |
|---|---|---|
| AI-01 | Prompt Injection Detection | Scans retrieved repository content for instruction-hijacking language ("ignore previous instructions", "you are now", ...) — repository content is DATA, never instructions. BLOCKs on a match. |
| AI-02 | Hallucination / Evidence Guard | Surfaces the planner's invented-files-removed list and unstated-risk claims as `UNVERIFIED`, never silently promoted to fact. |
| AI-03 | Model Output Validation | Confirms structured LLM output parsed against its Pydantic schema. |
| AI-04 | Tool Permission Control | Invariant check: every executed sandbox command must have passed AI-05 classification first. |
| AI-05 | Command Safety Classification | `SAFE / REVIEW_REQUIRED / BLOCKED` for every sandbox command, independent of the sandbox's own allowlist (defense in depth). |
| AI-06 | Context Boundary | Secrets must never enter an LLM prompt — scans the actual rendered context. |
| AI-07 | Model Usage Control | Records provider, model, prompt version, call count, and estimated tokens for every LLM interaction. |
| AI-08 | Retry/Repair Limit | Shares logic with COST-03. |
| AI-09 | AI Confidence / Evidence Level | Flags low-confidence generated changes (confidence is read from the model's own structured output, never invented). |

## 7. INPUT

Runs once, at workflow creation, **before** indexing/planning starts.
`classify_input()` always returns all 8 checks plus an overall
classification: `VALID / NEEDS_CLARIFICATION / UNSAFE / BLOCKED`.

| ID | Name |
|---|---|
| INPUT-01 | Input Size |
| INPUT-02 | Malformed Request |
| INPUT-03 | Prompt Injection |
| INPUT-04 | Dangerous Instructions ("delete the production database", "drop table", `rm -rf`, ...) |
| INPUT-05 | Production Access Request ("deploy this directly to production") |
| INPUT-06 | Secrets In Input |
| INPUT-07 | Ambiguous Requirements (very short request, or explicit uncertainty markers) |
| INPUT-08 | Unsafe Commands Referenced |

A `BLOCKED`/`UNSAFE` classification refuses workflow creation outright,
with the specific triggering check(s) named in the error. A
`NEEDS_CLARIFICATION` classification lets the workflow proceed with the
concern recorded and visible on the dashboard.

## 8. OUTPUT

Validates every important AI-generated output before it reaches the next
stage. Several of these deliberately reuse the same underlying logic as a
SECURITY/CI_CD/AI_LLM check, recorded under a distinct id — that mirrors the
spec's own category overlaps, not a duplicate implementation.

| ID | Name |
|---|---|
| OUTPUT-01 | Schema Validation |
| OUTPUT-02 | Security Validation (= SEC-03 applied to generated code) |
| OUTPUT-03 | Secret Detection (= SEC-01 applied to generated output) |
| OUTPUT-04 | Unsafe Command Detection (embedded `os.system`/`subprocess(shell=True)` in generated code) |
| OUTPUT-05 | Scope Validation (file/line limits + unrelated-file scope, merged) |
| OUTPUT-06 | Dependency Change Detection |
| OUTPUT-07 | Infrastructure Change Detection |
| OUTPUT-08 | API Compatibility Check (removed/changed route handlers) |
| OUTPUT-09 | Database Migration Check |
| OUTPUT-10 | Test Coverage / Regression Check |
| OUTPUT-11 | Evidence & Hallucination Validation |
| OUTPUT-12 | Policy Compliance (composite over the other OUTPUT-xx results for this batch) |
| OUTPUT-13 | Production Safety Check |

## Production Readiness — not a 9th category

The final `READY / READY_WITH_WARNINGS / NOT_READY` decision
(`services/readiness/engine.py`) is a separate, terminal composite over
validation status, blocked/warning guardrails, open risk severity, chaos
pass rate, rollback posture, and cost status. It is **not** one of the 8
guardrail categories and is persisted as its own
`ProductionReadinessAssessment` row, not as an additional `GuardrailCheck`.

## API

- `GET /api/guardrails` — the full 64-entry catalog (optionally `?category=`)
- `GET /api/guardrails/{workflow_id}` — this workflow's checks, filterable by `category`, `severity`, `status`, `checkpoint`
- `GET /api/guardrails/{workflow_id}/summary` — 8 category cards (total/passed/warnings/blocked/failed)
- `GET /api/guardrails/{workflow_id}/timeline` — chronological execution timeline
- `POST /api/guardrails/{workflow_id}/evaluate` — re-evaluate the checks whose inputs are current workflow state (environment, cost, repair budget) on demand
- `POST /api/guardrails/{workflow_id}/approve` — approve or decline a `REQUIRE_APPROVAL` check by id

## Testing

Every category has a dedicated test file under `backend/tests/unit/`:
`test_guardrails_security.py`, `test_guardrails_infrastructure.py`,
`test_guardrails_cicd.py`, `test_guardrails_deployment.py`,
`test_guardrails_cost.py`, `test_guardrails_ai_llm.py`,
`test_guardrails_input.py`, `test_guardrails_output.py`, plus
`test_guardrails_catalog.py` for catalog integrity and the
`record()`/`enforce()` mechanics. `backend/tests/integration/
test_production_control_plane_e2e.py` proves guardrails actually stop
workflow execution end-to-end (production-environment block, repair-loop
limit, chaos-environment isolation, dangerous-input block) and that a
legitimate change passes every category cleanly.
