# Evaluation Benchmark

10 developer tasks against the reproducible `demo-repository/` fixture,
covering every category required by the master spec.

| ID | Title | Category | Difficulty |
|---|---|---|---|
| task_001 | Add a password-reset feature | feature_addition | medium |
| task_002 | Fix the null-reference bug in the order service | bug_fix | easy |
| task_003 | Add tests for the order service's missing-order edge case | test_generation | easy |
| task_004 | Add an endpoint to cancel an order | api_modification | medium |
| task_005 | Add input validation to the registration endpoint | validation_error_handling | easy |
| task_006 | Add session-token expiry | authentication_security | medium |
| task_007 | Add the ability to deactivate a user account | database_service_change | medium |
| task_008 | Improve documentation of the order service | documentation_code_quality | easy |
| task_009 | Refactor password hashing without changing behavior | regression_sensitive_refactor | medium |
| task_010 | Refactor the order service's repository pattern | refactoring | medium |

Run the benchmark:

```bash
python scripts/run_evaluation.py
```

Results land in `evaluation/results/run_<timestamp>.json` (gitignored —
regenerate locally; see `docs/evaluation.md` for a worked example run and
methodology).

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
