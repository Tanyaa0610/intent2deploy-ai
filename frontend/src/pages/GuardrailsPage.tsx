import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { GUARDRAIL_CATEGORIES } from "../types";
import type { GuardrailCheckItem, GuardrailSummary, GuardrailTimelineItem, Workflow } from "../types";
import { StatusBadge } from "../components/StatusBadge";

const CATEGORY_LABELS: Record<string, string> = {
  SECURITY: "Security",
  INFRASTRUCTURE: "Infrastructure",
  CI_CD: "CI/CD",
  DEPLOYMENT: "Deployment",
  COST: "Cost",
  AI_LLM: "AI / LLM",
  INPUT: "Input",
  OUTPUT: "Output",
};

const STATUSES = ["PASSED", "WARNING", "BLOCKED", "FAILED", "NOT_APPLICABLE", "NOT_IMPLEMENTED"];
const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

const PIPELINE_STAGES: { label: string; category: string | null }[] = [
  { label: "Developer Input", category: null },
  { label: "Input Guardrails", category: "INPUT" },
  { label: "AI/LLM Guardrails", category: "AI_LLM" },
  { label: "Output Guardrails", category: "OUTPUT" },
  { label: "Security", category: "SECURITY" },
  { label: "Infrastructure", category: "INFRASTRUCTURE" },
  { label: "CI/CD", category: "CI_CD" },
  { label: "Deployment", category: "DEPLOYMENT" },
  { label: "Cost", category: "COST" },
  { label: "Final Readiness", category: null },
];

type DetailData = {
  id?: string;
  guardrail_id: string;
  category: string;
  name: string;
  description?: string;
  purpose?: string;
  enforcement_point: string;
  severity: string;
  status: string;
  action: string;
  trigger_condition: string;
  evidence: string[];
  remediation: string;
  configurable_threshold?: string;
  evaluated_at: string;
};

