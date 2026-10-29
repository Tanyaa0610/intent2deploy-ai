export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface Repository {
  id: string;
  project_id: string;
  source: string;
  local_path: string;
  indexed_at: string | null;
  file_count: number;
  chunk_count: number;
}

export interface Workflow {
  id: string;
  project_id: string;
  repository_id: string;
  intent: string;
  revision_of?: string | null; // set when this workflow fixes a problem reported on another one
  revision_note?: string;
  revision_attachments?: string; // JSON list of screenshot file names
  revision_addons?: string; // JSON list of add-on ids
  base_branch: string;
  branch_name: string;
  state: string;
  created_at: string;
  updated_at: string;
  repair_attempts: number;
  human_intervention_count: number;
  // "greenfield": the repository had no usable source code, so the project is
  // designed and generated from scratch (see greenfield_design_json).
  project_mode?: "existing" | "greenfield";
  greenfield_design_json?: string;
  failed_from?: string;
  indexing_ms: number | null;
  retrieval_ms: number | null;
  planning_ms: number | null;
  codegen_ms: number | null;
  testgen_ms: number | null;
  validation_ms: number | null;
  total_ms: number | null;
}

export interface PlanStep {
  id: string;
  description: string;
  files: string[];
}

export interface PlanDetail {
  id: string;
  summary: string;
  assumptions: string[];
  acceptance_criteria: string[];
  steps: PlanStep[];
  files_likely_to_change: string[];
  dependencies: string[];
  test_strategy: string[];
  risks: string[];
  prompt_version: string;
  approved: boolean | null;
  approval_comment: string;
}

export interface ProposedChangeItem {
  id: string;
  file: string;
  operation: string;
  reason: string;
  patch: string;
  confidence: number;
  risks: string[];
  acceptance_criterion: string;
}

export interface GeneratedTestItem {
  id: string;
  file: string;
  content: string;
  rationale: string;
  category: string;
}

export interface ValidationResultItem {
  stage: string;
  status: string;
  duration_ms: number;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  attempt: number;
  command: string;
}

export interface RetrievalEvidenceItem {
  file: string;
  start_line: number;
  end_line: number;
  score: number;
  reason: string;
  chunk_type: string;
  symbol: string;
  retrieval_method: string;
  content_preview: string;
}

