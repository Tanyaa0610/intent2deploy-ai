# Project Charter — Intent2Deploy AI

## Problem

Developers spend significant effort translating a natural-language
requirement into a validated code change: understanding the relevant
part of a codebase, writing the change, writing tests, running
validation, and integrating with CI/CD. AI coding assistants generally
automate only one slice of this (autocomplete, or a single "write this
function" request) without a coordinated, auditable, human-supervised
pipeline across the whole sequence.

## Solution

Intent2Deploy AI orchestrates the full sequence — intent → repository
retrieval (RAG) → LLM planning → human-approved diff generation → AI
test generation → sandboxed validation → bounded automatic repair → Git
commit → GitHub Actions CI → traceable final report — behind explicit
human approval checkpoints, so no step is either fully manual (slow) or
fully autonomous (unsafe).

## Objectives (see `PROJECT_PLAN.md` §5 for the full list)

1. Convert NL intent into a structured, evidence-grounded plan.
2. Retrieve relevant repository context via hybrid semantic search.
3. Generate explainable, safety-limited code-change proposals.
4. Generate and actually execute tests for each change.
5. Validate via a real sandboxed pipeline (syntax/lint/test/build/security).
6. Integrate with Git/GitHub and GitHub Actions.
7. Gate every risky action behind human approval.
8. Produce a traceable final report with real metrics.
9. Evaluate over a 10-task benchmark.
10. Document (rather than fabricate) any baseline comparison.

## Feasibility / resource plan

- Runs entirely locally (SQLite, ChromaDB, one deterministic mock LLM
  provider) — no paid API required for full functional demonstration.
- `docker compose up --build` or `./scripts/setup_demo.sh` for a
  single-command local setup.
- Optional live-LLM and GitHub integrations are additive, not required
  for the core deliverable.

## Team responsibility matrix

*(Fill in with actual team member names before submission — this
project's codebase does not assume a solo or group submission.)*

| Area | Owner | Notes |
|---|---|---|
| Backend / orchestration / RAG / safety | _TBD_ | `backend/` |
| Frontend | _TBD_ | `frontend/` |
| Evaluation & benchmark design | _TBD_ | `evaluation/`, `scripts/` |
| Documentation | _TBD_ | `docs/` |

The implementation was built with Claude Code as an AI pair-engineer
under direct developer instruction and review; the student(s) listed
above are responsible for understanding, defending, and presenting the
system in the viva.
