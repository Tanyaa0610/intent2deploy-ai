# Setup

## Prerequisites

- Python 3.11+
- Node.js 20+ / npm
- Docker + Docker Compose (optional, for the containerized path)
- Git

No LLM API key is required to run the full application: `LLM_MODE=mock`
(the default) uses a deterministic, retrieval-grounded local provider.

## Option A — Docker Compose (Local Dockerized Prototype)

```bash
cp .env.example .env
docker compose up --build
```

- Backend: http://localhost:8000 (API docs at `/docs`, health at `/api/health`)
- Frontend: http://localhost:5173

This is a local prototype — no CI/CD, no cloud deployment. `docker compose
up --build` starts two containers: `backend` (FastAPI/Uvicorn, health-checked
on `/api/health`) and `frontend` (a production Vite build served statically),
with `frontend` waiting for `backend` to report healthy before starting.

Persisted in the named volume `i2d_data` across restarts and rebuilds: the
SQLite database, ChromaDB index, sandboxed workspaces, and any GitHub
repositories cloned via `POST /api/repositories/clone`. The
`demo-repository/` folder is bind-mounted read/write from the host so it
stays available without rebuilding the image.

- Stop: `docker compose down`
- Rebuild after a code change: `docker compose up --build`
- Remove containers **and** local persisted data: `docker compose down -v`

## Option B — Local (no Docker)

```bash
./scripts/setup_demo.sh
```

or manually:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r demo-repository/requirements.txt
cp .env.example .env

cd backend && uvicorn app.main:app --reload --port 8000   # terminal 1

cd frontend && npm install && npm run dev                  # terminal 2
```

Open http://localhost:5173.

## Enabling a live LLM provider

Edit `.env`:

```env
LLM_MODE=live
LLM_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-5
ANTHROPIC_API_KEY=sk-ant-...
```

or for OpenAI:

```env
LLM_MODE=live
LLM_PROVIDER=openai
MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

## Enabling GitHub integration (optional)

```env
GITHUB_TOKEN=ghp_...
GITHUB_OWNER=your-github-username
GITHUB_REPO=your-repo-name
```

Without these set, the Push/PR/CI-status actions return a clear
"GitHub integration is unavailable" error rather than failing silently
or fabricating a result — local validation continues to work.

## Running the benchmark

```bash
source .venv/bin/activate
python scripts/run_evaluation.py
```

Results are written to `evaluation/results/run_<timestamp>.json` and a
matching `_summary.md`.

## Running the backend test suite

```bash
cd backend
pytest -q
ruff check app prompts
```