export interface AuditEventItem {
  event_type: string;
  stage: string;
  message: string;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface RepairAttemptItem {
  id: string;
  attempt_number: number;
  diagnosis: string;
  repair_patch: string;
  approved: boolean | null;
  result: string;
}

export interface PipelineStage {
  name: string;
  status: string;
  timestamp: string | null;
  duration_ms: number | null;
  input: string;
  output: string;
  evidence: string[];
  approval_state: string | null;
  guardrails_triggered: { guardrail_id: string; name: string; status: string }[];
}

export const GUARDRAIL_CATEGORIES = [
  "SECURITY",
  "INFRASTRUCTURE",
  "CI_CD",
  "DEPLOYMENT",
  "COST",
  "AI_LLM",
  "INPUT",
  "OUTPUT",
] as const;

export type GuardrailCategory = (typeof GUARDRAIL_CATEGORIES)[number];

export interface GuardrailCatalogItem {
  guardrail_id: string;
  category: string;
  name: string;
  severity: string;
}

export interface GuardrailCheckItem {
  id: string;
  workflow_id: string;
  guardrail_id: string;
  category: string;
  name: string;
  description: string;
  purpose: string;
  trigger_condition: string;
  enforcement_point: string;
  severity: string;
  status: string;
  action: string;
  evidence: string[];
  remediation: string;
  configurable_threshold: string;
  enabled: boolean;
  created_at: string;
  evaluated_at: string;
}

export interface GuardrailCategorySummary {
  total: number;
  passed: number;
  warnings: number;
  blocked: number;
  failed: number;
  not_applicable: number;
  not_implemented: number;
}

export interface GuardrailSummary {
  has_data: boolean;
  categories: Record<string, GuardrailCategorySummary>;
  approval_required: number;
}

export interface GuardrailTimelineItem {
  guardrail_id: string;
  category: string;
  name: string;
  enforcement_point: string;
  status: string;
  action: string;
  severity: string;
  reason: string;
  evidence: string[];
  remediation: string;
  approval_required: boolean;
  evaluated_at: string;
}

export interface EvidenceClassificationItem {
  item: string;
  classification: "FACT" | "INFERRED" | "ASSUMPTION" | "UNKNOWN" | "UNVERIFIED";
  note: string;
}

export interface ReportTimelineStage {
  name: string;
  status: string;
  timestamp: string | null;
  duration_ms: number | null;
  input: string;
  output: string;
  evidence: string[];
  approval_state: string | null;
  guardrails_triggered: { guardrail_id: string; name: string; status: string }[];
}

export interface ReportGuardrailCheck {
  guardrail_id: string;
  category: string;
  name: string;
  description: string;
  purpose: string;
  trigger_condition: string;
  enforcement_point: string;
  severity: string;
  status: string;
  action: string;
  evidence: unknown[];
  remediation: string;
  configurable_threshold: string;
  evaluated_at: string;
}

export interface ReportRiskFull {
  risk_id: string;
  title: string;
  component: string;
  category: string;
  severity: string;
  likelihood: string;
  blast_radius: string;
  detection: string;
  existing_mitigation: string;
  recommended_mitigation: string;
  validation_method: string;
  status: string;
  evidence: unknown[];
  source: string;
}

export interface ReportChaosScenario {
  experiment_id: string;
  scenario: string;
  failure_injected: string;
  hypothesis: string;
  expected_behavior: string;
  actual_behavior: string;
  result: string;
  environment: string;
  evidence: unknown[];
  timestamp: string;
}

export interface ReportValidationRun {
  stage: string;
  status: string;
  attempt: number;
  command: string;
  exit_code: number | null;
  duration_ms: number;
  stdout: string;
  stderr: string;
  timestamp: string;
}

export interface ReportTestItem {
  file: string;
  category: string;
  rationale: string;
  test_functions: string[];
  content: string;
  executed: boolean;
  execution_note: string;
}

export interface ReportFileChange {
  file: string;
  action: string;
  reason: string;
  evidence: string;
  validation: string;
}

export interface ReportTestEvidence {
  test: string;
  file: string;
  purpose: string;
  category: string;
  result: string;
  evidence: string;
}

export interface ReportApproval {
  checkpoint: string;
  timestamp: string;
  decision: string;
  comment: string;
  resulting_action: string;
}

export interface ReportLimitation {
  category: string;
  note: string;
}

export interface ReportProposedChangeFull {
  file: string;
  operation: string;
  reason: string;
  confidence: number;
  acceptance_criterion?: string;
  risks: string[];
  patch: string;
  status?: string;
}

export interface FinalReport {
  workflow_id: string;
  intent: string;
  final_status: string;
  repository: string;
  executive_summary: string;
  plan: {
    summary: string;
    acceptance_criteria: string[];
    steps: PlanStep[];
    risks: string[];
    approved: boolean | null;
  } | null;
  evidence: RetrievalEvidenceItem[];
  changes: { file: string; operation: string; reason: string; confidence: number }[];
  tests: { file: string; rationale: string; category: string }[];
  validation_results: { stage: string; status: string; attempt: number; duration_ms: number }[];
  final_validation: string | null;
  repair_attempts: number;
  repairs: { attempt_number: number; diagnosis: string; result: string }[];
  human_intervention_count: number;
  git_operations: { operation: string; detail: string; ref: string }[];
  audit_trail: { event_type: string; stage: string; timestamp: string }[];
  risks: { risk_id: string; title: string; component: string; severity: string; status: string; source: string }[];
  guardrails: {
    total: number;
    passed: number;
    warnings: number;
    blocked: number;
    failed: number;
    by_category: Record<string, number>;
    blocking: { guardrail_id: string; name: string; category: string; reason: string }[];
  };
  production_readiness: { decision: string; reasons: string[] } | null;
  evidence_classification: EvidenceClassificationItem[];
  timing_ms: Record<string, number | null>;

