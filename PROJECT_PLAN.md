# PROJECT_PLAN.md — Intent2Deploy AI

## 1. Purpose

Intent2Deploy AI turns a natural-language developer intent into a validated,
multi-stage, human-supervised DevOps workflow:

```
Intent → Repository Indexing (RAG) → LLM Plan → Human Approval →
Code Change Proposal (diff) → Human Approval → Test Generation →
Sandboxed Validation → Failure Diagnosis / Bounded Repair →
Git Commit → GitHub Actions CI → Final Report + Metrics
```

Built for CSE 4011 — Intelligent Developer Tools and AI DevOps Workflows.

## 2. Build Order (tracked against master spec §48)

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Skeleton: backend (FastAPI/SQLModel/SQLite), frontend (React/Vite/TS), docker-compose, `.env.example` | in progress |
| 2 | Repository ingestion / indexing + RAG (LangChain + ChromaDB) | pending |
| 3 | Repository Q&A endpoint + UI | pending |
| 4 | LLM planning with structured (Pydantic) output + prompt library | pending |
| 5 | Code-change proposal + unified diff generation + diff viewer | pending |
| 6 | Human approval workflow + audit trail | pending |
| 7 | Test generation + sandboxed execution | pending |
| 8 | Failure diagnosis + bounded repair loop (max 2 attempts) | pending |
| 9 | Git integration (branch/commit, no auto-push) | pending |
| 10 | GitHub Actions CI integration (real workflow file + optional push/PR) | pending |
| 11 | Evaluation framework + 10-task benchmark + runner | pending |
| 12 | Dashboard + Final Report (Markdown/JSON export) | pending |
| 13 | Security hardening (allowlist, path traversal, secret exclusion) + test suite | pending |
| 14 | Documentation + Demo Mode | pending |
| 15 | Git init, secret scan, GitHub repo creation & push | pending |

## 3. Architecture Decisions

- **Backend**: Python 3.11 (project `.venv`), FastAPI, SQLModel over SQLite,
  LangChain for RAG/orchestration, ChromaDB (local, on-disk, ONNX MiniLM
  default embedding function — no GPU/torch dependency required) as the
  vector store, pytest + Ruff for backend quality gates.
- **LLM Provider Abstraction**: `LLMProvider` interface with
  `AnthropicProvider`, `OpenAIProvider`, and `LocalProvider` (deterministic
  mock). `LLM_MODE=mock` is the default so the whole system is demonstrable
  without API credentials. Mock mode still performs **real retrieval** over
  the indexed repository and derives its plan/diff/tests from that
  retrieved evidence — it does not hardcode outputs — so changing the
  developer intent changes the retrieved files, plan, diff, and tests.
- **Frontend**: React + Vite + TypeScript, hand-built diff viewer (no heavy
  Monaco dependency required for the course demo; documented as a
  swappable choice).
- **Persistence**: SQLite via SQLModel. All workflow stages, retrieved
  documents, plans, proposed changes, test results, approvals, audit
  events, and metrics are persisted so a UI refresh does not lose state.
- **Sandboxing**: every workflow gets an isolated `/workspaces/{workflow_id}`
  directory (git worktree/copy). Only allowlisted commands execute, under a
  timeout, with captured stdout/stderr/exit code.
- **Safety**: three mandatory human checkpoints (Plan, Diff, External
  Action) enforced by the workflow state machine — invalid transitions are
  rejected at the API layer.

## 4. Non-Goals / Explicit Limitations

- No PostgreSQL, no Kubernetes, no multi-tenant auth — out of scope for a
  local, reproducible course project (§43).
- Sourcegraph OSS and Sweep.dev are **not** wired as live integrations
  unless credentials/infra are available; they are documented as adapters
  (`docs/sourcegraph.md`, `docs/ai-testing-tools.md`,
  `app/services/evaluation/automation_provider.py`) with an explicit
  "unavailable in this environment" status rather than simulated calls.
- FAISS is not installed by default (ChromaDB covers the vector-store
  requirement); the retrieval interface is written so FAISS could be
  swapped in via `VECTOR_STORE=faiss`.

## 5. Definition of Done

Tracked verbatim from the master spec §49 checklist; verified at the end of
implementation in the final report delivered in the closing chat message.
