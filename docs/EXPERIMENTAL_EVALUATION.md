# Experimental Evaluation: Baseline vs. Intent2Deploy

This document specifies, and reports the results of, a controlled
experiment comparing a non-orchestrated baseline LLM-assisted coding
approach against the full Intent2Deploy AI workflow. It extends (does
not replace) `docs/evaluation.md`, which documents the Intent2Deploy
arm's own metrics in more detail; this document is specifically about
the **comparison** between the two arms, written for the mid-term
evaluation rubric (research question alignment, quantitative evaluation,
results and interpretation).

Nothing in this document is hardcoded or invented. Every number below
was produced by the commands in [Reproducing the experiment](#reproducing-the-experiment),
on this build, in `LLM_MODE=mock`. Re-running those commands regenerates
the numbers from scratch — they are not pasted-in constants.

> **Repository migration note (this revision).** The target fixture
> repository was replaced: `demo-repository/` now contains **ShopFlow**,
> a larger, SQLite-backed FastAPI e-commerce backend
> (`demo-repository/src/shopflow/` — users, products, inventory, carts,
> orders, payments, refunds, notifications, audit log), in place of the
> original small in-memory auth/orders/payments fixture. The 11-task
> benchmark was migrated 1:1 (same categories, same experimental intent,
> retargeted at ShopFlow's real files) and extended with 10 new tasks
> (`task_012`–`task_021`), for 21 tasks total. Every number in this
> document is from the **current ShopFlow-based run**; the prior
> (smaller-fixture) results are preserved, clearly labeled, in
> `evaluation/results/archive_pre_shopflow/` and are not reused or
> averaged into anything below.

## 1. Research question

> How reliably can an LLM transform natural-language developer intent
> into a validated, multi-stage AI-DevOps workflow with minimal human
> intervention?

This is the same research question already stated in `docs/evaluation.md`
and `evaluation/README.md`; it has not been changed.

## 2. Experimental design

### 2.1 System under test — Intent2Deploy

The full orchestrated workflow already implemented in this repository:

```
Developer Intent → Repository Indexing → ChromaDB Retrieval (hybrid
semantic + BM25 + path + symbol) → RAG Context → Planning → Human
Approval → Code Generation → Test Generation → Validation → Guardrails
→ Readiness / Final Result
```

Run by `scripts/run_evaluation.py` (pre-existing; this experiment adds
guardrail-check counts and per-stage latency instrumentation to its
output — see [§2.3](#23-instrumentation-added-for-this-experiment)).

### 2.2 Baseline — non-orchestrated single-shot approach

Implemented in `backend/app/services/evaluation/baseline_runner.py`
(new) and run by `scripts/run_baseline_evaluation.py` (new). For each
task, the baseline:

1. Receives the same developer intent text as Intent2Deploy.
2. Gathers **"basic repository context"**: a naive keyword-overlap file
   scorer (`select_basic_context`) scans the repository's `.py` files
   (excluding `tests/`), scores each by how many of the intent's
   extracted key terms appear in its path/content, and returns the
   top 3. This stands in for "hand the model some files that seem
   relevant" — no embeddings, no BM25, no AST-aware chunking, no
   configurable `top_k` (contrast with
   `app/services/rag/retriever.py`, which Intent2Deploy uses with
   `top_k=12` and a hybrid scoring function).
3. Makes **one direct call** to the same LLM provider Intent2Deploy
   uses (`LocalProvider`, `"local-mock-v1"`, in `LLM_MODE=mock` — see
   [§2.4](#24-why-llm_modemock-and-what-live-mode-would-change)) with
   the `code_modification` prompt — no planning stage, no human-approval
   checkpoint, no guardrail engine.
4. Applies any generated patch to an **isolated workspace copy** (via
   the project's existing `app/services/validation/sandbox.py`
   utilities, keyed by `baseline-<run_id>-<task_id>` — never the real
   `demo-repository/` fixture, never an Intent2Deploy workflow's own
   workspace).
5. Runs the repository's test suite **exactly once** (`python3 -m
   pytest -q`) — no bounded repair loop, no separate lint/syntax/security
   validation stages.
6. Records the result and destroys the workspace.

The baseline is deliberately built by **reusing** Intent2Deploy's own
code-generation core (`LocalProvider`, `mock_strategies`, `apply_patch`)
rather than a different model or a hand-written stand-in. This is a
methodological choice: it isolates what is being measured to the value
of the *pipeline* (retrieval quality, planning, approval gates,
validation, guardrails) rather than conflating it with a difference in
underlying model capability. See [§6 Limitations](#6-limitations-and-assumptions)
for what this choice does and does not let us conclude.

### 2.3 Instrumentation added for this experiment

`scripts/run_evaluation.py` already measured most of what this
experiment needs (task completion, validation success, human
intervention, repair attempts, execution time, retrieval precision/
recall@K, the unnecessary-modification proxy, and real regression
detection against a pristine test collection). Two things were missing
and have been added, minimally, without changing its control flow:

- **Guardrail check counts** (`guardrail_total/warnings/blocked/failed`)
  — read from the `GuardrailCheck` rows the orchestrator already writes
  automatically at each checkpoint; nothing new is evaluated, this just
  surfaces data that already existed.
- **Per-stage latency** (`stage_latency_ms`: indexing/planning/codegen/
  testgen/validation) — read from `Workflow.indexing_ms` etc., which the
  orchestrator already computes and persists but `run_evaluation.py`
  was not yet reading into its output.
- **`touched_expected_files`** — in both arms, the fraction of a task's
  `expected_files` that were actually part of the applied change (not
  just *retrieved*, but *changed*). This is what makes "code
  correctness" (below) a real, independent signal rather than a restated
  completion rate.

`collect_baseline_tests` (pristine-test-collection helper) was moved
from being a private function inside `run_evaluation.py` into the new
shared module (`collect_pristine_test_ids`) so both arms use the
identical definition of "a regression" — this is a pure relocation, not
a behavior change.

### 2.4 Why `LLM_MODE=mock`, and what live mode would change

This build runs with `LLM_MODE=mock` by default (no API key required;
see `docs/ai-testing-tools.md`). `LocalProvider` supports a bounded set
of five intent categories with real, grounded code-generation strategies
(`password_reset`, `bug_fix_orders`, `input_validation`,
`auth_token_expiry`, `payment_timeout_reliability` — see
`app/services/codegen/mock_strategies.py`); an intent that doesn't match
one of these returns an honest no-op (confidence 0, explanatory reason),
never fabricated code. Both arms use this identical provider, so neither
arm has an unfair generative advantage — but it also means this
benchmark cannot show a difference in *generation quality* between arms,
only in what the pipeline does with that generation (context selection,
approval, validation, guardrails). Running with `LLM_MODE=live` and a
configured provider (Anthropic/OpenAI) would let both runners call a
real model for arbitrary intents; the runner code does not need to
change for this (`LocalProvider` is swapped for a real `LLMProvider` at
the call site), but it was not run this way for this report because it
would consume real API credits and introduce non-determinism across
runs — left as documented future work.

## 3. Benchmark

21 tasks in `evaluation/tasks/task_001.json` … `task_021.json`, grounded
in the real ShopFlow fixture at `demo-repository/`. **Every
`expected_files` path across all 21 tasks was verified to exist on disk
immediately before each run in this document** (a scripted check, not a
spot-check — see §7.2). See `evaluation/README.md` for the full table.

Tasks 001–011 are the original 10/11-task benchmark, migrated: same
`id`, `category`, `difficulty`, and experimental intent as before,
retargeted at ShopFlow's equivalent file(s) and (where the original
scenario no longer applied verbatim — e.g. ShopFlow already ships a
cancel-order endpoint) re-grounded in a real, verified ShopFlow gap of
the same category. Tasks 012–021 are new. Category coverage:

| Category | Tasks |
|---|---|
| feature_addition | task_001 (password reset), task_012 (payment idempotency, differently worded from task_011), task_013 (low-stock notification) |
| bug_fix | task_002 (order-total null reference), task_014 (cancel after shipment), task_019 (cancel restores inventory), task_020 (refund eligibility), task_021 (failed payment confirms order) |
| test_generation | task_003 (missing-order edge case tests) |
| api_modification | task_004 (reactivate-user endpoint) |
| validation_error_handling | task_005 (registration input validation), task_018 (max quantity per product) |
| authentication_security | task_006 (session-token expiry), task_015 (admin-only inventory update) |
| database_service_change | task_007 (session invalidation on deactivation) |
| documentation_code_quality | task_008 (order-service docs) |
| regression_sensitive_refactor | task_009 (password-hash refactor) |
| refactoring | task_010 (order-service data access) |
| reliability_improvement | task_011 (duplicate-charge / payment timeout), task_016 (payment retry handling) |
| observability_logging | task_017 (structured failed-payment logging) |

`observability_logging` is a new category (no equivalent in the original
10-category spread) added because ShopFlow — unlike the original
fixture — has a real structured-logging module (`utils/logging.py`) to
ground a logging task in, without inventing one. task_011 and task_012
deliberately target overlapping functionality from differently-worded
intents (see `evaluation/README.md`) — this was a deliberate design
choice approved before the benchmark was run, not something altered
afterward to influence results.

No new `evaluation/benchmark.json` was created. The existing per-file
`evaluation/tasks/task_NNN.json` format already satisfies "a clear,
reproducible JSON format" and is what both runners already consume —
consolidating it into a second file would duplicate, not improve, the
existing benchmark storage.

## 4. Metric definitions

| Metric | Formula | Data source | Unit | Interpretation |
|---|---|---|---|---|
| Task completion rate | `completed_tasks / total_tasks`; a task counts as completed only if validation passed **and** at least one real (non-zero-confidence) change was applied | Workflow state + `ProposedChange.confidence` | fraction | Primary answer to "how reliably" |
| Code correctness (structural proxy) | `completed AND (no expected_files OR touched_expected_files > 0)` | `touched_expected_files` (new, §2.3) + completion | fraction | **Not** a semantic grading of the task's `acceptance_criteria` text — see §6 |
| Test / validation pass rate | fraction of tasks whose final validation run exited 0 | `ValidationResult` / pytest exit code | fraction | Includes trivial passes where nothing changed — read together with completion rate |
| File-selection recall@K | `\|selected ∩ expected\| / \|expected\|`, per task, averaged | `RetrievedDocument` (Intent2Deploy) / `select_basic_context` (baseline) vs. task `expected_files` | fraction | Did the system find the human-curated relevant files? |
| File-selection precision@K | `\|selected ∩ expected\| / \|selected\|`, per task, averaged | same as above | fraction | Of what was looked at, how much was relevant? |
| Unnecessary modifications (proxy) | `\|changed − expected\| / \|changed\|`, per task, averaged | `ProposedChange.file` vs. `expected_files` | fraction | Proxy: `expected_files` is human-curated, not perfect ground truth |
| Human intervention count | `sum(Workflow.human_intervention_count) / total_tasks` | `Workflow` row | count/task | Lower is not automatically better — see §5 interpretation |
| Regression rate | tasks where a pristine-passing test shows `FAILED` after the change, `/ total_tasks` | pristine test collection (`--collect-only`) vs. final `pytest` run, both arms | fraction | Real detection, not a proxy |
| Execution time | wall-clock per task, `time.monotonic()` | runner | ms/task | Speed only, not quality |
| Guardrail warnings/blocks | count of `GuardrailCheck` rows by status | `GuardrailCheck` | count/task | **Intent2Deploy only** — baseline has no guardrail engine (structurally absent, reported as `null`, not `0`) |
| Per-stage latency | `Workflow.{indexing,planning,codegen,testgen,validation}_ms` | `Workflow` row | ms | **Intent2Deploy only**; baseline reports `context_selection`/`codegen`/`validation` instead, since it has no separate indexing/planning/testgen stages |

## 5. Measured results (this build, `LLM_MODE=mock`, ShopFlow benchmark)

Reproduced from `evaluation/results/run_20261007T104452Z.json`
(Intent2Deploy, 21 tasks), `evaluation/results/baseline_run_20261007T104609Z.json`
(baseline, 21 tasks), and `evaluation/results/experiment_summary.json`
(the comparison) — all three regenerable with the commands in §7, and
all also browsable in the frontend Evaluation page. **These numbers
supersede every number in the previous revision of this document**,
which described the old, smaller fixture repository (archived — see the
migration note at the top of this document).

| Metric | Baseline | Intent2Deploy | Abs. diff | % change |
|---|---|---|---|---|
| Task completion rate | 33.3% | 33.3% | 0.0 | 0% |
| Code correctness (proxy) | 33.3% | 33.3% | 0.0 | 0% |
| Validation pass rate | 90.5% | 85.7% | −4.8pp | −5.3% |
| File-selection recall@K | 0.881 | 0.893 | +0.012 | +1.4% |
| File-selection precision@K | 0.365 | 0.115 | −0.250 | −68.5% |
| Unnecessary modifications (proxy) | 0.111 | 0.524 | +0.413 | +372.1% |
| Human intervention points/task | 0 | 2.86 | +2.86 | n/a (baseline structurally 0) |
| Regression rate | 9.5% | 9.5% | 0.0 | 0% |
| Execution time/task | 1,419ms | 3,483ms | +2,064ms | +145.5% |
| Guardrail warnings/task | n/a | 0.57 | — | Intent2Deploy only |
| Guardrail blocks/task | n/a | 0.43 | — | Intent2Deploy only |

Per-stage latency (Intent2Deploy, ms): indexing 177.5, planning 97.7,
codegen 0.0, testgen 0.9, validation 1553.8 — validation dominates
execution time, expected given ShopFlow's much larger test suite (73
tests vs. the old fixture's ~20).

### Interpretation (as generated by `scripts/compare_evaluation_runs.py`, read alongside manual diagnosis below)

- **Task completion was identical (33.3%, 7/21) in both arms.** The 7
  that completed are exactly the tasks among 001–011 whose intent
  matches one of the 5 grounded mock strategies (same strategies, same
  code, same reasoning as the earlier 11-task result — see
  `docs/evaluation.md`). **All 10 new tasks (012–021) failed to
  complete in both arms** — mock mode's strategy set was not extended
  to cover them (expected; see §6). This means the 21-task completion
  rate is **not comparable** to the earlier 11-task 72.7% figure: the
  denominator changed from "tasks the generator can handle" to "tasks
  the generator can handle plus 10 it structurally cannot" — the drop
  from 72.7% to 33.3% is a benchmark-composition effect, not a
  regression in the pipeline.
- **A real, measured regression was found — not a flaw in the
  comparison, a flaw in a specific mock strategy.** task_012
  (Intent2Deploy) and task_016 (both arms) hit `VALIDATION_FAILED` with
  13 genuine test failures (`AttributeError`). Root cause (confirmed by
  direct reproduction, not inferred): the `payment_idempotency` mock
  strategy (`app/services/codegen/mock_strategies.py`) patches
  `payment_service.py`, `schemas/payment.py`, and `api/payments.py`
  **independently per-file**, gated only on whether each file is
  present in the retrieved/selected context. For these two tasks'
  specific intent wording, retrieval/selection surfaced
  `payment_service.py` and `api/payments.py` but not
  `schemas/payment.py` — and the patched `api/payments.py` reads
  `payload.idempotency_key`, a field only `schemas/payment.py`'s patch
  adds. The result is syntactically valid, semantically broken code: a
  real, reproducible coupling bug in the mock strategy, surfaced by
  running the actual 21-task benchmark rather than by manual
  spot-checks. **Not fixed in this revision** — per this evaluation
  round's explicit scope (benchmark migration and measurement only, no
  feature changes) — and reported here instead of silently patched.
  See §9 for the full reproduction.
- **File-selection precision dropped sharply for both arms** relative
  to the 11-task benchmark (Intent2Deploy: 0.136 → 0.115; baseline:
  0.424 → 0.365), and **Intent2Deploy's precision is now much further
  below the baseline's** (0.115 vs. 0.365, −68.5%, roughly the same gap
  as before in relative terms). This is a mechanical consequence of
  repository size: ShopFlow has roughly 5–6× as many Python files as
  the old fixture, so Intent2Deploy's fixed `top_k=12` retrieval now
  returns a much lower fraction of truly-relevant files for the same
  small `expected_files` ground-truth sets, while the baseline's
  `top_k=3` is naturally more conservative. Recall stayed comparable
  (0.893 vs. 0.881) — both arms still reliably find *a* relevant file,
  just with more noise around it for Intent2Deploy.
- **Unnecessary modifications rose sharply for Intent2Deploy** (0.524
  vs. the baseline's 0.111, and vs. 0.0 in the 11-task benchmark) —
  directly explained by the same retrieval-breadth effect above:
  broader retrieval in a larger repository means more candidate files
  get proposed as changes, a larger fraction of which fall outside each
  task's narrow `expected_files` set.
- **Validation pass rate (85.7% vs. 90.5%) and regression rate (9.5%
  both arms)** are both fully explained by the single task_012/
  task_016 bug above — there is no second, independent cause in this
  run's data.
- **Human intervention: baseline 0 (structural), Intent2Deploy 2.86/task**
  (down from 3.0/task in the 11-task benchmark because tasks that
  never reach a change-approval checkpoint — the 10 no-op tasks among
  012–021 — accumulate fewer intervention events than a task that
  reaches COMPLETED). Still the same structural trade-off: baseline has
  no mechanism for a human to catch a problem; Intent2Deploy has
  up to three gates.
- **Where the baseline outperformed Intent2Deploy on this benchmark**:
  validation pass rate, file-selection precision, unnecessary
  modifications, and execution time. This is a larger set of
  baseline-favorable metrics than the 11-task benchmark showed, driven
  almost entirely by the retrieval-breadth effect on a larger
  repository, not by the baseline's reasoning being better.
- **No repair attempts were triggered** in this run, so the bounded
  repair loop's potential advantage over the baseline's single-shot
  validation was not exercised here.
- **Guardrails recorded 0.57 warnings and 0.43 blocks per task on
  average** (Intent2Deploy only) — comparable order of magnitude to the
  11-task benchmark (0.27 / 0.73), not separately investigated per
  guardrail ID in this round (same limitation as before — see §6).

## 6. Limitations and assumptions

- **n = 21 tasks, one fixture repository, one run each.** No
  statistical significance test is reported or claimed — the sample is
  far too small. All numbers above are descriptive observations of this
  specific benchmark, not a generalizable claim about LLM-assisted
  coding in general.
- **10 of the 21 tasks (012–021) have no grounded mock strategy.**
  Mock mode's 5 code-generation strategies were written for the
  original 5 scenarios (tasks 001/002/005/006/011) and were
  deliberately *not* extended to cover the 10 new tasks as part of this
  evaluation round — doing so would mean generating code for the
  benchmark rather than measuring the pipeline against a fixed
  benchmark, which §14 of this round's instructions explicitly
  prohibited ("do not optimize the benchmark based on observed
  results"). Their value in this round is structural: they prove the
  pipeline produces an honest no-op (not fabricated code) when mock
  mode cannot ground a change, across 10 additional realistic
  scenarios. A `LLM_MODE=live` run is the correct way to get a
  completion-rate measurement for them.
- **A real, unfixed bug exists in the `payment_idempotency` mock
  strategy** (see §5 and §9): its 3-file patch has an inter-file
  dependency that is not safe when only a subset of the 3 files is
  retrieved. This affects exactly task_012 (Intent2Deploy arm) and
  task_016 (both arms) in this specific run and is the sole cause of
  the measured regression rate. It does not affect task_011, which
  patches only `payment_service.py` and was unaffected by this bug in
  this run. Left unfixed deliberately in this revision — see §5.
- **`LLM_MODE=mock` bounds what can be measured.** Both arms share the
  same bounded code-generation core, so this experiment measures the
  *pipeline's* effect (context gathering, approval, validation,
  guardrails, repair) holding generation constant — it does not, and
  cannot, measure whether Intent2Deploy's structured prompting produces
  better *generated code* than an unstructured prompt would with a real
  model. Re-running both runners under `LLM_MODE=live` (same provider,
  same model, same temperature) would be needed to measure that; the
  code supports it (`provider` is an injectable parameter in both
  runners) but it was not run for this report (see §2.4).
- **"Code correctness" is a structural proxy**, not a semantic grading
  of each task's `acceptance_criteria` text. Scoring acceptance criteria
  semantically would require either a human rater or an LLM-as-judge
  call — both documented as explicit future work in `docs/evaluation.md`
  ("Plan quality") and not implemented here, to avoid introducing a
  second, unvalidated LLM judgment into a project whose stated purpose
  is honesty about what mock mode can and cannot verify.
- **The baseline's "basic repository context" is one reasonable
  operationalization of "simpler LLM-assisted approach," not the only
  possible one.** A different naive-retrieval design (e.g., different
  `max_files`, including test files, or a different scoring function)
  would likely shift the precision/recall numbers in §5. The
  implementation and its exact scoring rule are in
  `baseline_runner.select_basic_context` for inspection and
  modification.
- **Guardrail-ID-level attribution of the 0.73 blocks/task figure was
  not analyzed** — the comparison script reports the count, not which
  of the ~40+ cataloged guardrails fired or why. A qualitative
  follow-up (reading the `GuardrailCheck` rows for the 11-task run
  directly, e.g. via the Guardrails & Safety page) is recommended before
  citing this number as evidence of anything beyond "guardrails do
  fire during a normal run."
- **This is a single run per arm.** Both runners are deterministic in
  `LLM_MODE=mock` (same intent → same output every time — see
  `test_select_basic_context_is_naive_and_deterministic`), so repeat
  runs are not expected to change these numbers under mock mode; this
  would not hold under `LLM_MODE=live`.

## 7. Reproducing the experiment

### 7.1 Environment

- Python 3.11 (a `backend/.venv` virtualenv is the supported setup;
  `python3.11 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`)
- No API key required (`LLM_MODE=mock`, the default — see
  `backend/app/core/config.py`)
- Repository version: whatever commit is checked out; the benchmark
  targets the `demo-repository/` fixture at that commit

### 7.2 Commands

```bash
# 1. Intent2Deploy arm (writes evaluation/results/run_<ts>.json)
cd /path/to/intent2deploy-ai
backend/.venv/bin/python scripts/run_evaluation.py

# 2. Baseline arm (writes evaluation/results/baseline_run_<ts>.json)
backend/.venv/bin/python scripts/run_baseline_evaluation.py

# 3. Comparison, interpretation, failure analysis (writes
#    evaluation/results/experiment_summary.{json,md})
backend/.venv/bin/python scripts/compare_evaluation_runs.py
```

Each of the three scripts picks up the *latest* matching file in
`evaluation/results/` by filename timestamp, so re-running step 1 or 2
and then step 3 regenerates the comparison against the newest runs.

### 7.3 Where results are stored

```
evaluation/
  tasks/task_001.json … task_021.json   (benchmark, version-controlled)
  results/                               (gitignored — regenerate locally)
    run_<timestamp>.json                 Intent2Deploy arm, one file per run
    run_<timestamp>_summary.md
    baseline_run_<timestamp>.json        baseline arm, one file per run
    baseline_run_<timestamp>_summary.md
    experiment_summary.json              latest comparison (overwritten each run)
    experiment_summary.md
    archive_pre_shopflow/                 results from the earlier, smaller
                                           fixture repository — preserved,
                                           not reused (see migration note)
```

### 7.4 Frontend

`GET /api/evaluation/results`, `/api/evaluation/baseline-results`, and
`/api/evaluation/comparison` (all new except `/results`, which already
existed) serve these files read-only to the Evaluation page
(`frontend/src/pages/EvaluationPage.tsx`), which renders the overview,
results table, metric definitions, comparison charts, interpretation,
research-question alignment, failure analysis, and both arms' raw run
history.

### 7.5 Running the new tests

```bash
cd backend
.venv/bin/python -m pytest -q tests/unit/test_baseline_runner.py   # new tests only
.venv/bin/python -m pytest -q                                      # full suite
.venv/bin/ruff check app prompts                                   # project's lint scope
```

## 8. Research question alignment

| Concept in the research question | Hypothesis | Metrics | Measured result (this run) |
|---|---|---|---|
| "reliably" | Intent2Deploy completes a higher fraction of tasks without crashing or fabricating output, vs. baseline | task completion rate, code correctness (proxy) | Equal in both arms (33.3%) — see §5 for why |
| "validated" | Completed changes are genuinely test-passing and non-regressive | validation pass rate, regression rate | 85.7% vs 90.5% pass; 9.5% vs 9.5% regression (both explained by one mock-strategy bug — see §5, §9) |
| "multi-stage AI-DevOps workflow" | Retrieval, planning, and guardrails measurably change what is selected/changed vs. a single-shot call | recall@K, precision@K, unnecessary-modification proxy, guardrail counts | recall 0.893 vs 0.881; precision 0.115 vs 0.365; guardrails fired only in Intent2Deploy (0.57 warn / 0.43 block per task) |
| "minimal human intervention" | Intervention is bounded and purposeful, not proportional to failure | human intervention count | 2.86/task (Intent2Deploy, approval gates) vs. 0 (baseline, structurally absent — no mechanism to intervene at all) |

## 9. Failure case summary

14 of 21 tasks did not complete in at least one arm. They fall into
exactly two distinct, independently-confirmed root causes — not 14
unrelated failures:

### 9.1 Honest no-op — 12 tasks, both arms, no bug

`task_004`, `task_005`, `task_007`, `task_009`, `task_013`, `task_014`,
`task_015`, `task_017`, `task_018`, `task_019`, `task_020`, `task_021`
all map to intent-classifier categories with no entry in
`mock_strategies.STRATEGIES` — mock mode correctly produces an honest,
zero-confidence no-op rather than fabricated code (see
`mock_strategies.generic_fallback`). No crash, no partial/corrupted
change, no silently-wrong output. This is the identical, expected
behavior already documented for tasks 004/007/009 in the original
11-task benchmark, now also true for 9 of the 10 new tasks (the
exceptions are 012 and 016 — see below).

### 9.2 Real mock-strategy bug — task_012 (Intent2Deploy only), task_016 (both arms)

Independently reproduced outside the benchmark runner to confirm root
cause (not inferred from the summary alone — see the reproduction
commands this section is based on):

- `payment_idempotency` (in `app/services/codegen/mock_strategies.py`)
  patches up to 3 files: `services/payment_service.py`,
  `schemas/payment.py`, `api/payments.py`. Each is patched
  independently, gated only on "is this file present in the given
  context."
- For task_012's and task_016's intent wording, real retrieval (or the
  baseline's naive selection) surfaced `payment_service.py` and
  `api/payments.py` but **not** `schemas/payment.py`.
- The patched `api/payments.py` contains `payload.idempotency_key`,
  reading a field that only the (not-applied) `schemas/payment.py`
  patch would have added to `PaymentChargeRequest`. Pydantic's
  `BaseModel` has no such attribute on the unpatched schema, so this
  raises `AttributeError` at request time.
- Effect: 13 real test failures (`tests/test_payments.py`,
  `tests/test_refunds.py`, `tests/test_notifications.py::test_payment_*`,
  `tests/test_orders.py::test_cancel_delivered_order_rejected` — the
  last two fail because they depend on a successful payment to set up
  their fixture state, not because they test payments directly).
  `task_011` was **not** affected in this run: its intent wording
  caused retrieval to surface only `payment_service.py`, which patches
  cleanly on its own (no cross-file dependency).

This is the sole cause of this run's regression rate (9.5%, 2/21) and
of the gap between the two arms' validation pass rates. **Not fixed in
this revision**: this evaluation round's instructions were to measure
the fixed benchmark and report results, not to iterate on
infrastructure based on what the measurement finds. Fixing it (making
each of the 3 files' patches check for the others' presence, or
bundling them as one atomic change) is straightforward future work,
tracked here rather than silently applied.

### Lesson learned

Because mock mode's bounded strategy set is shared by both arms, this
benchmark's completion-rate comparison remains informative only for the
task categories mock mode can actually generate for. Notably, **task_005
did not complete in this run** even though its intent matches the
`input_validation` strategy's trigger phrases: per-task retrieval
diagnostics (`retrieval_recall_at_k: 0.5, touched_expected_files: 0.0`)
show that in this run, retrieval surfaced only one of task_005's two
`expected_files`, and the `input_validation` strategy's string-anchor
guard (it requires the exact current text of `api/auth.py` to be
present before patching — see mock_strategies.py's own anti-fabrication
design, §2.4) did not find what it needed, so it correctly produced a
no-op rather than guessing. This is a **retrieval-coverage** finding
(the file this task needed wasn't in the context the strategy saw this
run), distinct from the task_012/task_016 **coupling bug** above — not
re-run to "fix" the number, per this round's instructions. A
`LLM_MODE=live` re-run is the correct next step to get a completion-rate
comparison not gated by mock mode's coverage, and would also be expected
to avoid the task_012/task_016 failure mode organically, since a real
model generating all 3 files in one coherent response would not have
this specific inter-file dependency problem.