  // --- expanded auditable report (additive; see backend app/services/reporting.py) ---
  report_metadata?: { report_version: string; generated_at: string; workflow_id: string; project_id: string; status: string; report_type: string };
  developer_intent?: { text: string; submitted_at: string; base_branch: string; test_command: string; build_command: string; environment: string };
  workflow_summary?: {
    final_status: string;
    total_duration_ms: number | null;
    human_intervention_count: number;
    repair_attempts: number;
    production_readiness_decision: string;
    final_validation: string;
    requested_change_succeeded: boolean;
  };
  intent_understanding?: { classified_category: string; classification_method: string; confidence: string; note: string; interpreted_problem: string };
  production_context?: { repository_source: string; repository_local_path: string; environment: string; file_count: number | null; chunk_count: number | null; indexed_at: string | null };
  repository_indexing?: { status: string; files_indexed: number | null; chunks_created: number | null; vector_store: string; indexing_duration_ms: number | null; indexed_at: string | null; warnings: string[] };
  repository_rag?: { query: string; retrieval_duration_ms: number | null; files_retrieved: string[]; chunk_count_retrieved: number; evidence: RetrievalEvidenceItem[]; limitations: string[] };
  architecture_analysis?:
    | { components: { name: string; path: string; files: string[]; functions: number; classes: number }[]; external_dependencies: string[]; total_files: number; total_functions: number; total_classes: number }
    | { error: string; detail: string };
  risk_analysis?: ReportRiskFull[];
  engineering_plan?:
    | {
        summary: string;
        assumptions: string[];
        acceptance_criteria: string[];
        steps: PlanStep[];
        files_likely_to_change: string[];
        dependencies: string[];
        test_strategy: string[];
        risks: string[];
        rollback_strategy: string;
        constraints: string;
        prompt_version: string;
        created_at: string;
        approved: boolean | null;
        approval_comment: string;
      }
    | null;
  plan_approval?: { status: string; timestamp: string | null; comment: string; human_intervention_count: number };
  code_generation?: {
    applied: boolean;
    files_modified: ReportProposedChangeFull[];
    files_proposed_not_applied: ReportProposedChangeFull[];
    retrieved_read_only_files: string[];
  };
  change_approval?: {
    status: string;
    timestamp: string | null;
    comment: string;
    human_intervention_count: number;
    files_approved: string[];
    all_decisions: { approved: boolean; comment: string; timestamp: string }[];
  };
  test_generation?: { status: string; generation_duration_ms: number | null; count: number; generated_at: string | null; tests: ReportTestItem[] };
  resilience_testing?: { status: string; scenarios: ReportChaosScenario[] };
  chaos_simulation?: { status: string; pass_count: number; applicable_count: number; total_count: number; scenarios: ReportChaosScenario[]; limitations: string[] };
  guardrails_full?: {
    total: number;
    passed: number;
    warnings: number;
    blocked: number;
    failed: number;
    not_applicable: number;
    approval_required: number;
    by_category: Record<string, number>;
    altered_execution: boolean;
    checks: ReportGuardrailCheck[];
  };
  validation?: { final_result: string; repair_triggered: boolean; attempts: number[]; runs: ReportValidationRun[]; duration_ms: number | null };
  ai_repair?: {
    triggered: boolean;
    attempt_count: number;
    attempts: { attempt_number: number; diagnosis: string; repair_patch: string; approved: boolean | null; result: string; timestamp: string }[];
    final_result?: string;
    reason?: string;
  };
  production_readiness_full?: { decision: string; reasons: string[]; checklist: Record<string, string>; assessed_at: string | null };
  ci_cd?: { applicable: boolean; status: string; detail: string; evaluated_at?: string };
  github_pr?: {
    branch: string;
    branch_created: boolean;
    commit: { status: string; detail?: string; ref?: string; timestamp?: string };
    push: { status: string; detail?: string; ref?: string; timestamp?: string };
    pull_request: { status: string; detail?: string; ref?: string; timestamp?: string };
    ci_status: string;
    configured: boolean;
    all_operations: { operation: string; detail: string; ref: string; approved: boolean; timestamp: string }[];
    note?: string;
  };
  final_outcome?: {
    requested_change_succeeded: boolean;
    final_status: string;
    files_changed: string[];
    final_validation: string;
    final_readiness_decision: string;
    remaining_open_risks: { risk_id: string; title: string; severity: string }[];
    repair_attempts: number;
    human_intervention_count: number;
    total_duration_ms: number | null;
  };
  timeline?: ReportTimelineStage[];
  file_change_summary?: ReportFileChange[];
  test_evidence?: ReportTestEvidence[];
  guardrail_evidence?: { category: string; check: string; result: string; action: string; evidence: unknown[] }[];
  risk_readiness_summary?: { risk: string; severity: string; detection: string; mitigation: string; final_status: string }[];
  approvals?: ReportApproval[];
  limitations?: ReportLimitation[];
}

// --- Baseline vs. Intent2Deploy experimental evaluation -------------------
// Shapes match scripts/compare_evaluation_runs.py's JSON output exactly;
// see docs/EXPERIMENTAL_EVALUATION.md for the methodology.

// --- Workflow-specific evaluation (faculty framework, 7 fixed categories) -
// Shape matches backend/app/services/workflow_evaluation.py exactly; see
// GET /api/workflows/{id}/evaluation. Distinct from the multi-task
// baseline-vs-Intent2Deploy benchmark types below.

export type EvaluationCategoryKey =
  | "explanation"
  | "code_retrieval"
  | "dependency_understanding"
  | "bug_analysis"
  | "code_generation"
  | "refactoring"
  | "rag_based_question";

export interface EvaluationCriterion {
  label: string;
  result: string; // "met" | "not met" | "N/A" | "XX% met"
  weight: number;
}

export interface EvaluationCategoryResult {
  status: "evaluated" | "not_applicable" | "not_evaluated";
  score: number | null;
  is_partial: boolean;
  criteria: EvaluationCriterion[];
  metrics: Record<string, string | number>;
  independent_checks: Record<string, string>;
  evidence: Record<string, unknown>;
  note: string;
}

export interface MetricStatusEntry {
  metric: string;
  status: "measured" | "evidence-based" | "ground_truth_dependent" | "unavailable";
  value: string | number;
  evidence: string;
}

export interface EvaluationMetricsSummary {
  measured_count: number;
  evidence_based_count: number;
  ground_truth_dependent_count: number;
  unavailable_count: number;
  measured: string[];
  ground_truth_dependent: string[];
  unavailable: string[];
}

export interface GuardrailMetrics {
  total: number;
  passed: number;
  warnings: number;
  blocked: number;
  failed: number;
  not_applicable: number;
  approval_required: number;
  by_category: Record<string, number>;
  regression_gate: string;
  note?: string;
}

export interface TokenUsage {
  prompt_tokens: string;
  completion_tokens: string;
  total_tokens: string;
  note: string;
  estimated_proxy?: {
    llm_calls: number;
    estimated_tokens: number;
    estimated_cost_usd: number;
    note: string;
  };
}

export interface WorkflowEvaluation {
  workflow_id: string;
  status: string;
  available: boolean;
  evaluated_at: string | null;
  message: string | null;
  overall_score: number | null;
  overall_score_message?: string | null;
  evaluated_categories: number;
  total_categories?: number;
  categories: Partial<Record<EvaluationCategoryKey, EvaluationCategoryResult>>;
  evidence: {
    developer_intent?: string;
    repository?: string;
    final_status?: string;
    final_validation?: string | null;
    total_duration_ms?: number | null;
  };
  measurement_limitations: string[];
  token_usage: TokenUsage;
  latency_breakdown: Record<string, number>;
  guardrail_metrics: GuardrailMetrics;
  metric_status: MetricStatusEntry[];
  metrics_summary: EvaluationMetricsSummary;
}

export interface ComparisonMetricRow {
  metric: string;
  field: string;
  unit: string;
  formula: string;
  data_source: string;
  interpretation_note: string;
  baseline: number | null;
  intent2deploy: number | null;
  absolute_difference: number | null;
  percent_improvement: number | null;
}

export interface FailureCase {
  task_id: string;
  title: string;
  category: string;
  baseline_completed: boolean | null;
  intent2deploy_completed: boolean | null;
  baseline_failure_reason: string | null;
  intent2deploy_failure_reason: string | null;
  baseline_result: Record<string, unknown> | null;
  intent2deploy_result: Record<string, unknown> | null;
}

export interface ResearchQuestionAlignmentRow {
  concept: string;
  hypothesis: string;
  metrics: string[];
  result: string;
}

export interface ExperimentComparison {
  available: boolean;
  message?: string;
  research_question?: string;
  generated_at?: string;
  baseline_run_file?: string;
  intent2deploy_run_file?: string;
  tasks_total_baseline?: number;
  tasks_total_intent2deploy?: number;
  comparison_table?: ComparisonMetricRow[];
  failure_analysis?: FailureCase[];
  interpretation?: string[];
  research_question_alignment?: ResearchQuestionAlignmentRow[];
  statistical_note?: string;
}

// ---- New types for the interactive control centre upgrade ----

export interface PlanStepUpdate {
  id: string;
  description: string;
  files: string[];
}

export interface DashboardSummary {
  active_workflows: number;
  completed_workflows: number;
  failed_workflows: number;
  awaiting_approval: number;
  validation_pass_rate: number | null;
  production_readiness: Record<string, number> | null;
  human_interventions: number;
  guardrail_violations: number;
  avg_execution_time_ms: number | null;
  avg_repair_attempts: number | null;
  has_data: boolean;
}

export interface AttentionItem {
  id: string;
  intent: string;
  state: string;
  project_name: string;
  repository_name: string;
  updated_at: string;
  repair_attempts: number;
  human_intervention_count: number;
  awaiting_action: string | null;
}

export interface DashboardAttention {
  attention: AttentionItem[];
  recent_completed: AttentionItem[];
}

// ---------------------------------------------------------------------------
// Repository Manager
// ---------------------------------------------------------------------------
export type RepoStatus = "cloning" | "indexing" | "syncing" | "ready" | "error" | "disconnected";

export interface ManagedRepository {
  id: string;
  project_id: string;
  name: string;
  kind: "local" | "github" | "created";
  source: string;
  local_path: string;
  remote_url: string;
  is_private: boolean;
  status: RepoStatus;
  status_detail: string;
  connected_at: string | null;
  indexed_at: string | null;
  file_count: number;
  chunk_count: number;
  source_file_count: number;
  accessible: boolean;
  is_git: boolean;
  branch: string | null;
  head: string | null;
  dirty: boolean | null;
  workflow_count: number;
  last_workflow_at: string | null;
}

export interface RepoTreeEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size: number | null;
  ignored: boolean;
  restricted: boolean;
}

