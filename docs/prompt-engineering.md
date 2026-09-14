# Prompt Engineering

## Design

Every prompt used by the system lives in `backend/prompts/*.md` as a
standalone, versioned file — never inlined as a giant string inside
business logic. Each file has:

- YAML frontmatter: `version`, `purpose`, `input_schema`, `output_schema`,
  `safety_constraints`.
- A `## System Instruction` body with `{placeholder}` variables filled at
  call time via `app/core/prompts.py::PromptTemplate.render`.

The nine required categories (master spec §11) and their files:

| Category | File | Used by |
|---|---|---|
| Requirement analysis | `requirement_analysis.md` | `services/planner/planner.py` |
| Repository retrieval query generation | `retrieval_query_generation.md` | `services/planner/planner.py` |
| Code explanation | `code_explanation.md` | `api/repositories.py` (Q&A) |
| Implementation planning | `implementation_planning.md` | `services/planner/planner.py` |
| Code modification | `code_modification.md` | `services/codegen/codegen.py` |
| Test generation | `test_generation.md` | `services/orchestrator.py::run_test_generation` (schema reference; mock mode synthesizes directly — see below) |
| Failure diagnosis | `failure_diagnosis.md` | `services/validation/repair.py` |
| Repair planning | `repair_planning.md` | `services/validation/repair.py` |
| Final report generation | `final_report_generation.md` | `services/reporting.py` |

## Versioning and audit

`PromptTemplate.version` (currently `v1` for all nine) is recorded:

- on every `Plan` row (`prompt_version` column),
- on every `ProposedChange` generation event's audit metadata,
- in every workflow's `PLAN_GENERATED` / `PATCH_GENERATED` audit events.

This gives a reproducible record of exactly which prompt revision
produced a given plan/diff for any historical workflow — required for
explainability and grading evidence.

## Safety constraints as data, not just prose

Each prompt's `safety_constraints` list is not merely documentation —
the corresponding constraint is enforced in code, independent of what
the LLM actually returns:

- `implementation_planning.md` says the planner must not invent files →
  `planner.py` strips any file the plan references that is not in the
  actual retrieved-file set (`invented_files_removed`).
- `code_modification.md` says the model must not emit shell commands →
  the code-generation output schema (`ChangeSetOutput`) has no field
  through which a shell command could execute; patches are applied via
  in-process diff parsing (`app/services/codegen/diffing.py`), never
  `patch`/`git apply` subprocess calls.
- `code_modification.md`'s size constraints are enforced numerically in
  `codegen.py` (`MAX_FILES_CHANGED`, `MAX_PATCH_LINES`), not left to the
  model to self-police.

## Structured output reliability

All nine prompts request **strict JSON**. `app/core/llm_reliability.py`
wraps every call: parse JSON (tolerant of a model wrapping the JSON in
prose), validate against the matching Pydantic schema, retry up to
`MAX_RETRIES=2` additional times on failure, then raise a typed
`LLMOutputError` rather than silently returning malformed data.

## Mock mode and prompt versioning

`LocalProvider` (mock mode) still goes through the same prompt-render and
schema-validation path — it just answers deterministically instead of
calling a network API (see `docs/responsible-ai.md` and
`docs/ai-testing-tools.md` for the honesty rationale). Prompt version
numbers are therefore recorded identically whether running in mock or
live mode.
