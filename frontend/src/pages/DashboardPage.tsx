import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { Project, Repository, Workflow } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export function DashboardPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [repos, setRepos] = useState<Record<string, Repository>>({});
  const [health, setHealth] = useState<{ llm_provider: string; llm_mode: string; is_mock: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listWorkflows(), api.listProjects(), api.listRepositories(), api.health()])
      .then(([wfs, projs, repositories, h]) => {
        setWorkflows(wfs);
        setProjects(Object.fromEntries(projs.map((p) => [p.id, p])));
        setRepos(Object.fromEntries(repositories.map((r) => [r.id, r])));
        setHealth(h);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const completed = workflows.filter((w) => w.state === "COMPLETED").length;
  const totalInterventions = workflows.reduce((sum, w) => sum + w.human_intervention_count, 0);
  const avgTime =
    workflows.filter((w) => w.total_ms).length > 0
      ? Math.round(
          workflows.filter((w) => w.total_ms).reduce((s, w) => s + (w.total_ms || 0), 0) /
            workflows.filter((w) => w.total_ms).length
        )
      : null;

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
      {error && <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>{error}</div>}

      <div className="grid grid-4">
        <div className="card stat">
          <span className="stat-value">{workflows.length}</span>
          <span className="stat-label">Total workflows</span>
        </div>
        <div className="card stat">
          <span className="stat-value">{completed}</span>
          <span className="stat-label">Completed</span>
        </div>
        <div className="card stat">
          <span className="stat-value">{totalInterventions}</span>
          <span className="stat-label">Human interventions</span>
        </div>
        <div className="card stat">
          <span className="stat-value">{avgTime ? `${(avgTime / 1000).toFixed(1)}s` : "—"}</span>
          <span className="stat-label">Avg. execution time</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Workflows</div>
        {loading ? (
          <div className="empty-state">Loading…</div>
        ) : workflows.length === 0 ? (
          <div className="empty-state">
            No workflows yet. <Link to="/new-workflow">Start a new workflow</Link>.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Intent</th>
                <th>Project</th>
                <th>Repository</th>
                <th>Status</th>
                <th>Interventions</th>
                <th>Repairs</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {workflows.map((w) => (
                <tr key={w.id}>
                  <td>
                    <Link to={`/workflows/${w.id}`}>{w.intent.slice(0, 70)}</Link>
                  </td>
                  <td>{projects[w.project_id]?.name || w.project_id}</td>
                  <td>{repos[w.repository_id]?.source.split("/").pop() || w.repository_id}</td>
                  <td>
                    <StatusBadge state={w.state} />
                  </td>
                  <td>{w.human_intervention_count}</td>
                  <td>{w.repair_attempts}</td>
                  <td>{new Date(w.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