export interface RepoFile {
  path: string;
  size: number;
  language: string;
  lines: number;
  content: string;
}

export interface RepoTextMatch {
  file: string;
  line: number;
  text: string;
}

export interface RepoInsights {
  indexed: boolean;
  indexed_at?: string;
  chunks?: number;
  files?: number;
  symbols?: number;
  languages?: { language: string; files: number }[];
  chunk_types?: { type: string; count: number }[];
  largest_files?: { file: string; chunks: number }[];
}

export interface RiskItem {
  risk_id: string;
  title: string;
  component: string;
  severity: string;
  likelihood: string;
  blast_radius: string;
  detection: string;
  mitigation: string;
  validation_method: string;
  status: string;
  evidence: string[];
  source: string;
}

export interface GreenfieldDesign {
  project_name: string;
  summary: string;
  requirements: string[];
  non_functional: string[];
  acceptance_criteria: string[];
  stack: string;
  components: { name: string; responsibility: string; files: string[] }[];
  files: { path: string; purpose: string }[];
  dependencies: string[];
  test_command: string;
  run_command: string;
  risks: string[];
  template: string;
}

export interface CheckDetails {
  name: string;
  event: string;
  status: string;
  conclusion: string;
  url: string;
  seconds?: number | null;
  steps: { number?: number; name: string; status: string; conclusion: string; seconds: number | null }[];
  sections: { title: string; output: string[] }[];
  tests: { name: string; outcome: string }[];
  test_summary: string;
  logs_available: boolean;
}

