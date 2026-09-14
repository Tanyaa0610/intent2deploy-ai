# AI-Assisted Testing Tool Mapping

The course mentions CodiumAI/Codeium as a reference point for
AI-assisted test generation. This document maps this project's own
test-generation stage to that capability, and states plainly what is and
is not a real external integration.

## Where AI-assisted test generation fits in this project

`backend/app/services/testing/` + the `test_generation` prompt
(`backend/prompts/test_generation.md`) implement the same conceptual
capability CodiumAI/Codeium provide: given existing code and a change,
propose tests covering happy path, edge cases, invalid input, regression,
and security/authorization conditions, in the repository's existing test
style.

No CodiumAI/Codeium API is called. There is no API key configuration for
it in `.env.example` because there is nothing to call — this project's
test generation is a first-party feature, not an adapter around that
product. This is a deliberate, disclosed scope decision, not an
oversight.

## How this project's test-generation stage works

1. **Discover existing tests** (`orchestrator.py::run_test_generation`
   counts `test_*.py` files in the target repository) so the UI can show
   `Existing tests found: N` truthfully.
2. **Generate tests grounded in the actual proposed change** — in mock
   mode, `app/services/testing/mock_test_strategies.py` pairs one
   test-generation function per supported intent category with the
   matching code-generation strategy in
   `app/services/codegen/mock_strategies.py`, so the tests actually
   exercise the code that was actually added (verified in
   `backend/tests/integration/test_orchestrator_e2e.py`). In live mode,
   the `test_generation` prompt asks the configured LLM directly.
3. **Apply and run** — generated test content is appended to (or creates)
   the appropriate test file inside the sandboxed workspace, then the
   validation pipeline actually executes `pytest` against it. No test
   result is ever reported without having actually run.

## How usefulness is evaluated

`scripts/run_evaluation.py` and the persisted `ValidationResult` rows are
the evidence: for each benchmark task, the real pass/fail outcome of the
generated tests (plus the full pre-existing regression suite) is
recorded. `docs/evaluation.md` reports the measured numbers from an
actual run — including the tasks where mock mode could not generate a
grounded test at all, which is disclosed rather than hidden.

## If a real external tool becomes available

The provider-abstraction pattern used for LLMs
(`app/services/providers/`) is the template to follow: a
`TestGenerationProvider` interface with a `CodiumProvider` adapter could
be added without touching the orchestrator, gated by its own
`is_available()` check exactly like `SweepProvider` in
`app/services/evaluation/automation_provider.py`. This is not
implemented in the current build.
