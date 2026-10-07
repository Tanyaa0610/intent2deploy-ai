# Evaluation

## Research question

> How reliably can an LLM transform natural-language developer intent
> into a validated, multi-stage AI-DevOps workflow with minimal human
> intervention?

## Benchmark

`evaluation/tasks/task_001.json` … `task_021.json` — 21 tasks against the
single reproducible `demo-repository/` fixture (the ShopFlow API — see
`docs/EXPERIMENTAL_EVALUATION.md` for the repository migration), covering:
feature addition, bug fix, test generation, API modification,
validation/error handling, authentication/security, database/service
change, documentation/code-quality, regression-sensitive refactor,
general refactoring, reliability improvement, and observability/logging
(see `evaluation/README.md` for the full table).

Each task specifies `expected_files` (ground truth for retrieval
Precision@K/Recall@K) and `acceptance_criteria`. Every `expected_files`
path is verified to exist in the repository before each run.

## Runner

```bash
python scripts/run_evaluation.py
```

For each task, in order: index → plan → (auto-approve) → generate
changes → (auto-approve) → generate tests → validate → bounded repair if
needed → (auto-approve) → commit → finalize → report. Every checkpoint is
still recorded as a human-intervention event (auto-approval in an
unattended benchmark run still counts, for metric comparability with an
interactive run).

## Metrics computed (master spec §24)

All of the following are computed from the real persisted rows of that
run — see `scripts/run_evaluation.py`; none are hardcoded.

| Metric | How it's computed |
|---|---|
| Task Completion Rate | `completed / total`, where `completed` requires both `state == COMPLETED` **and** at least one applied change with confidence > 0 (a workflow that reaches COMPLETED with a no-op change is not counted as completed) |
| Validation Success Rate | fraction of tasks whose final validation attempt passed |
| Human Intervention Count | sum of `Workflow.human_intervention_count` |
| Repair Attempts | average of `Workflow.repair_attempts` |
| Execution Time | wall-clock time per task, `time.monotonic()` around the full run |
| Retrieval Precision@K / Recall@K | real set intersection of retrieved files vs. each task's `expected_files` ground truth |
| Unnecessary Modification Ratio (proxy) | `|changed_files - expected_files| / |changed_files|`, explicitly labeled a proxy since `expected_files` is a human-curated approximation of true scope, not ground truth |
| Regression Rate | real (not proxy): the pristine repository's test suite is collected once (`--collect-only`), and a task is counted as regressed only if a test that exists in that baseline set shows `FAILED` in the task's final `unit_tests` run |
| Resource Consumption | reported as `"Not available from provider"` in `LLM_MODE=mock`, since `LLMUsage.available=False` for the local provider; would report real token counts in `LLM_MODE=live` via `LLMUsage.prompt_tokens/completion_tokens` |

## Measured results (mock mode, this build, ShopFlow benchmark)

From `evaluation/results/run_20261007T104452Z.json` (real run, not
fabricated — reproduce with the command above against the current
21-task ShopFlow benchmark):

```
Tasks: 21
Completed: 7
Task Completion Rate: 33.3%
Validation Success Rate: 85.7%
Average Human Interventions: 2.86
Average Repair Attempts: 0.0
Average Execution Time: 3483ms/task
Retrieval Precision@K (avg): 0.115
Retrieval Recall@K (avg): 0.893
Unnecessary Modification Ratio (proxy, avg): 0.524
Regression Rate: 9.5%
Average Guardrail Warnings: 0.57
Average Guardrail Blocks: 0.43
```

### Interpretation

- **33.3% completion (7/21)**: the 11 migrated tasks (task_001–011)
  behave the same way the original 10/11-task benchmark did — 7 of them
  match one of the 5 grounded mock strategies and complete; the other 4
  (task_004, task_005, task_007, task_009) get an honest no-op, same as
  before. **All 10 new tasks (task_012–021) fail to complete** — this is
  expected and correctly honest, not a regression: mock mode's bounded
  strategy set was written for the original 5 scenarios and was not
  extended to cover the 10 new ones (see
  `docs/EXPERIMENTAL_EVALUATION.md` for which 2 of the 10 *do* produce a
  real, partially-working patch via the existing payment-idempotency
  strategy).
- **A real regression was found, not fabricated**: task_012 (Intent2Deploy
  arm) and task_016 (both arms) hit `VALIDATION_FAILED` with 13 real test
  failures (`AttributeError`) — the payment-idempotency mock strategy
  patches `payment_service.py`, `schemas/payment.py`, and `api/payments.py`
  independently per-file, but `api/payments.py`'s patched code depends on
  a field only `schemas/payment.py`'s patch adds. When retrieval surfaces
  the first two files but not the third, the result is syntactically
  valid but behaviorally broken. This is a genuine, newly-discovered
  limitation of that specific mock strategy, left unfixed and reported
  here rather than quietly patched, per this evaluation round's explicit
  scope (no feature changes during a benchmark run).
- **Retrieval precision dropped sharply (0.115 vs. the old benchmark's
  0.19)**: ShopFlow has far more files than the old fixture (~45 vs. ~8
  Python files), so `retrieve_multi(top_k=12)`'s fixed `top_k` now
  returns a much lower fraction of truly-relevant files for the same
  small `expected_files` ground truth sets — an expected, mechanical
  consequence of a larger repository, not a retrieval regression.
- **Regression rate 9.5% (2/21)**: both regressions are the task_012/
  task_016 inter-file-dependency bug above, not independent findings.

## Baseline comparison (master spec §25)

A human-developer baseline (read → search → modify → test → run → fix,
performed by a person) is still not automated here — doing so
meaningfully would require recruiting developers to complete the same
tasks under time pressure, out of scope for this project's resourcing.

An **automated, reproducible baseline** *is* now implemented:
`scripts/run_baseline_evaluation.py` runs a non-orchestrated, single-shot
LLM-assisted approach (same intent, a naive keyword-matched "basic
repository context," the same underlying LLM provider, no retrieval
pipeline, no planning stage, no approval checkpoints, no guardrails,
single validation run) against the same benchmark, and
`scripts/compare_evaluation_runs.py` computes a metric-for-metric
comparison against this document's own numbers above. See
`docs/EXPERIMENTAL_EVALUATION.md` for the full experimental design,
metric definitions, measured results, interpretation, and limitations —
including the honest finding that, in this `LLM_MODE=mock` benchmark
against the 21-task ShopFlow suite, task completion rate came out
identical between the two arms (33.3%, because both share the same
bounded mock code-generation core), the baseline's naive top-3 file
selection actually scored *higher* precision and a *lower* unnecessary-
modification ratio than Intent2Deploy's broader retrieval on this run,
and both arms independently hit the same real inter-file-dependency bug
in the payment-idempotency mock strategy (see above).

## Plan quality

`scripts/run_evaluation.py` does not currently score plan quality against
each task's `acceptance_criteria` (this would require either human rating
or a second LLM-as-judge call, both left as documented future work);
the plan JSON is however inspectable per-task in `Plan.acceptance_criteria_json`
alongside the task's own `acceptance_criteria` for manual comparison.
