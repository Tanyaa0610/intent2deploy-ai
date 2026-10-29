import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../services/api";
import type { AttentionItem, DashboardAttention, DashboardSummary } from "../types";
import { StatusBadge } from "../components/StatusBadge";

function relTime(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function actionChipClass(state: string): string {
  if (state.startsWith("AWAITING_") || state === "REPAIRING") return "approval";
  if (state === "VALIDATION_FAILED" || state === "FAILED" || state.endsWith("_REJECTED")) return "failure";
  return "info";
}

function KPIStrip({ summary }: { summary: DashboardSummary }) {
  return (
    <div className="kpi-strip">
      <div className="kpi-cell">
        <span className={`kpi-value${summary.active_workflows > 0 ? " accent" : ""}`}>
          {summary.active_workflows}
        </span>
        <span className="kpi-label">Active</span>
      </div>
      <div className="kpi-cell">
        <span className={`kpi-value${summary.awaiting_approval > 0 ? " warn" : ""}`}>
          {summary.awaiting_approval}
        </span>
        <span className="kpi-label">Awaiting approval</span>
      </div>
      <div className="kpi-cell">
        <span className={`kpi-value${summary.failed_workflows > 0 ? " danger" : ""}`}>
          {summary.failed_workflows}
        </span>
        <span className="kpi-label">Failed</span>
      </div>
      <div className="kpi-cell">
        <span className="kpi-value success">{summary.completed_workflows}</span>
        <span className="kpi-label">Completed</span>
      </div>
    </div>
  );
}

function AttentionList({
  items,
  emptyMsg,
}: {
  items: AttentionItem[];
  emptyMsg: string;
}) {
  const navigate = useNavigate();
  if (items.length === 0) {
    return <div className="empty-state">{emptyMsg}</div>;
  }
  return (
    <div>
      {items.map((item) => (
        <div
          key={item.id}
          className="attention-row"
          onClick={() => navigate(`/workflows/${item.id}`)}
          role="link"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && navigate(`/workflows/${item.id}`)}
        >
          <div style={{ minWidth: 0 }}>
            <div className="attention-intent" title={item.intent}>
              {item.intent.length > 72 ? item.intent.slice(0, 72) + "…" : item.intent}
            </div>
            <div className="attention-meta">
              {item.project_name} · {item.repository_name} · {relTime(item.updated_at)}
              {item.repair_attempts > 0 && (
                <span style={{ marginLeft: 6, color: "var(--warn)" }}>
                  {item.repair_attempts} repair{item.repair_attempts !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
          <StatusBadge state={item.state} />
          {item.awaiting_action ? (
            <span className={`action-chip ${actionChipClass(item.state)}`}>
              {item.awaiting_action}
            </span>
          ) : (
            <span style={{ width: 80 }} />
          )}
        </div>
      ))}
    </div>
  );
}

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [attention, setAttention] = useState<DashboardAttention | null>(null);
  const [health, setHealth] = useState<{ llm_provider: string; llm_mode: string; is_mock: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getDashboardSummary(),
      api.getDashboardAttention(),
      api.health(),
    ])
      .then(([s, a, h]) => {
        setSummary(s);
        setAttention(a);
        setHealth(h);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div>
        <h1 className="page-title">Dashboard</h1>
        <div className="empty-state">Loading…</div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Dashboard</h1>
        <Link to="/new-workflow" className="btn btn-primary" style={{ fontSize: 12.5, padding: "6px 14px" }}>
          + New Workflow
        </Link>
      </div>

      {health?.is_mock && (
        <div className="callout callout-mock" style={{ marginBottom: 14 }}>
          <strong>Mock mode</strong> — {health.llm_provider} configured, no live API calls.
          Set <code>LLM_MODE=live</code> with a provider key for real generation.
        </div>
      )}

      {error && <div className="callout callout-danger">{error}</div>}

      {summary && <KPIStrip summary={summary} />}

      {/* Attention items — primary focus */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="sec-header">
          <span className="sec-header-title">
            Needs attention
            {attention?.attention.length ? (
              <span style={{ marginLeft: 6, fontSize: 11.5, fontWeight: 400, color: "var(--text-faint)" }}>
                ({attention.attention.length})
              </span>
            ) : null}
          </span>
          <Link to="/workflows" className="sec-link">View all →</Link>
        </div>
        {!attention ? (
          <div className="empty-state">Loading…</div>
        ) : (
          <AttentionList
            items={attention.attention}
            emptyMsg="Nothing needs attention right now."
          />
        )}
      </div>

      {/* Recently completed */}
      {attention?.recent_completed && attention.recent_completed.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="sec-header">
            <span className="sec-header-title">Recently completed</span>
          </div>
          <AttentionList
            items={attention.recent_completed}
            emptyMsg="No completed workflows yet."
          />
        </div>
      )}

      {/* Secondary metrics */}
      {summary?.has_data && (
        <div className="card">
          <div className="sec-header" style={{ marginBottom: 12 }}>
            <span className="sec-header-title">System metrics</span>
          </div>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 19, fontWeight: 700, color: "var(--text)" }}>
                {summary.avg_execution_time_ms != null
                  ? (summary.avg_execution_time_ms / 1000).toFixed(1) + "s"
                  : "—"}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Avg execution
              </div>
            </div>
            <div>
              <div style={{ fontSize: 19, fontWeight: 700, color: summary.guardrail_violations > 0 ? "var(--danger)" : "var(--text)" }}>
                {summary.guardrail_violations}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Guardrail violations
              </div>
            </div>
            <div>
              <div style={{ fontSize: 19, fontWeight: 700, color: "var(--text)" }}>
                {summary.human_interventions}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Human interventions
              </div>
            </div>
            {summary.avg_repair_attempts != null && (
              <div>
                <div style={{ fontSize: 19, fontWeight: 700, color: summary.avg_repair_attempts > 1 ? "var(--warn)" : "var(--text)" }}>
                  {summary.avg_repair_attempts.toFixed(1)}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Avg repairs / workflow
                </div>
              </div>
            )}
            {summary.validation_pass_rate != null && (
              <div>
                <div style={{ fontSize: 19, fontWeight: 700, color: summary.validation_pass_rate < 0.5 ? "var(--danger)" : "var(--success)" }}>
                  {Math.round(summary.validation_pass_rate * 100)}%
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  CI pass rate
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!summary?.has_data && !loading && (
        <div className="card">
          <div className="empty-state" style={{ padding: "28px 0" }}>
            No workflows yet.{" "}
            <Link to="/new-workflow">Start your first workflow →</Link>
          </div>
        </div>
      )}
    </div>
  );
}
