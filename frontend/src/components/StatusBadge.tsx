type Tone = "neutral" | "accent" | "success" | "warn" | "danger";

const STATE_TONE: Record<string, Tone> = {
  CREATED: "neutral",
  INDEXING: "accent",
  INDEXED: "accent",
  PLANNING: "accent",
  PLAN_READY: "accent",
  AWAITING_PLAN_APPROVAL: "warn",
  PLAN_REJECTED: "danger",
  CHANGES_GENERATING: "accent",
  CHANGES_READY: "accent",
  AWAITING_CHANGE_APPROVAL: "warn",
  CHANGES_REJECTED: "danger",
  TESTS_GENERATING: "accent",
  VALIDATING: "accent",
  VALIDATION_FAILED: "danger",
  REPAIRING: "warn",
  VALIDATION_PASSED: "success",
  AWAITING_COMMIT_APPROVAL: "warn",
  COMMITTED: "success",
  CI_RUNNING: "accent",
  COMPLETED: "success",
  FAILED: "danger",
  passed: "success",
  failed: "danger",
  error: "danger",
  skipped: "neutral",
  pending: "neutral",
  // Guardrail Control Plane statuses/actions (uppercase, as returned by
  // GET /api/guardrails*).
  PASSED: "success",
  WARNING: "warn",
  BLOCKED: "danger",
  NOT_APPLICABLE: "neutral",
  NOT_IMPLEMENTED: "neutral",
  ALLOW: "success",
  WARN: "warn",
  REQUIRE_APPROVAL: "accent",
  BLOCK: "danger",
  ABORT: "danger",
  LOW: "neutral",
  MEDIUM: "accent",
  HIGH: "warn",
  CRITICAL: "danger",
  // Final-report evidence classification (Part 14).
  FACT: "success",
  INFERRED: "accent",
  ASSUMPTION: "warn",
  UNKNOWN: "neutral",
  UNVERIFIED: "danger",
  READY: "success",
  READY_WITH_WARNINGS: "warn",
  NOT_READY: "danger",
};

export function StatusBadge({ state }: { state: string }) {
  const tone = STATE_TONE[state] || "neutral";
  return (
    <span className={`status ${tone}`}>
      <span className="dot" />
      {state.replace(/_/g, " ")}
    </span>
  );
}
