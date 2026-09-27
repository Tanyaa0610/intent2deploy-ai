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
}
