import type {
  AuditEventItem,
  ExperimentComparison,
  FinalReport,
  GeneratedTestItem,
  GuardrailCatalogItem,
  GuardrailCheckItem,
  GuardrailSummary,
  GuardrailTimelineItem,
  PipelineStage,
  PlanDetail,
  Project,
  ProposedChangeItem,
  RepairAttemptItem,
  Repository,
  RetrievalEvidenceItem,
  ValidationResultItem,
  Workflow,
  WorkflowEvaluation,
} from "../types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => request<{ status: string; llm_provider: string; llm_mode: string; is_mock: boolean }>("/api/health"),

  createProject: (name: string) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  listProjects: () => request<Project[]>("/api/projects"),

  indexRepository: (project_id: string, path: string) =>
    request<Repository>("/api/repositories/index", { method: "POST", body: JSON.stringify({ project_id, path }) }),
  cloneRepository: (project_id: string, url: string) =>
    request<Repository>("/api/repositories/clone", { method: "POST", body: JSON.stringify({ project_id, url }) }),
  listRepositories: (project_id?: string) =>
    request<Repository[]>(`/api/repositories${project_id ? `?project_id=${project_id}` : ""}`),

  createWorkflow: (payload: {
    project_id: string;
    repository_id: string;
    intent: string;
    base_branch?: string;
    test_command?: string;
    build_command?: string;
  }) => request<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(payload) }),
  listWorkflows: (project_id?: string) =>
    request<Workflow[]>(`/api/workflows${project_id ? `?project_id=${project_id}` : ""}`),
  getWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),

  runIndexing: (id: string) => request<Workflow>(`/api/workflows/${id}/index`, { method: "POST" }),
  runPlanning: (id: string) => request<Workflow>(`/api/workflows/${id}/plan`, { method: "POST" }),
  getPlan: (id: string) => request<PlanDetail>(`/api/workflows/${id}/plan`),
  approvePlan: (id: string, approved: boolean, comment = "") =>
    request<Workflow>(`/api/workflows/${id}/approve-plan`, { method: "POST", body: JSON.stringify({ approved, comment }) }),

  generateChanges: (id: string) => request<Workflow>(`/api/workflows/${id}/generate-changes`, { method: "POST" }),
  getChanges: (id: string) => request<{ changes: ProposedChangeItem[] }>(`/api/workflows/${id}/changes`),
  approveChanges: (id: string, approved: boolean, comment = "") =>
    request<Workflow>(`/api/workflows/${id}/approve-changes`, { method: "POST", body: JSON.stringify({ approved, comment }) }),

  generateTests: (id: string) => request<Workflow>(`/api/workflows/${id}/generate-tests`, { method: "POST" }),
  getTests: (id: string) => request<{ tests: GeneratedTestItem[] }>(`/api/workflows/${id}/tests`),

  runValidation: (id: string) => request<Workflow>(`/api/workflows/${id}/validate`, { method: "POST" }),
  getValidation: (id: string) => request<{ results: ValidationResultItem[] }>(`/api/workflows/${id}/validation`),

  proposeRepair: (id: string) => request<RepairAttemptItem>(`/api/workflows/${id}/repair`, { method: "POST" }),
  approveRepair: (id: string, repair_id: string, approved: boolean) =>
    request<Workflow>(`/api/workflows/${id}/approve-repair`, { method: "POST", body: JSON.stringify({ repair_id, approved }) }),
  getRepairs: (id: string) => request<{ repairs: RepairAttemptItem[] }>(`/api/workflows/${id}/repairs`),

  approveCommit: (id: string, approved: boolean, comment = "") =>
    request<Workflow>(`/api/workflows/${id}/commit`, { method: "POST", body: JSON.stringify({ approved, comment }) }),
  completeWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}/complete`, { method: "POST" }),

  pushBranch: (id: string, approved: boolean) =>
    request<{ status: string; branch?: string }>(`/api/workflows/${id}/github/push`, { method: "POST", body: JSON.stringify({ approved }) }),
  createPR: (id: string, approved: boolean, title = "", body = "") =>
    request<{ status: string; url?: string; number?: number }>(`/api/workflows/${id}/github/pr`, {
      method: "POST",
      body: JSON.stringify({ approved, title, body }),
    }),
  getCIStatus: (id: string) =>
    request<{ provider: string; status: string; detail: string; url: string }>(`/api/workflows/${id}/github/ci`, { method: "POST" }),

  getEvents: (id: string) => request<{ events: AuditEventItem[] }>(`/api/workflows/${id}/events`),
  getEvidence: (id: string) => request<{ evidence: RetrievalEvidenceItem[] }>(`/api/workflows/${id}/evidence`),
  getReport: (id: string) => request<FinalReport>(`/api/workflows/${id}/report`),
  getReportMarkdownUrl: (id: string) => `${BASE_URL}/api/workflows/${id}/report.md`,
  getReportJsonUrl: (id: string) => `${BASE_URL}/api/workflows/${id}/report.json`,

  searchRepository: (repository_id: string, query: string, top_k = 8) =>
    request<{ results: RetrievalEvidenceItem[] }>("/api/repository/search", {
      method: "POST",
      body: JSON.stringify({ repository_id, query, top_k }),
    }),
  askRepository: (repository_id: string, question: string) =>
    request<{ answer: string; cited_files: string[]; evidence: RetrievalEvidenceItem[] }>("/api/repository/ask", {
      method: "POST",
      body: JSON.stringify({ repository_id, question }),
    }),

  getEvaluationResults: () => request<{ runs: unknown[] }>("/api/evaluation/results"),
  getBaselineResults: () => request<{ runs: unknown[] }>("/api/evaluation/baseline-results"),
  getEvaluationComparison: () => request<ExperimentComparison>("/api/evaluation/comparison"),
  getWorkflowEvaluation: (id: string) => request<WorkflowEvaluation>(`/api/workflows/${id}/evaluation`),

  getPipeline: (workflowId: string) =>
    request<{ workflow_id: string; stages: PipelineStage[] }>(`/api/workflows/${workflowId}/pipeline`),

  getReadiness: (workflowId: string) =>
    request<{ decision: string | null; reasons: string[]; checklist: Record<string, string>; created_at?: string }>(
      `/api/workflows/${workflowId}/readiness`
    ),

  getGuardrailCatalog: (category?: string) =>
    request<{ categories: string[]; guardrails: GuardrailCatalogItem[] }>(
      `/api/guardrails${category ? `?category=${encodeURIComponent(category)}` : ""}`
    ),
  getWorkflowGuardrails: (
    workflowId: string,
    filters: { category?: string; severity?: string; status?: string; checkpoint?: string } = {}
  ) => {
    const params = new URLSearchParams();
    if (filters.category) params.set("category", filters.category);
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.status) params.set("status", filters.status);
    if (filters.checkpoint) params.set("checkpoint", filters.checkpoint);
    const qs = params.toString();
    return request<{ guardrails: GuardrailCheckItem[] }>(`/api/guardrails/${workflowId}${qs ? `?${qs}` : ""}`);
  },
  getGuardrailSummary: (workflowId: string) => request<GuardrailSummary>(`/api/guardrails/${workflowId}/summary`),
  getGuardrailTimeline: (workflowId: string) =>
    request<{ timeline: GuardrailTimelineItem[] }>(`/api/guardrails/${workflowId}/timeline`),
  evaluateGuardrails: (workflowId: string) =>
    request<{ evaluated: GuardrailCheckItem[] }>(`/api/guardrails/${workflowId}/evaluate`, { method: "POST" }),
  approveGuardrail: (workflowId: string, checkId: string, approved: boolean, comment = "") =>
    request<GuardrailCheckItem>(`/api/guardrails/${workflowId}/approve`, {
      method: "POST",
      body: JSON.stringify({ check_id: checkId, approved, comment }),
    }),
};