export function GuardrailsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowId, setWorkflowId] = useState("");
  const [summary, setSummary] = useState<GuardrailSummary | null>(null);
  const [checks, setChecks] = useState<GuardrailCheckItem[]>([]);
  const [timeline, setTimeline] = useState<GuardrailTimelineItem[]>([]);
  const [readiness, setReadiness] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [selected, setSelected] = useState<DetailData | null>(null);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .listWorkflows()
      .then((wfs) => {
        setWorkflows(wfs);
        if (wfs.length > 0) setWorkflowId(wfs[0].id);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingWorkflows(false));
  }, []);

  const refreshOverview = useCallback(async () => {
    if (!workflowId) return;
    setError("");
    try {
      const [s, t, r] = await Promise.all([
        api.getGuardrailSummary(workflowId),
        api.getGuardrailTimeline(workflowId),
        api.getReadiness(workflowId),
      ]);
      setSummary(s);
      setTimeline(t.timeline);
      setReadiness(r.decision);
    } catch (e) {
      setError(String(e));
    }
  }, [workflowId]);

  const refreshFiltered = useCallback(async () => {
    if (!workflowId) return;
    try {
      const r = await api.getWorkflowGuardrails(workflowId, {
        category: categoryFilter || undefined,
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
      });
      setChecks(r.guardrails);
    } catch (e) {
      setError(String(e));
    }
  }, [workflowId, categoryFilter, statusFilter, severityFilter]);

  useEffect(() => {
    refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    refreshFiltered();
  }, [refreshFiltered]);

  async function handleEvaluate() {
    if (!workflowId) return;
    setBusy(true);
    setError("");
    try {
      await api.evaluateGuardrails(workflowId);
      await Promise.all([refreshOverview(), refreshFiltered()]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleApproval(approved: boolean) {
    if (!workflowId || !selected?.id) return;
    setBusy(true);
    setError("");
    try {
      await api.approveGuardrail(workflowId, selected.id, approved, approved ? "Approved from Guardrail Control Plane" : "Declined from Guardrail Control Plane");
      setSelected(null);
      await Promise.all([refreshOverview(), refreshFiltered()]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const totals = summary?.has_data
    ? Object.values(summary.categories).reduce(
        (acc, c) => ({
          total: acc.total + c.total,
          passed: acc.passed + c.passed,
          warnings: acc.warnings + c.warnings,
          blocked: acc.blocked + c.blocked,
          failed: acc.failed + c.failed,
        }),
        { total: 0, passed: 0, warnings: 0, blocked: 0, failed: 0 }
      )
    : null;

  function pipelineNodeClass(category: string | null, index: number): string {
    if (category === null) {
      if (index === 0) return ""; // Developer Input: neutral entry point
      // Final Readiness node
      if (readiness === "READY") return "clear";
      if (readiness === "READY_WITH_WARNINGS") return "warn";
      if (readiness === "NOT_READY") return "attention";
      return "";
    }
    const c = summary?.categories[category];
    if (!c || c.total === 0) return "";
    if (c.blocked > 0 || c.failed > 0) return "attention";
    if (c.warnings > 0) return "warn";
    return "clear";
  }

  function pipelineNodeCaption(category: string | null, index: number): string {
    if (category === null) {
      if (index === 0) return "workflow.intent";
      return readiness ? readiness.replace(/_/g, " ") : "not assessed";
    }
    const c = summary?.categories[category];
    if (!c || c.total === 0) return "no data yet";
    return `${c.total} check${c.total === 1 ? "" : "s"}`;
  }

  function openDetail(item: GuardrailCheckItem | GuardrailTimelineItem) {
    setSelected({
      id: "id" in item ? item.id : undefined,
      guardrail_id: item.guardrail_id,
      category: item.category,
      name: item.name,
      description: "description" in item ? item.description : undefined,
      purpose: "purpose" in item ? item.purpose : undefined,
      enforcement_point: item.enforcement_point,
      severity: item.severity,
      status: item.status,
      action: item.action,
      trigger_condition: "trigger_condition" in item ? item.trigger_condition : item.reason,
      evidence: item.evidence,
      remediation: item.remediation,
      configurable_threshold: "configurable_threshold" in item ? item.configurable_threshold : undefined,
      evaluated_at: item.evaluated_at,
    });
  }

  const activeWorkflow = workflows.find((w) => w.id === workflowId);

  return (
    <div>
      <h1 className="page-title">AI-DevOps Guardrail Control Plane</h1>
      <p className="page-subtitle">
        Every result below is read live from <code>GuardrailCheck</code> rows produced by the backend guardrail
        engine — SECURITY, INFRASTRUCTURE, CI/CD, DEPLOYMENT, COST, AI/LLM, INPUT, and OUTPUT.
      </p>

      {error && (
        <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
          {error}
        </div>
      )}

      <div className="card">
        <div className="card-title">Workflow</div>
        {loadingWorkflows ? (
          <div className="empty-state">Loading workflows…</div>
        ) : workflows.length === 0 ? (
          <div className="empty-state">
            No workflows yet. <Link to="/new-workflow">Start a new workflow</Link> to see guardrail activity.
          </div>
        ) : (
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} style={{ maxWidth: 480 }}>
              {workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.intent.slice(0, 70)} — {w.state}
                </option>
              ))}
            </select>
            {activeWorkflow && <StatusBadge state={activeWorkflow.state} />}
            <Link to={`/workflows/${workflowId}`} className="btn" style={{ marginLeft: "auto" }}>
              Open workflow
            </Link>
            <button className="btn btn-primary" disabled={busy} onClick={handleEvaluate}>
              Re-evaluate on demand
            </button>
          </div>
        )}
      </div>

      {workflowId && (
        <>
          <div className="card">
            <div className="card-title">Developer Intent → Guardrails → Final Readiness</div>
            <div className="gr-pipeline">
              {PIPELINE_STAGES.map((stage, i) => (
                <div key={stage.label} style={{ display: "flex", alignItems: "center" }}>
                  <div className={`gr-pipeline-node ${pipelineNodeClass(stage.category, i)}`}>
                    <div className="n">{stage.label}</div>
                    <div className="c">{pipelineNodeCaption(stage.category, i)}</div>
                  </div>
                  {i < PIPELINE_STAGES.length - 1 && <span className="gr-pipeline-arrow">→</span>}
                </div>
              ))}
            </div>
          </div>

          <div className="card-title" style={{ marginTop: 4 }}>
            Overall Guardrail Summary
          </div>
          {!summary?.has_data ? (
            <div className="card">
              <div className="empty-state">
                No guardrail data yet for this workflow. Run indexing → plan → generate changes to trigger the
                guardrail engine, then return here.
              </div>
            </div>
          ) : (
            <div className="gr-kpis">
              <div className="gr-kpi">
                <span className="n">{totals?.total ?? 0}</span>
                <span className="l">Total checks</span>
              </div>
              <div className="gr-kpi passed">
                <span className="n">{totals?.passed ?? 0}</span>
                <span className="l">Passed</span>
              </div>
              <div className="gr-kpi warnings">
                <span className="n">{totals?.warnings ?? 0}</span>
                <span className="l">Warnings</span>
              </div>
              <div className="gr-kpi blocked">
                <span className="n">{totals?.blocked ?? 0}</span>
                <span className="l">Blocked</span>
              </div>
              <div className="gr-kpi blocked">
                <span className="n">{totals?.failed ?? 0}</span>
                <span className="l">Failed</span>
              </div>
              <div className="gr-kpi approval">
                <span className="n">{summary.approval_required}</span>
                <span className="l">Require approval</span>
              </div>
            </div>
          )}

          <div className="card-title">Category-Wise Breakdown</div>
          <div className="gr-category-grid" style={{ marginBottom: 20 }}>
            {GUARDRAIL_CATEGORIES.map((cat) => {
              const c = summary?.categories[cat];
              return (
                <button
                  key={cat}
                  className={`gr-category-card ${categoryFilter === cat ? "active" : ""}`}
                  onClick={() => setCategoryFilter(categoryFilter === cat ? "" : cat)}
                >
                  <div className="cat-name">{CATEGORY_LABELS[cat]}</div>
                  <div className="cat-total">{c?.total ?? 0}</div>
                  <div className="gr-cat-stats">
                    <span className="gr-cat-stat passed">{c?.passed ?? 0} passed</span>
                    <span className="gr-cat-stat warnings">{c?.warnings ?? 0} warn</span>
                    <span className="gr-cat-stat blocked">{(c?.blocked ?? 0) + (c?.failed ?? 0)} blocked</span>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="card">
            <div className="card-title">Filter Guardrail Results</div>
            <div className="gr-filters">
              <div className="field">
                <label>Category</label>
                <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                  <option value="">All categories</option>
                  {GUARDRAIL_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {CATEGORY_LABELS[c]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Status</label>
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">All statuses</option>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Severity</label>
                <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
                  <option value="">All severities</option>
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              {(categoryFilter || statusFilter || severityFilter) && (
                <button
                  className="btn"
                  onClick={() => {
                    setCategoryFilter("");
                    setStatusFilter("");
                    setSeverityFilter("");
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>

            {checks.length === 0 ? (
              <div className="empty-state">No guardrail checks match these filters yet.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>Guardrail</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Action</th>
                    <th>Reason</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.map((c) => (
                    <tr key={c.id} className="gr-row-clickable" onClick={() => openDetail(c)}>
                      <td>{CATEGORY_LABELS[c.category] || c.category}</td>
                      <td>
                        <code>{c.guardrail_id}</code> {c.name}
                      </td>
                      <td>
                        <StatusBadge state={c.status} />
                      </td>
                      <td>
                        <StatusBadge state={c.severity} />
                      </td>
                      <td>
                        <StatusBadge state={c.action} />
                      </td>
                      <td style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c.trigger_condition || c.description}
                      </td>
                      <td>{new Date(c.evaluated_at).toLocaleTimeString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <div className="card-title">Guardrail Execution Timeline</div>
            {timeline.length === 0 ? (
              <div className="empty-state">No guardrail activity recorded yet for this workflow.</div>
            ) : (
              <div>
                {timeline.map((t, i) => (
                  <div
                    key={i}
                    className={`gr-timeline-item ${t.status.toLowerCase()} gr-row-clickable`}
                    onClick={() => openDetail(t)}
                  >
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 700, fontSize: 12.5 }}>
                        <code>{t.guardrail_id}</code> {t.name}
                      </span>
                      <StatusBadge state={t.status} />
                      {t.approval_required && <span className="badge badge-accent">approval required</span>}
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 3 }}>
                      {CATEGORY_LABELS[t.category] || t.category} · {t.enforcement_point} ·{" "}
                      {new Date(t.evaluated_at).toLocaleString()}
                    </div>
                    {t.reason && <div style={{ fontSize: 12.5, marginTop: 4 }}>{t.reason}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {selected && (
        <>
          <div className="gr-detail-backdrop" onClick={() => setSelected(null)} />
          <div className="gr-detail-panel">
            <button className="close-btn" onClick={() => setSelected(null)} aria-label="Close">
              ×
            </button>
            <div className="card-title" style={{ marginBottom: 2 }}>
              {CATEGORY_LABELS[selected.category] || selected.category}
            </div>
            <h2 style={{ fontSize: 17, margin: "0 0 4px" }}>
              <code>{selected.guardrail_id}</code> {selected.name}
            </h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 4 }}>
              <StatusBadge state={selected.status} />
              <StatusBadge state={selected.severity} />
              <StatusBadge state={selected.action} />
            </div>

            {selected.description && (
              <>
                <div className="gr-field-label">Description</div>
                <p style={{ fontSize: 13 }}>{selected.description}</p>
              </>
            )}
            {selected.purpose && (
              <>
                <div className="gr-field-label">Purpose</div>
                <p style={{ fontSize: 13 }}>{selected.purpose}</p>
              </>
            )}

            <div className="gr-field-label">Reason</div>
            <p style={{ fontSize: 13 }}>{selected.trigger_condition || "—"}</p>

            <div className="gr-field-label">Evidence</div>
            {selected.evidence.length === 0 ? (
              <p style={{ fontSize: 13, color: "var(--text-faint)" }}>No specific evidence recorded.</p>
            ) : (
              <ul className="gr-evidence-list">
                {selected.evidence.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}

            <div className="gr-field-label">Remediation</div>
            <p style={{ fontSize: 13 }}>{selected.remediation || "No action needed."}</p>

            <div className="gr-field-label">Enforcement Point</div>
            <p style={{ fontSize: 13 }}>{selected.enforcement_point}</p>

            {selected.configurable_threshold && (
              <>
                <div className="gr-field-label">Configurable Threshold</div>
                <p style={{ fontSize: 13 }}>{selected.configurable_threshold}</p>
              </>
            )}

            <div className="gr-field-label">Evaluated At</div>
            <p style={{ fontSize: 13 }}>{new Date(selected.evaluated_at).toLocaleString()}</p>

            {selected.action === "REQUIRE_APPROVAL" && selected.id && (
              <>
                <div className="gr-field-label">Human Decision</div>
                <div className="btn-row" style={{ marginTop: 6 }}>
                  <button className="btn btn-success" disabled={busy} onClick={() => handleApproval(true)}>
                    Approve
                  </button>
                  <button className="btn btn-danger" disabled={busy} onClick={() => handleApproval(false)}>
                    Decline
                  </button>
                </div>
              </>
            )}
            {selected.action === "REQUIRE_APPROVAL" && !selected.id && (
              <p style={{ fontSize: 12, color: "var(--text-faint)", marginTop: 10 }}>
                Open this result from the filtered table (not the timeline) to approve or decline it.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
