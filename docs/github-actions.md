# GitHub Actions CI/CD

## Workflow file

`.github/workflows/ai-devops.yml` runs on every push to `main` or any
`intent2deploy/**` branch, on pull requests to `main`, and manually via
`workflow_dispatch`. It has three jobs:

1. **backend** — installs `backend/requirements.txt`, runs `ruff check`,
   runs the full backend test suite (`pytest`, unit + integration +
   security), uploads the JUnit XML, then installs and runs the
   **demo-repository's own** test suite as a baseline regression check.
2. **frontend** — installs frontend deps, type-checks with `tsc -b`,
   builds with Vite, uploads the build artifact.
3. **evaluation** — installs backend + demo-repository deps and runs
   `python scripts/run_evaluation.py` in `LLM_MODE=mock`, uploading the
   real JSON results as a workflow artifact. Marked `continue-on-error`
   so a benchmark regression does not block merges, but the numbers are
   still visible for every run.

## LOCAL VALIDATION vs GITHUB ACTIONS VALIDATION

The application UI (CI/CD tab) explicitly distinguishes:

- **LOCAL VALIDATION** — the sandboxed pipeline in
  `app/services/validation/pipeline.py`, always available, run for every
  workflow regardless of GitHub configuration.
- **GITHUB ACTIONS VALIDATION** — only shown/attempted when
  `GITHUB_TOKEN`/`GITHUB_OWNER`/`GITHUB_REPO` are configured. Without
  them, `GET/POST .../github/ci` returns
  `{"provider": "local", "status": "not_configured", ...}` rather than a
  fabricated status.

## Triggering and checking a real run

```bash
gh workflow list
gh workflow run ai-devops.yml
gh run list --limit 5
gh run view <RUN_ID>
```

The application never claims a GitHub Actions run passed unless
`app/services/github/github_ops.py::get_latest_workflow_run` actually
returned `conclusion == "success"` for that run — this is a live API
call via PyGithub, not a cached or invented value.

## Why CI failure does not silently pass

The `backend` job is a normal (non-`continue-on-error`) job: if the
backend test suite or lint fails, the workflow run fails, exactly like
any other CI pipeline. Only the `evaluation` job — which measures the
AI workflow's own benchmark success rate, not code correctness — is
allowed to be red without blocking the pipeline, since a benchmark
result naturally varies by design (see `docs/evaluation.md`).
