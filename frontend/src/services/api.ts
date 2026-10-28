import type {
  AddOnItem,
  AlertCounts,
  AlertItem,
  AuditEventItem,
  DashboardAttention,
  DashboardSummary,
  ExperimentComparison,
  FinalReport,
  GeneratedTestItem,
  GuardrailCatalogItem,
  GuardrailCheckItem,
  GuardrailSummary,
  CheckDetails,
  PreviewInfo,
  GuardrailTimelineItem,
  ManagedRepository,
  PipelineStage,
  PlanDetail,
  PlanStepUpdate,
  Project,
  ProposedChangeItem,
  RepairAttemptItem,
  RepoFile,
  RepoInsights,
  RepoTextMatch,
  RepoTreeEntry,
  Repository,
  RetrievalEvidenceItem,
  RiskItem,
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
  getDashboardSummary: () => request<DashboardSummary>("/api/dashboard/summary"),
  getDashboardAttention: () => request<DashboardAttention>("/api/dashboard/attention"),

  health: () => request<{ status: string; llm_provider: string; llm_mode: string; is_mock: boolean }>("/api/health"),

  createProject: (name: string) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  listProjects: () => request<Project[]>("/api/projects"),

  indexRepository: (project_id: string, path: string) =>
    request<Repository>("/api/repositories/index", { method: "POST", body: JSON.stringify({ project_id, path }) }),
  cloneRepository: (project_id: string, url: string) =>
    request<Repository>("/api/repositories/clone", { method: "POST", body: JSON.stringify({ project_id, url }) }),
  listRepositories: (project_id?: string) =>
    request<Repository[]>(`/api/repositories${project_id ? `?project_id=${project_id}` : ""}`),

  // Repository Manager
  getRepoRoots: () => request<{ roots: string[]; server_token_configured: boolean }>("/api/repositories/roots"),
  listManagedRepositories: () => request<ManagedRepository[]>("/api/repositories/managed"),
  getManagedRepository: (id: string) => request<ManagedRepository>(`/api/repositories/${id}/details`),
  createLocalRepository: (payload: { path: string; name?: string; git_init: boolean; readme: boolean; index: boolean }) =>
    request<ManagedRepository>("/api/repositories/create", { method: "POST", body: JSON.stringify(payload) }),
  connectLocalRepository: (payload: { path: string; name?: string; index: boolean }) =>
    request<ManagedRepository>("/api/repositories/connect-local", { method: "POST", body: JSON.stringify(payload) }),
  connectGitHubRepository: (payload: {
    url: string;
    branch?: string;
    private: boolean;
    token?: string;
    use_server_token?: boolean;
    index: boolean;
  }) => request<ManagedRepository>("/api/repositories/connect-github", { method: "POST", body: JSON.stringify(payload) }),
  reindexRepository: (id: string) => request<ManagedRepository>(`/api/repositories/${id}/reindex`, { method: "POST" }),
  syncRepository: (id: string, payload: { token?: string; use_server_token?: boolean; reindex?: boolean } = {}) =>
    request<ManagedRepository>(`/api/repositories/${id}/sync`, { method: "POST", body: JSON.stringify(payload) }),
  disconnectRepository: (id: string) =>
    request<{ status: string; removed_clone: boolean }>(`/api/repositories/${id}`, { method: "DELETE" }),
  getRepoTree: (id: string, path = "") =>
    request<{ path: string; entries: RepoTreeEntry[] }>(`/api/repositories/${id}/tree?path=${encodeURIComponent(path)}`),
  getWorkflowFile: (workflowId: string, path: string) =>
    request<RepoFile>(`/api/workflows/${workflowId}/file?path=${encodeURIComponent(path)}`),
  getRepoFile: (id: string, path: string) =>
    request<RepoFile>(`/api/repositories/${id}/file?path=${encodeURIComponent(path)}`),
  grepRepository: (id: string, q: string, caseSensitive = false) =>
    request<{ results: RepoTextMatch[]; truncated: boolean; files_scanned: number }>(
      `/api/repositories/${id}/grep?q=${encodeURIComponent(q)}&case_sensitive=${caseSensitive}`
    ),
  getRepoInsights: (id: string) => request<RepoInsights>(`/api/repositories/${id}/insights`),
  getRepoWorkflows: (id: string) => request<Workflow[]>(`/api/repositories/${id}/workflows`),

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
  deleteWorkflow: (id: string) =>
    request<{ deleted: string; records_removed: number; workspace_removed: boolean }>(`/api/workflows/${id}`, { method: "DELETE" }),

  resumeWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}/resume`, { method: "POST" }),
  // Report a problem found on staging: starts a follow-up workflow that fixes it.
  // If the code on staging already does what is asked, the answer says so (with evidence) instead.
  // `addons`: built-in upgrades to apply (ids from listAddons) — they work without an AI model.
  reviseWorkflow: (id: string, problem: string, screenshots: string[] = [], force = false, addons: string[] = []) =>
    request<
      | { already_satisfied: false; workflow: Workflow }
      | {
          already_satisfied: true;
          message: string;
          findings: { capability: string; present: boolean; evidence: string[] }[];
          upgrades: AddOnItem[];
        }
    >(`/api/workflows/${id}/revise`, { method: "POST", body: JSON.stringify({ problem, screenshots, force, addons }) }),
  listAddons: (id: string) => request<{ addons: AddOnItem[] }>(`/api/workflows/${id}/addons`),
  attachmentUrl: (id: string, name: string) => `${BASE_URL}/api/workflows/${id}/attachments/${encodeURIComponent(name)}`,
  listRevisions: (id: string) => request<Workflow[]>(`/api/workflows/${id}/revisions`),
  revisionCheck: (id: string) =>
    request<{
      checked: boolean;
      already_satisfied: boolean;
      findings: { capability: string; present: boolean; evidence: string[] }[];
    }>(`/api/workflows/${id}/revision-check`),
  runIndexing: (id: string) => request<Workflow>(`/api/workflows/${id}/index`, { method: "POST" }),
  runPlanning: (id: string) => request<Workflow>(`/api/workflows/${id}/plan`, { method: "POST" }),
  getPlan: (id: string) => request<PlanDetail>(`/api/workflows/${id}/plan`),
  updatePlan: (id: string, payload: Partial<{ summary: string; assumptions: string[]; acceptance_criteria: string[]; steps: PlanStepUpdate[]; files_likely_to_change: string[]; test_strategy: string[] }>) =>
    request<PlanDetail>(`/api/workflows/${id}/plan`, { method: "PATCH", body: JSON.stringify(payload) }),
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

  // Feature-branch delivery: publish branch + PR to main, status, update, gated merge.
  publishPR: (id: string, token = "") =>
    request<{ number: number; url: string; base: string; head: string; repository: string; initialized_base: boolean }>(
      `/api/workflows/${id}/github/publish`,
      { method: "POST", body: JSON.stringify({ token }) }
    ),
  getPRStatus: (id: string, token = "") =>
    request<{
      published: boolean;
      repository: string;
      base: string;
      head: string;
      number?: number;
      url?: string;
      title?: string;
      state?: string;
      merge_sha?: string;
      head_sha?: string;
      mergeable_state?: string;
      checks?: { id: number; name: string; event: string; status: string; conclusion: string; url: string }[];
      checks_summary?: { total: number; pending: number; failed: number; passed: number };
      local_validation_passed?: boolean;
      viewer?: string;
      viewer_can_merge?: boolean;
      blockers?: string[];
      needs_token?: boolean;
      can_merge?: boolean;
    }>(`/api/workflows/${id}/github/pr/status`, { method: "POST", body: JSON.stringify({ token }) }),
  getCheckDetails: (id: string, checkId: number, token = "") =>
    request<CheckDetails>(`/api/workflows/${id}/github/checks/${checkId}`, { method: "POST", body: JSON.stringify({ token }) }),
  // Staging: preview the integration branch, then release it to main.
  previewStart: (id: string, token = "") =>
    request<PreviewInfo>(`/api/workflows/${id}/github/preview/start`, { method: "POST", body: JSON.stringify({ token }) }),
  previewInfo: (id: string) => request<PreviewInfo>(`/api/workflows/${id}/github/preview`),
  previewStop: (id: string) => request<PreviewInfo>(`/api/workflows/${id}/github/preview/stop`, { method: "POST" }),
  previewRollback: (id: string) => request<PreviewInfo>(`/api/workflows/${id}/github/preview/rollback`, { method: "POST" }),
  // Alerts and live deployment monitoring
  listAlerts: (openOnly = false) =>
    request<{ alerts: AlertItem[]; open: AlertCounts }>(`/api/alerts?open_only=${openOnly}`),
  ackAlert: (alertId: string) => request<{ open: AlertCounts }>(`/api/alerts/${alertId}/ack`, { method: "POST" }),
  ackAllAlerts: () => request<{ acknowledged: number; open: AlertCounts }>("/api/alerts/ack-all", { method: "POST" }),
  listDeployments: () => request<{ deployments: (PreviewInfo & { key: string })[] }>("/api/deployments"),
  releaseOpen: (id: string, token = "") =>
    request<{ number: number; url: string; base: string; head: string; commits: string[] }>(
      `/api/workflows/${id}/github/release/open`,
      { method: "POST", body: JSON.stringify({ token }) }
    ),
  releaseStatus: (id: string, token = "") =>
    request<Awaited<ReturnType<typeof api.getPRStatus>>>(`/api/workflows/${id}/github/release/status`, {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  releaseMerge: (id: string, approved: boolean, verified_on_staging: boolean, comment = "", token = "") =>
    request<{ status: string; number: number; merge_sha: string; url: string }>(`/api/workflows/${id}/github/release/merge`, {
      method: "POST",
      body: JSON.stringify({ approved, verified_on_staging, comment, token }),
    }),
  updatePRBranch: (id: string, token = "") =>
    request<{ status: string; detail: string }>(`/api/workflows/${id}/github/update-branch`, {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  mergePR: (id: string, approved: boolean, comment = "", token = "") =>
    request<{ status: string; number: number; merge_sha: string; base: string; url: string }>(
      `/api/workflows/${id}/github/merge`,
      { method: "POST", body: JSON.stringify({ approved, comment, token }) }
    ),
  getGitHubTarget: (id: string) =>
    request<{ configured: boolean; repository: string | null; url: string | null; source: string | null; server_token: boolean; branch: string }>(
      `/api/workflows/${id}/github/target`
    ),
  pushBranch: (id: string, approved: boolean, token = "") =>
    request<{ status: string; branch?: string; repository?: string; url?: string }>(`/api/workflows/${id}/github/push`, {
      method: "POST",
      body: JSON.stringify({ approved, token }),
    }),
  createPR: (id: string, approved: boolean, title = "", body = "", token = "") =>
    request<{ status: string; url?: string; number?: number }>(`/api/workflows/${id}/github/pr`, {
      method: "POST",
      body: JSON.stringify({ approved, title, body, token }),
    }),
  getCIStatus: (id: string, token = "") =>
    request<{ provider: string; status: string; detail: string; url: string; repository?: string | null }>(
      `/api/workflows/${id}/github/ci`,
      { method: "POST", body: JSON.stringify({ token }) }
    ),

  // What CI runs for this project: its GitHub Actions workflows, jobs and steps.
  getCIWorkflows: (id: string) =>
    request<{
      workflows: {
        file: string;
        name: string;
        triggers: string[];
        jobs: { id: string; name: string; runs_on: string; steps: string[] }[];
      }[];
    }>(`/api/workflows/${id}/ci/workflows`),

  getRisks: (id: string) => request<{ risks: RiskItem[] }>(`/api/workflows/${id}/risks`),
  analyzeRisks: (id: string) => request<{ risks: RiskItem[] }>(`/api/workflows/${id}/risks/analyze`, { method: "POST" }),

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
    request<{
      answer: string;
      cited_files: string[];
      evidence: RetrievalEvidenceItem[];
      // Where the answer is: file-name matches first, then the retrieved pieces.
      locations: { file: string; start_line: number; end_line: number; symbol: string; why: string }[];
    }>("/api/repository/ask", {
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
