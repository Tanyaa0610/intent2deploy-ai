# Evaluation

## Research question

> How reliably can an LLM transform natural-language developer intent
> into a validated, multi-stage AI-DevOps workflow with minimal human
> intervention?

## Benchmark

`evaluation/tasks/task_001.json` … `task_010.json` — 10 tasks against the
single reproducible `demo-repository/` fixture, covering: feature
addition, bug fix, test generation, API modification, validation/error
handling, authentication/security, database/service change,
documentation/code-quality, regression-sensitive refactor, and general
refactoring (see `evaluation/README.md` for the full table).

Each task specifies `expected_files` (ground truth for retrieval
Precision@K/Recall@K) and `acceptance_criteria`.

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

## Measured results (mock mode, this build)

From `evaluation/results/run_20260914T105550Z_summary.md` (real run,
not fabricated — reproduce with the command above):

```
Tasks: 10
Completed: 7
Task Completion Rate: 70%
Validation Success Rate: 100%
Average Human Interventions: 3.0
Average Repair Attempts: 0.0
Average Execution Time: ~1.1s/task
Retrieval Precision@K (avg): 0.19
Retrieval Recall@K (avg): 1.0
Unnecessary Modification Ratio (proxy, avg): 0.0
Regression Rate: 0%
```

### Interpretation

- **100% validation success but 70% completion**: three tasks (API
  modification, database/service change, regression-sensitive refactor)
  reached `COMPLETED` because mock mode's fallback correctly produced
  *no* change rather than a fabricated one — validation trivially
  "passes" because nothing was touched. This is the intended honest
  behavior described in `docs/ai-testing-tools.md`: mock mode supports a
  bounded set of intent patterns, and the evaluation framework is
  designed to expose that boundary rather than hide it.
- **Recall@K = 1.0, Precision@K = 0.19**: retrieval reliably finds every
  ground-truth file (`retrieve_multi(top_k=12)` is deliberately generous)
  but also returns many additional, lower-relevance files. A smaller
  `top_k` would trade recall for precision; this is documented rather
  than tuned away, since the plan/codegen stages already filter down to
  the top-ranked files that matter.
- **Regression rate 0%**: no task broke a previously-passing test in
  this run — expected, since the four working mock strategies are
  narrowly scoped, additive changes.

## Baseline comparison (master spec §25)

The "conventional developer workflow" baseline
(read → search → modify → test → run → fix) is not separately
automated in this build — doing so meaningfully would require recruiting
human developers to complete the same 10 tasks under time pressure, which
is out of scope for this project's resourcing. Instead, this document
reports the AI-assisted workflow's own measured numbers above without
claiming superiority over an unautomated baseline; the comparison
methodology (what would need to be measured, and how) is documented here
so it can be run as a follow-up study.

## Plan quality

`scripts/run_evaluation.py` does not currently score plan quality against
each task's `acceptance_criteria` (this would require either human rating
or a second LLM-as-judge call, both left as documented future work);
the plan JSON is however inspectable per-task in `Plan.acceptance_criteria_json`
alongside the task's own `acceptance_criteria` for manual comparison.
