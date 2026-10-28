import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";
import type { ManagedRepository } from "../types";
import { RepoStatusBadge } from "../components/RepoStatusBadge";
import { branchSummary, indexSummary, isBusy, kindLabel } from "../services/repoMeta";

type Mode = "local" | "github" | "create";

const MODE_LABEL: Record<Mode, string> = {
  local: "Connect local",
  github: "Connect GitHub",
  create: "Create new",
};

export function RepositoriesPage() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<ManagedRepository[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [mode, setMode] = useState<Mode | null>(null);
  const [roots, setRoots] = useState<string[]>([]);
  const [serverToken, setServerToken] = useState(false);

  const load = useCallback(() => {
    return api
      .listManagedRepositories()
      .then((r) => {
        setRepos(r);
        setLoadError("");
      })
      .catch((e) => setLoadError(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    api
      .getRepoRoots()
      .then((r) => {
        setRoots(r.roots);
        setServerToken(r.server_token_configured);
      })
      .catch(() => undefined);
  }, [load]);

  // Poll while any repository has a clone/index/pull in progress.
  const anyBusy = repos.some(isBusy);
  useEffect(() => {
    if (!anyBusy) return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [anyBusy, repos, load]);

  function onAdded(repo: ManagedRepository) {
    setRepos((prev) => [repo, ...prev.filter((r) => r.id !== repo.id)]);
    setMode(null);
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Repositories</h1>
          <p className="page-subtitle">Local folders and GitHub clones available for browsing, indexing and workflows.</p>
        </div>
        <div className="btn-row" style={{ marginTop: 0 }}>
          {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`btn ${mode === m ? "btn-primary" : ""}`}
              onClick={() => setMode(mode === m ? null : m)}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
      </div>

      {mode && (
        <AddRepositoryForm
          key={mode}
          mode={mode}
          roots={roots}
          serverToken={serverToken}
          onCancel={() => setMode(null)}
          onAdded={onAdded}
        />
      )}

      {loadError && <div className="callout callout-danger">Could not load repositories: {loadError}</div>}

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : repos.length === 0 && !loadError ? (
        <div className="card empty-state" style={{ padding: 32 }}>
          No repositories yet. Connect a local folder, clone from GitHub, or create a new one.
        </div>
      ) : (
        <div className="repo-grid">
          {repos.map((r) => (
            <RepoCard key={r.id} repo={r} onOpen={() => navigate(`/repositories/${r.id}`)} />
          ))}
        </div>
      )}
    </div>
  );
}

function RepoCard({ repo, onOpen }: { repo: ManagedRepository; onOpen: () => void }) {
  const location = repo.kind === "github" ? repo.source : repo.local_path;
  return (
    <button type="button" className="repo-card" onClick={onOpen} aria-label={`Open ${repo.name}`}>
      <div className="repo-card-head">
        <span className="repo-card-name">{repo.name}</span>
        <RepoStatusBadge repo={repo} />
      </div>
      <div className="repo-card-sub">
        <span>{kindLabel(repo)}</span>
        {repo.branch && <span className="mono">{repo.branch}</span>}
        {repo.workflow_count > 0 && <span>{repo.workflow_count} {repo.workflow_count === 1 ? "run" : "runs"}</span>}
      </div>
      <dl className="repo-card-details">
        <dt>{repo.kind === "github" ? "URL" : "Path"}</dt>
        <dd className="mono">{location}</dd>
        {repo.kind === "github" && (
          <>
            <dt>Clone</dt>
            <dd className="mono">{repo.local_path}</dd>
          </>
        )}
        <dt>Branch</dt>
        <dd>{branchSummary(repo)}</dd>
        <dt>Connection</dt>
        <dd>{repo.status === "cloning" ? "Cloning…" : repo.accessible ? "Accessible" : "Path not found or unreadable"}</dd>
        <dt>Index</dt>
        <dd>{indexSummary(repo)}</dd>
        {repo.status === "error" && repo.status_detail && (
          <>
            <dt>Error</dt>
            <dd className="text-danger">{repo.status_detail}</dd>
          </>
        )}
      </dl>
    </button>
  );
}

function AddRepositoryForm({
  mode,
  roots,
  serverToken,
  onCancel,
  onAdded,
}: {
  mode: Mode;
  roots: string[];
  serverToken: boolean;
  onCancel: () => void;
  onAdded: (repo: ManagedRepository) => void;
}) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [token, setToken] = useState("");
  const [useServerToken, setUseServerToken] = useState(false);
  const [gitInit, setGitInit] = useState(true);
  const [readme, setReadme] = useState(true);
  const [index, setIndex] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const sep = roots[0]?.includes("\\") ? "\\" : "/";
  const examplePath = roots[0] ? `${roots[0]}${sep}${mode === "create" ? "new-project" : "my-project"}` : "/absolute/path";

  const canSubmit =
    !submitting &&
    (mode === "github" ? url.trim() && (!isPrivate || token.trim() || useServerToken) : path.trim());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      let repo: ManagedRepository;
      if (mode === "local") {
        repo = await api.connectLocalRepository({ path: path.trim(), name: name.trim(), index });
      } else if (mode === "create") {
        repo = await api.createLocalRepository({ path: path.trim(), name: name.trim(), git_init: gitInit, readme, index });
      } else {
        repo = await api.connectGitHubRepository({
          url: url.trim(),
          branch: branch.trim(),
          private: isPrivate,
          token: isPrivate && !useServerToken ? token.trim() : "",
          use_server_token: isPrivate && useServerToken,
          index,
        });
      }
      setToken("");
      onAdded(repo);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card repo-form" onSubmit={submit}>
      <div className="card-title">{MODE_LABEL[mode]}</div>

      {mode !== "github" ? (
        <>
          <label htmlFor="repo-path">{mode === "create" ? "New folder path" : "Folder path"}</label>
          <input id="repo-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder={examplePath} autoFocus spellCheck={false} />
          {roots.length > 0 && <div className="hint">Allowed under: {roots.join(", ")}</div>}
          <label htmlFor="repo-name">Display name</label>
          <input id="repo-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Folder name" />
          {mode === "create" && (
            <div className="check-row">
              <label className="check">
                <input type="checkbox" checked={gitInit} onChange={(e) => setGitInit(e.target.checked)} /> Initialize git
              </label>
              <label className="check">
                <input type="checkbox" checked={readme} onChange={(e) => setReadme(e.target.checked)} /> Add README.md
              </label>
            </div>
          )}
        </>
      ) : (
        <>
          <label htmlFor="repo-url">Repository URL</label>
          <input
            id="repo-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repository"
            autoFocus
            spellCheck={false}
          />
          <label htmlFor="repo-branch">Branch</label>
          <input id="repo-branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Default branch" spellCheck={false} />
          <div className="check-row">
            <label className="check">
              <input type="checkbox" checked={isPrivate} onChange={(e) => setIsPrivate(e.target.checked)} /> Private repository
            </label>
          </div>
          {isPrivate && (
            <>
              {serverToken && (
                <div className="check-row">
                  <label className="check">
                    <input type="checkbox" checked={useServerToken} onChange={(e) => setUseServerToken(e.target.checked)} /> Use
                    server GITHUB_TOKEN
                  </label>
                </div>
              )}
              {!useServerToken && (
                <>
                  <label htmlFor="repo-token">Access token</label>
                  <input
                    id="repo-token"
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="github_pat_… (read access)"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <div className="hint">Used for this clone only. Not stored.</div>
                </>
              )}
            </>
          )}
        </>
      )}

      <div className="check-row">
        <label className="check">
          <input type="checkbox" checked={index} onChange={(e) => setIndex(e.target.checked)} /> Index for RAG after adding
        </label>
      </div>

      {error && (
        <div className="callout callout-danger" role="alert" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      <div className="btn-row">
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          {submitting ? "Working…" : mode === "create" ? "Create" : mode === "github" ? "Clone" : "Connect"}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  );
}
