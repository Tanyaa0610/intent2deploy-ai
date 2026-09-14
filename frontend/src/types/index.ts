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
  timing_ms: Record<string, number | null>;
}
