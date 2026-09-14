# Course Alignment Matrix

CSE 4011 — Intelligent Developer Tools and AI DevOps Workflows.

| Course Requirement | Project Implementation | Evidence |
|---|---|---|
| Prompt Engineering | 9 versioned prompt templates (frontmatter + system instruction) covering requirement analysis, retrieval, explanation, planning, codegen, test generation, failure diagnosis, repair, reporting | `backend/prompts/*.md`, `docs/prompt-engineering.md`, `Plan.prompt_version` |
| Semantic Code Search | Code-aware chunking + hybrid (semantic/BM25/path/symbol) retrieval | `backend/app/services/rag/`, Repository Intelligence tab |
| Sourcegraph | Documented complementary tool + integration seam (not a live dependency) | `docs/sourcegraph.md` |
| LLM Code Understanding | Repository Q&A + evidence-grounded planning | `code_explanation.md` prompt, Plan tab |
| RAG | LangChain (text splitters, `Embeddings` interface) + ChromaDB vector store | `backend/app/services/rag/`, `docs/rag.md` |
| Code Generation | Structured, evidence-scoped unified-diff proposals with hard safety limits | `backend/app/services/codegen/`, Proposed Changes tab |
| AI Testing | Framework-matching generated tests, actually executed | `backend/app/services/testing/`, Tests tab |
| Bug Detection | Sandboxed validation pipeline + LLM failure diagnosis | `backend/app/services/validation/`, CI/CD tab |
| GitHub Actions | Real `.github/workflows/ai-devops.yml` (lint/test/build/evaluation) | `docs/github-actions.md` |
| DevOps Automation | Explicit workflow state machine orchestrating every stage | `backend/app/services/orchestrator.py`, `state_machine.py` |
| Human Oversight | 3 mandatory approval checkpoints + persisted audit trail | `backend/app/models/models.py::AuditEvent`, Workflow Timeline UI |
| Responsible AI | Untrusted-repository-content model, secret redaction, bounded autonomy | `docs/responsible-ai.md` |
| Evaluation | 10-task benchmark + real metrics runner | `evaluation/`, `scripts/run_evaluation.py`, `docs/evaluation.md` |

## Mapping to project phase evaluations

### A1 — Phase Evaluation 1 (30%)

- Problem definition, objectives, methodology: `PROJECT_PLAN.md`, `README.md`.
- Prompt engineering for code completion/refactoring: `backend/prompts/`.
- Sourcegraph/semantic navigation: `docs/sourcegraph.md`.
- Tool configuration & code exploration: `docs/setup.md`, Repository Intelligence tab.
- Course-evidence artifacts: `docs/course-evidence/`.

### A2 — Phase Evaluation 2 (30%)

- RAG-based Q&A using LangChain: Repository Intelligence Q&A (`POST /api/repository/ask`).
- GitHub Actions CI/CD with AI workflow automation: `.github/workflows/ai-devops.yml`, `docs/github-actions.md`.
- AI-assisted test generation: `docs/ai-testing-tools.md`, Tests tab.
- Working prototype: full vertical slice, end-to-end tested (see `README.md` "Test results").

### A3 — Final Project (40%)

- Coordinated pipeline (not disconnected features): the workflow state
  machine (`orchestrator.py`) is the single source of truth that
  sequences retrieval → planning → codegen → testing → validation →
  repair → git → CI for every workflow.
- Custom prompt design: `backend/prompts/`.
- Evaluation: `evaluation/`, real measured results in
  `docs/evaluation.md`.
- Presentation/usability: clean developer-tool UI (`frontend/`), demo
  script (`docs/demo-script.md`).
