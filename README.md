# Intent2Deploy AI

**From Developer Intent to Executable, Validated DevOps Workflow**

A course project (CSE 4011 — Intelligent Developer Tools and AI DevOps
Workflows) that turns a natural-language developer intent into a
validated, multi-stage, human-supervised AI-DevOps workflow:

```
Intent → Repository Indexing/RAG → LLM Plan → Human Approval →
Code Change Proposal → Human Approval → Test Generation →
Sandboxed Validation → Failure Diagnosis/Bounded Repair →
Git Commit → GitHub Actions CI → Final Report + Metrics
```

## Problem

AI coding assistants typically automate one slice of the developer
workflow (autocomplete, or a single generated function) without a
coordinated, auditable pipeline spanning retrieval, planning, code
generation, testing, validation, and CI/CD — and without a clear model
of when a human needs to look at the output before it goes anywhere
real.

## Solution

Intent2Deploy AI is not "an AI that writes code." It is an **AI-
orchestrated developer workflow**: intent understanding + repository
intelligence (RAG) + prompt-engineered LLM planning + structured code
generation + AI-assisted testing + sandboxed validation + bounded
failure recovery + human oversight + Git/CI automation + measurement,
coordinated by an explicit workflow state machine. See
`docs/architecture.md`.

## Key features

- **Real hybrid RAG**: code-aware chunking (AST for Python), semantic +
  BM25 + path + symbol retrieval, with an explainable "why this file"
  reason for every result. `docs/rag.md`
- **Structured, evidence-grounded LLM planning**: the plan can only
  reference files that were actually retrieved.
- **Diff-based code generation**: never "rewrite the repo" — structured,
  file-scoped unified diffs, safety-limited (max files/lines changed),
  shown to a human before anything touches disk.
- **Three mandatory human approval checkpoints**: Plan, Diff, and any
  externally-visible action (commit, push, PR).
- **Sandboxed validation**: isolated per-workflow workspace, allowlisted
  commands only, real syntax/lint/unit-test/security stages.
- **Bounded, human-approved repair loop** (max 2 attempts, never
  infinite).
- **Real Git integration** and optional GitHub Actions CI, clearly
  distinguishing LOCAL VALIDATION from GITHUB ACTIONS VALIDATION.
- **A 10-task benchmark + evaluation runner** producing real, non-
  fabricated metrics — see the honest 70% completion rate discussed in
  `docs/evaluation.md`.
- **Mock mode** (`LLM_MODE=mock`, default): the entire pipeline is
  demonstrable without any API key — retrieval, planning, code
  generation and validation are all real; only the generative LLM call
  is a deterministic, retrieval-grounded stand-in, clearly labeled in
  the UI. See `docs/responsible-ai.md` and `docs/ai-testing-tools.md`.

## Architecture

```
backend/    FastAPI + SQLModel/SQLite + LangChain + ChromaDB
frontend/   React + Vite + TypeScript
demo-repository/   small fixture repo used for the demo + benchmark
evaluation/  10-task benchmark + results
docs/       architecture, RAG, prompt engineering, responsible AI, evaluation, demo script, course alignment
scripts/    setup_demo.sh, run_evaluation.py
.github/workflows/ai-devops.yml   real CI: lint, test, build, benchmark
```

Full diagram and component table: `docs/architecture.md`.

## Setup

```bash
cp .env.example .env
docker compose up --build
```

or without Docker: `./scripts/setup_demo.sh`. Full instructions,
including enabling a live LLM provider or GitHub integration:
`docs/setup.md`.

## Demo

Open the frontend, go to **New Workflow**, and click **Run Demo** (or
enter your own intent against `demo-repository`). Step-by-step live
demo script: `docs/demo-script.md`.

## Evaluation

```bash
python scripts/run_evaluation.py
```

Real measured results and methodology: `docs/evaluation.md`.

## Test results (this build)

```
backend:  57 passed  (pytest -q, unit + integration + security)
backend lint: All checks passed (ruff check app prompts)
demo-repository: 18 passed  (pytest -q, baseline regression suite)
frontend: tsc -b clean; vite build succeeds
evaluation benchmark: 10 tasks, 7 completed (70%), 100% validation
                       success on completed tasks, 0% regression
```

Reproduce any of these yourself — see `docs/setup.md`.

## Limitations (disclosed, not hidden)

- Mock mode's code generation covers a bounded set of intent patterns
  (see `docs/ai-testing-tools.md`); it is not a general-purpose code
  generator. A live LLM provider is required for arbitrary intents.
- The vector embedding is a deterministic hashing function, not a
  downloaded transformer model — a documented reproducibility trade-off,
  see `docs/rag.md`.
- Sourcegraph OSS and Sweep.dev are documented integration points, not
  live dependencies of this build — see `docs/sourcegraph.md` and
  `app/services/evaluation/automation_provider.py`.
- The "conventional developer workflow" baseline in `docs/evaluation.md`
  is described methodologically rather than run with real human
  participants (out of scope for this project's resourcing).
- JS/TS chunking is regex-heuristic, not a real parser.

## Course alignment

`docs/course-alignment.md` maps every course requirement (prompt
engineering, semantic search, RAG, GitHub Actions, human oversight,
responsible AI, evaluation, …) to the exact code/doc that satisfies it.
`docs/course-evidence/` holds the project charter, timeline, and
responsibility matrix.

## License

See `LICENSE`.
