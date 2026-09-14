# Live Demo Script (7–10 minutes)

## Setup (before the room)

```bash
cp .env.example .env          # LLM_MODE=mock — no API key needed
docker compose up --build     # or ./scripts/setup_demo.sh
```

Open http://localhost:5173. Confirm the Dashboard shows the MOCK-mode
banner.

## 1. Motivation (30s)

"This is Intent2Deploy AI: it turns a plain-English developer request
into a validated, human-supervised change — not by asking an LLM to
'rewrite the repo,' but through a coordinated pipeline: retrieval,
planning, diff generation, testing, validation, and Git integration,
with a human approving every risky step."

## 2. New Workflow (1 min)

Go to **New Workflow**. Point at `demo-repository`. Enter the intent:

> "Add a password reset feature. Create appropriate tests and make sure
> existing authentication functionality is not affected."

Click **Start Analysis** (or the **Run Demo** shortcut).

## 3. Repository Intelligence (1.5 min)

On the workflow page, open **Repository Intelligence**. Show:
- The retrieval evidence panel — real files with scores and *why* each
  was retrieved (semantic/BM25/path/symbol).
- Ask the Q&A box: *"Where is authentication handled?"* — show the
  answer cites `src/auth/service.py`.

## 4. Plan + Approval Checkpoint 1 (1.5 min)

Open **Plan**. Walk through: interpreted requirement, acceptance
criteria, implementation steps (each tied to a real retrieved file),
risks. Click **Approve Plan**. Point out: *"Nothing has touched the
repository yet — this is purely an LLM output review."*

## 5. Diff + Approval Checkpoint 2 (1.5 min)

Open **Proposed Changes**. Show the real unified diff adding
`generate_password_reset_token`/`reset_password` to `AuthService`. Click
**Approve Changes**. *"Only now does the system copy the repo into an
isolated workspace and apply this exact patch."*

## 6. Tests + Sandboxed Validation (1.5 min)

Open **Tests**. Show the generated tests (happy path, invalid token,
expired token, and a regression test for existing login). Click
**Generate Tests**, then **Run Validation**. Show the real
syntax/lint/unit-test/security stage results — "18 pre-existing tests
plus 4 new ones, all actually executed just now."

## 7. Commit + CI/CD (1 min)

Open **CI/CD**. Click **Approve Commit** — show the real git branch name
`intent2deploy/<id>` and commit hash. Mention: "Push and PR creation are
available but require an explicit further approval and a configured
GitHub token — never automatic."

## 8. Final Report (1 min)

Open **Final Report**. Show the full traceable record: intent → plan →
evidence → diff → tests → validation → approvals → metrics. Export as
Markdown or JSON.

## 9. Evaluation (1 min)

Switch to the **Evaluation** page (or run
`python scripts/run_evaluation.py` live if time allows). Show the real
10-task benchmark results — 70% completion, 100% validation success on
completed tasks, 0% regression — and explain *why* it's not 100%
(mock mode's honest, bounded scope — see `docs/evaluation.md`).

## Closing line

"Every number just shown was computed from an actual run in this
session — nothing here is a canned screenshot."