export interface PreviewInfo {
  running: boolean;
  mode?: "docker" | "python";
  url?: string;
  open_url?: string;
  port?: number;
  comment_url?: string;
  comment_error?: string;
  branch?: string;
  sha?: string;
  exit_code?: number | null;
  log?: string[];
  // Zero-downtime deployment status
  strategy?: string;
  release?: number | null;
  standby?: boolean;
  previous?: { sha: string; number: number; warm: boolean; warm_until: number | null } | null;
  monitor?: DeploymentMonitor;
  traffic?: { requests: number; failovers: number; server_errors: number; unavailable: number };
  releases?: ReleaseSummary[];
  last_release?: ReleaseSummary | null;
}

export interface DeploymentMonitor {
  enabled: boolean;
  interval_seconds: number;
  checks: number;
  ok: number;
  availability: number | null;
  consecutive_failures: number;
  last_check: number | null;
  last_latency_ms: number | null;
  down_since: number | null;
  incidents: { at: number; text: string }[];
}

export interface ReleaseSummary {
  number: number;
  branch: string;
  sha: string;
  status: "candidate" | "live" | "previous" | "blocked" | "retired";
  created_at: number;
  reason: string;
  checks: { stage: string; status: string; report: string }[];
}

export interface AlertItem {
  id: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  source: string;
  deployment: string;
  workflow_id: string | null;
  title: string;
  detail: string;
  acknowledged: boolean;
  delivered_to: string;
  created_at: string;
}

export type AlertCounts = { CRITICAL: number; WARNING: number; INFO: number };


/** A built-in upgrade that can be applied to code on staging without an AI model. */
export interface AddOnItem {
  id: string;
  title: string;
  description: string;
  status: "available" | "applied" | "not_supported";
}
