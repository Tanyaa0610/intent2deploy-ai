# Evaluation Benchmark

21 developer tasks against the reproducible `demo-repository/` fixture
(the ShopFlow API — see `docs/EXPERIMENTAL_EVALUATION.md` for the
repository migration from the earlier, smaller fixture), covering every
category required by the master spec plus several additional
production-realistic scenarios.

Tasks 001–011 are a direct migration of the original 10/11-task
benchmark (same categories, same experimental intent, retargeted at
ShopFlow's real files); tasks 012–021 are new, added for this benchmark.

| ID | Title | Category | Difficulty |
|---|---|---|---|
| task_001 | Add a password-reset feature | feature_addition | medium |
| task_002 | Fix the null-reference bug in the order service | bug_fix | easy |
| task_003 | Add tests for the order service's missing-order edge case | test_generation | easy |
| task_004 | Add an endpoint to reactivate a deactivated user account | api_modification | easy |
| task_005 | Add input validation to the registration endpoint | validation_error_handling | easy |
| task_006 | Add session-token expiry | authentication_security | medium |
| task_007 | Invalidate sessions immediately on account deactivation | database_service_change | medium |
| task_008 | Improve documentation of the order service | documentation_code_quality | easy |
| task_009 | Refactor password hashing without changing behavior | regression_sensitive_refactor | medium |
| task_010 | Refactor the order service's internal data access | refactoring | medium |
| task_011 | Fix duplicate orders on payment-provider timeout | reliability_improvement | hard |
| task_012 | Add idempotency handling to payment retries | feature_addition | hard |
| task_013 | Add a low-stock notification when inventory falls below threshold | feature_addition | easy |
| task_014 | Prevent cancelling orders after shipment | bug_fix | easy |
| task_015 | Restrict inventory updates to administrators | authentication_security | easy |
| task_016 | Add retry handling for payment provider timeouts | reliability_improvement | medium |
| task_017 | Add structured logging for failed payments | observability_logging | easy |
| task_018 | Enforce a maximum quantity limit per product in the cart | validation_error_handling | easy |
| task_019 | Restore reserved inventory when an order is cancelled | bug_fix | medium |
| task_020 | Only allow refunds for successfully captured payments | bug_fix | easy |
| task_021 | Prevent failed payments from confirming an order | bug_fix | medium |

task_011 and task_012 deliberately target overlapping functionality
(payment idempotency) from differently-worded intents — this is
intentional, to test whether the system reasons consistently about the
same code regardless of phrasing; see `docs/EXPERIMENTAL_EVALUATION.md`.

Run the benchmark (Intent2Deploy arm):

```bash
python scripts/run_evaluation.py
```

Results land in `evaluation/results/run_<timestamp>.json` (gitignored —
regenerate locally; see `docs/evaluation.md` for a worked example run and
methodology).

### Baseline comparison

For the controlled baseline-vs-Intent2Deploy experiment (mid-term
evaluation), also run:

```bash
python scripts/run_baseline_evaluation.py   # non-orchestrated baseline arm
python scripts/compare_evaluation_runs.py   # comparison + interpretation + failure analysis
```

See `docs/EXPERIMENTAL_EVALUATION.md` for the full methodology, metric
definitions, measured results, and limitations. Both arms' results and
the comparison are also browsable on the frontend's Evaluation page.

## Task schema

```json
{
  "id": "task_001",
  "title": "...",
  "category": "...",
  "intent": "...",
  "repository": "demo-repository",
  "expected_files": ["..."],
  "acceptance_criteria": ["..."],
  "validation_commands": ["python3 -m pytest -q"],
  "difficulty": "easy|medium|hard"
}
```
