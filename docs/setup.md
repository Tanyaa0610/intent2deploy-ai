# Setup

## Prerequisites

- Python 3.11+
- Node.js 20+ / npm
- Docker + Docker Compose (optional, for the containerized path)
- Git

No LLM API key is required to run the full application: `LLM_MODE=mock`
(the default) uses a deterministic, retrieval-grounded local provider.

## Option A — Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173

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
