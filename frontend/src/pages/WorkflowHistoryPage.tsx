import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { Project, Repository, Workflow } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export function WorkflowHistoryPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [repos, setRepos] = useState<Record<string, Repository>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listWorkflows(), api.listProjects(), api.listRepositories()])
      .then(([wfs, projs, repositories]) => {
        setWorkflows(wfs.slice().sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at)));
        setProjects(Object.fromEntries(projs.map((p) => [p.id, p])));
        setRepos(Object.fromEntries(repositories.map((r) => [r.id, r])));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="page-title">Workflow History</h1>
      <p className="page-subtitle">Every workflow run in this workspace, most recently updated first.</p>

      {error && <div className="callout callout-danger">{error}</div>}

      <div className="card">
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
