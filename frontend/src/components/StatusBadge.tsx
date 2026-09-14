const STATE_STYLE: Record<string, string> = {
  CREATED: "badge-neutral",
  INDEXING: "badge-accent",
  INDEXED: "badge-accent",
  PLANNING: "badge-accent",
  PLAN_READY: "badge-accent",
  AWAITING_PLAN_APPROVAL: "badge-warn",
  PLAN_REJECTED: "badge-danger",
  CHANGES_GENERATING: "badge-accent",
  CHANGES_READY: "badge-accent",
  AWAITING_CHANGE_APPROVAL: "badge-warn",
  CHANGES_REJECTED: "badge-danger",
  TESTS_GENERATING: "badge-accent",
  VALIDATING: "badge-accent",
  VALIDATION_FAILED: "badge-danger",
  REPAIRING: "badge-warn",
  VALIDATION_PASSED: "badge-success",
  AWAITING_COMMIT_APPROVAL: "badge-warn",
  COMMITTED: "badge-success",
  CI_RUNNING: "badge-accent",
  COMPLETED: "badge-success",
  FAILED: "badge-danger",
  passed: "badge-success",
  failed: "badge-danger",
  error: "badge-danger",
  skipped: "badge-neutral",
  pending: "badge-neutral",
};

export function StatusBadge({ state }: { state: string }) {
  const cls = STATE_STYLE[state] || "badge-neutral";
  return <span className={`badge ${cls}`}>{state.replace(/_/g, " ")}</span>;
}
