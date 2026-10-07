import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { AuditEventItem, Project, Repository, Workflow } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";

function relativeTime(iso: string): string {
  const diffSec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

export function DashboardPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [repos, setRepos] = useState<Record<string, Repository>>({});
  const [health, setHealth] = useState<{ llm_provider: string; llm_mode: string; is_mock: boolean } | null>(null);
  const [recentEvents, setRecentEvents] = useState<AuditEventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listWorkflows(), api.listProjects(), api.listRepositories(), api.health()])
      .then(([wfs, projs, repositories, h]) => {
        const sorted = wfs.slice().sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
        setWorkflows(sorted);
        setProjects(Object.fromEntries(projs.map((p) => [p.id, p])));
        setRepos(Object.fromEntries(repositories.map((r) => [r.id, r])));
        setHealth(h);
        if (sorted.length > 0) {
          api.getEvents(sorted[0].id).then((r) => setRecentEvents(r.events.slice(-8).reverse())).catch(() => {});
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const completed = workflows.filter((w) => w.state === "COMPLETED").length;
  const awaiting = workflows.filter((w) => w.state.startsWith("AWAITING_")).length;
  const avgTime =
    workflows.filter((w) => w.total_ms).length > 0
      ? Math.round(
          workflows.filter((w) => w.total_ms).reduce((s, w) => s + (w.total_ms || 0), 0) /
            workflows.filter((w) => w.total_ms).length
        )
      : null;

  const overviewSentence =
    workflows.length === 0
      ? "No workflows have been run in this workspace yet."
      : `${workflows.length} workflow${workflows.length === 1 ? "" : "s"} tracked — ${completed} completed, ${awaiting} awaiting approval.`;

  const recent = workflows.slice(0, 6);
  const latest = workflows[0];

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-subtitle">Project, repository, and workflow status at a glance.</p>

      {health?.is_mock && (
        <div className="callout callout-mock">
          Running in <strong>MOCK mode</strong> ({health.llm_provider} configured, no live API calls). Retrieval,
          planning, code generation, and validation are all real — only the generative LLM step is a deterministic,
          retrieval-grounded stand-in. Set <code>LLM_MODE=live</code> with a provider API key for live generation.
        </div>
      )}
      {error && <div className="callout callout-danger">{error}</div>}

      <div className="card-title">Overview</div>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -6, marginBottom: 2 }}>{overviewSentence}</p>

      <div className="overview-stats">
        <div>
          <div className="stat-value">{workflows.length}</div>
          <div className="stat-label">Total workflows</div>
        </div>
        <div>
          <div className="stat-value">{completed}</div>
          <div className="stat-label">Completed</div>
        </div>
        <div>
          <div className="stat-value">{avgTime ? `${(avgTime / 1000).toFixed(1)}s` : "—"}</div>
          <div className="stat-label">Avg. execution time</div>
        </div>
      </div>

      <div className="section-row">
        <div className="card-title">Recent workflows</div>
        {workflows.length > 6 && (
          <Link to="/workflows" className="section-link">
            View all →
          </Link>
        )}
      </div>
      <div className="card">
        {loading ? (
          <div className="empty-state">Loading…</div>
        ) : recent.length === 0 ? (
          <div className="empty-state">
            No workflows yet. <Link to="/new-workflow">Start a new workflow</Link>.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Repository</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((w) => (
                <tr key={w.id}>
                  <td>
                    <Link to={`/workflows/${w.id}`}>{w.intent.slice(0, 60)}</Link>
                    <div style={{ fontSize: 11.5, color: "var(--text-faint)" }}>
                      {projects[w.project_id]?.name || w.project_id}
                    </div>
                  </td>
                  <td>{repos[w.repository_id]?.source.split("/").pop() || w.repository_id}</td>
                  <td>
                    <StatusBadge state={w.state} />
                  </td>
                  <td style={{ color: "var(--text-muted)" }}>{relativeTime(w.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {latest && (
        <>
          <div className="card-title">System activity</div>
          <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: -8, marginBottom: 12 }}>
            From the most recently updated workflow — <Link to={`/workflows/${latest.id}`}>{latest.intent.slice(0, 48)}</Link>
          </p>
          <div className="card">
            <Timeline events={recentEvents} />
          </div>
        </>
      )}
    </div>
  );
}
