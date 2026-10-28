import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { Project, Repository, Workflow } from "../types";
import { StatusBadge } from "../components/StatusBadge";

type SortKey = "updated" | "created" | "state" | "repairs";
type SortDir = "asc" | "desc";

const STATE_GROUPS: Record<string, string[]> = {
  "Awaiting approval": ["AWAITING_PLAN_APPROVAL", "AWAITING_CHANGE_APPROVAL", "AWAITING_COMMIT_APPROVAL", "REPAIRING"],
  "In progress":       ["CREATED", "INDEXING", "INDEXED", "PLANNING", "PLAN_READY", "CHANGES_GENERATING", "CHANGES_READY", "TESTS_GENERATING", "VALIDATING"],
  "Failed / rejected": ["VALIDATION_FAILED", "PLAN_REJECTED", "CHANGES_REJECTED", "FAILED"],
  "Completed":         ["COMPLETED"],
  "CI running":        ["COMMITTED", "CI_RUNNING"],
};

function groupForState(state: string): string {
  for (const [group, states] of Object.entries(STATE_GROUPS)) {
    if (states.includes(state)) return group;
  }
  return "Other";
}

function relTime(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function WorkflowHistoryPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [repos, setRepos] = useState<Record<string, Repository>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter state
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [projectFilter, setProjectFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("updated");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [deleting, setDeleting] = useState(false);
  const [deleteErrors, setDeleteErrors] = useState<string[]>([]);

  // Permanently removes workflow history + local workspace folders (never the
  // repository or anything on GitHub). Failures (e.g. a folder in use by a
  // running app) are reported and the rest still go ahead.
  async function deleteWorkflows(ids: string[]) {
    const label = ids.length === 1 ? "this workflow" : `these ${ids.length} workflows`;
    if (!window.confirm(`Permanently delete ${label} and their local workspace folders?\n\nYour repositories and anything on GitHub are not affected.`)) return;
    setDeleting(true);
    setDeleteErrors([]);
    const errors: string[] = [];
    const removed = new Set<string>();
    for (const id of ids) {
      try {
        await api.deleteWorkflow(id);
        removed.add(id);
      } catch (e) {
        errors.push(`${id}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
    setWorkflows((prev) => prev.filter((w) => !removed.has(w.id)));
    setDeleteErrors(errors);
    setDeleting(false);
  }

  useEffect(() => {
    Promise.all([api.listWorkflows(), api.listProjects(), api.listRepositories()])
      .then(([wfs, projs, repositories]) => {
        setWorkflows(wfs);
        setProjects(Object.fromEntries(projs.map((p) => [p.id, p])));
        setRepos(Object.fromEntries(repositories.map((r) => [r.id, r])));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return <span style={{ color: "var(--text-faint)", fontSize: 10 }}>⇅</span>;
    return <span style={{ fontSize: 10 }}>{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  const filtered = useMemo(() => {
    let rows = [...workflows];

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((w) =>
        w.intent.toLowerCase().includes(q) ||
        (projects[w.project_id]?.name ?? "").toLowerCase().includes(q) ||
        (repos[w.repository_id]?.source ?? "").toLowerCase().includes(q)
      );
    }

    if (stateFilter !== "all") {
      if (Object.keys(STATE_GROUPS).includes(stateFilter)) {
        rows = rows.filter((w) => STATE_GROUPS[stateFilter].includes(w.state));
      } else {
        rows = rows.filter((w) => w.state === stateFilter);
      }
    }

    if (projectFilter !== "all") {
      rows = rows.filter((w) => w.project_id === projectFilter);
    }

    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "updated": cmp = +new Date(a.updated_at) - +new Date(b.updated_at); break;
        case "created": cmp = +new Date(a.created_at) - +new Date(b.created_at); break;
        case "state":   cmp = a.state.localeCompare(b.state); break;
        case "repairs": cmp = a.repair_attempts - b.repair_attempts; break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });

    return rows;
  }, [workflows, projects, repos, search, stateFilter, projectFilter, sortKey, sortDir]);

  const projectList = Object.values(projects);

  // Counts by group for the filter badges
  const groupCounts: Record<string, number> = {};
  for (const w of workflows) {
    const g = groupForState(w.state);
    groupCounts[g] = (groupCounts[g] ?? 0) + 1;
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16, gap: 10, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>Workflow Runs</h1>
          <p className="page-subtitle" style={{ margin: "4px 0 0 0" }}>
            {loading ? "Loading…" : `${workflows.length} total`}
          </p>
        </div>
        <Link to="/new-workflow" className="btn btn-primary" style={{ fontSize: 12.5, padding: "6px 14px" }}>
          + New Workflow
        </Link>
      </div>

      {error && <div className="callout callout-danger">{error}</div>}

      {/* Quick-group filter pills */}
      {!loading && workflows.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          <button
            className={`tab${stateFilter === "all" ? " active" : ""}`}
            onClick={() => setStateFilter("all")}
            style={{ padding: "5px 12px", fontSize: 12 }}
          >
            All ({workflows.length})
          </button>
          {Object.entries(STATE_GROUPS).map(([group]) => {
            const count = groupCounts[group] ?? 0;
            if (count === 0) return null;
            return (
              <button
                key={group}
                className={`tab${stateFilter === group ? " active" : ""}`}
                onClick={() => setStateFilter(stateFilter === group ? "all" : group)}
                style={{ padding: "5px 12px", fontSize: 12 }}
              >
                {group} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Filter bar */}
      <div className="filter-bar" style={{ marginBottom: 14 }}>
        <input
          className="search-input"
          type="search"
          placeholder="Search by intent, project or repository…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {projectList.length > 1 && (
          <select value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="all">All projects</option>
            {projectList.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
        {filtered.length !== workflows.length && (
          <span style={{ fontSize: 12, color: "var(--text-faint)", alignSelf: "center" }}>
            {filtered.length} of {workflows.length}
          </span>
        )}
        {filtered.length > 0 && (
          <button
            className="btn"
            style={{ fontSize: 12, padding: "6px 10px", color: "var(--danger)", marginLeft: "auto" }}
            disabled={deleting}
            onClick={() => deleteWorkflows(filtered.map((w) => w.id))}
          >
            {deleting ? "Deleting…" : filtered.length === workflows.length ? `Delete all (${filtered.length})` : `Delete ${filtered.length} shown`}
          </button>
        )}
        {(search || stateFilter !== "all" || projectFilter !== "all") && (
          <button
            className="btn"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() => { setSearch(""); setStateFilter("all"); setProjectFilter("all"); }}
          >
            Clear
          </button>
        )}
      </div>

      {deleteErrors.length > 0 && (
        <div className="callout callout-danger" style={{ marginBottom: 10 }}>
          <strong>Some workflows were not deleted:</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{deleteErrors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <div className="empty-state" style={{ padding: "28px 0" }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="empty-state" style={{ padding: "28px 0" }}>
            {workflows.length === 0
              ? <><span>No workflows yet. </span><Link to="/new-workflow">Start a new workflow →</Link></>
              : "No workflows match the current filters."}
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ paddingLeft: 18 }}>Intent</th>
                <th>Repository</th>
                <th
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onClick={() => toggleSort("state")}
                >
                  Status {sortIcon("state")}
                </th>
                <th
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onClick={() => toggleSort("repairs")}
                >
                  Repairs {sortIcon("repairs")}
                </th>
                <th>Checkpoints</th>
                <th
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onClick={() => toggleSort("updated")}
                >
                  Updated {sortIcon("updated")}
                </th>
                <th style={{ paddingRight: 18 }} />
              </tr>
            </thead>
            <tbody>
              {filtered.map((w) => {
                const repoName = (repos[w.repository_id]?.source ?? "").split("/").pop() || w.repository_id;
                const projectName = projects[w.project_id]?.name ?? "";
                const isAwaiting = w.state.startsWith("AWAITING_") || w.state === "REPAIRING";
                const isFailed = w.state === "VALIDATION_FAILED" || w.state === "FAILED" || w.state.endsWith("_REJECTED");
                return (
                  <tr key={w.id} style={{ background: isAwaiting ? "var(--warn-soft)" : isFailed ? "var(--danger-soft)" : undefined }}>
                    <td style={{ paddingLeft: 18, maxWidth: 320 }}>
                      <Link
                        to={`/workflows/${w.id}`}
                        style={{ fontWeight: 600, fontSize: 13 }}
                        title={w.intent}
                      >
                        {w.intent.length > 65 ? w.intent.slice(0, 65) + "…" : w.intent}
                      </Link>
                      {projectName && (
                        <div style={{ fontSize: 11, color: "var(--text-faint)" }}>{projectName}</div>
                      )}
                    </td>
                    <td>
                      <code style={{ fontSize: 11.5 }}>{repoName}</code>
                    </td>
                    <td>
                      <StatusBadge state={w.state} />
                    </td>
                    <td>
                      <span
                        style={{
                          fontSize: 12.5,
                          fontWeight: 600,
                          color: w.repair_attempts > 0 ? "var(--warn)" : "var(--text-faint)",
                        }}
                      >
                        {w.repair_attempts}
                      </span>
                    </td>
                    <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {w.human_intervention_count}
                    </td>
                    <td style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                      {relTime(w.updated_at)}
                    </td>
                    <td style={{ paddingRight: 18, textAlign: "right" }}>
                      <Link
                        to={`/workflows/${w.id}`}
                        style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)" }}
                      >
                        Open →
                      </Link>
                      <button
                        type="button"
                        title="Delete workflow"
                        aria-label="Delete workflow"
                        disabled={deleting}
                        onClick={() => deleteWorkflows([w.id])}
                        style={{ background: "none", border: "none", marginLeft: 10, cursor: "pointer", fontSize: 13 }}
                      >
                        🗑️
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
