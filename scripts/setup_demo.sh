#!/usr/bin/env bash
# Sets up Intent2Deploy AI for a local demo run without Docker.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Setting up backend virtual environment"
if [ ! -d ".venv" ]; then
  python3.11 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt

echo "==> Installing demo-repository dependencies"
pip install -r demo-repository/requirements.txt

if [ ! -f ".env" ]; then
  echo "==> Creating .env from .env.example (mock mode, no API key required)"
  cp .env.example .env
fi

echo "==> Setting up frontend"
cd frontend
if [ ! -d "node_modules" ]; then
  npm install
fi
cd "$ROOT_DIR"

echo "==> Running backend test suite"
cd backend
pytest -q
cd "$ROOT_DIR"

cat <<'EOF'

Setup complete.

Start the backend:
  source .venv/bin/activate
  cd backend && uvicorn app.main:app --reload --port 8000

Start the frontend (in a second terminal):
  cd frontend && npm run dev

Then open http://localhost:5173 and click "Run Demo" on the New Workflow page,
or run the evaluation benchmark:
  python scripts/run_evaluation.py
EOF
