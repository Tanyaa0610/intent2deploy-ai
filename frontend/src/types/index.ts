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
  base_branch: string;
  branch_name: string;
  state: string;
  created_at: string;
  updated_at: string;
  repair_attempts: number;
  human_intervention_count: number;
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
