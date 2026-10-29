import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import type {
  ManagedRepository,
  RepoFile,
  RepoInsights,
  RepoTextMatch,
  RepoTreeEntry,
  RetrievalEvidenceItem,
  Workflow,
} from "../types";
import { RepoStatusBadge } from "../components/RepoStatusBadge";
import { branchSummary, indexSummary, isBusy, kindLabel, timeAgo } from "../services/repoMeta";
import { StatusBadge } from "../components/StatusBadge";

type Tab = "files" | "search" | "rag" | "workflows";

function errText(e: unknown): string {
  return String(e instanceof Error ? e.message : e);
}

export function RepositoryWorkspacePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [repo, setRepo] = useState<ManagedRepository | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState<Tab>("files");
  const [actionError, setActionError] = useState("");
  const [acting, setActing] = useState<string | null>(null);
  const [openFile, setOpenFile] = useState<{ path: string; line?: number } | null>(null);
  const [syncToken, setSyncToken] = useState("");
  const [showSyncAuth, setShowSyncAuth] = useState(false);

  const load = useCallback(
    () =>
      api
        .getManagedRepository(id)
        .then((r) => {
          setRepo(r);
          setLoadError("");
        })
        .catch((e) => setLoadError(errText(e))),
    [id]
  );

  useEffect(() => {
    load();
  }, [load]);

  const busy = repo ? isBusy(repo) : false;
  useEffect(() => {
    if (!busy) return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [busy, repo, load]);

  async function act(name: string, fn: () => Promise<unknown>) {
    setActing(name);
    setActionError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setActing(null);
    }
  }

  function sync() {
    if (repo?.is_private) {
      setShowSyncAuth(true); // private pulls need a token, asked for each time
      return;
    }
    act("sync", () => api.syncRepository(id, { reindex: true }));
  }

  async function disconnect() {
    if (!repo) return;
    const note = repo.kind === "github" ? " The local clone is removed if no workflow run uses it." : " Files on disk are not touched.";
    if (!window.confirm(`Disconnect ${repo.name}?${note}`)) return;
    setActing("disconnect");
    try {
      await api.disconnectRepository(id);
      navigate("/repositories");
    } catch (e) {
      setActionError(errText(e));
      setActing(null);
    }
  }

  if (loadError && !repo) {
    return (
      <div>
        <Link to="/repositories" className="back-link">← Repositories</Link>
        <div className="callout callout-danger" style={{ marginTop: 12 }}>{loadError}</div>
      </div>
    );
  }
  if (!repo) return <div className="empty-state">Loading…</div>;

  const usable = repo.accessible && repo.status !== "cloning";

  return (
    <div>
      <Link to="/repositories" className="back-link">← Repositories</Link>
      <div className="page-head" style={{ marginTop: 8 }}>
        <div style={{ minWidth: 0 }}>
          <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {repo.name} <RepoStatusBadge repo={repo} />
          </h1>
          <div className="ws-meta">
            <span>{kindLabel(repo)}</span>
            <span className="mono" title={repo.local_path}>{repo.kind === "github" ? repo.source : repo.local_path}</span>
            <span className="mono">{branchSummary(repo)}</span>
            <span>{indexSummary(repo)}</span>
          </div>
        </div>
        <div className="btn-row" style={{ marginTop: 0, flexShrink: 0 }}>
          <button
            className="btn btn-primary"
            disabled={!usable || busy}
            onClick={() => navigate(`/new-workflow?repository=${repo.id}`)}
          >
            New workflow
          </button>
          <button className="btn" disabled={!usable || busy || acting !== null} onClick={() => act("reindex", () => api.reindexRepository(id))}>
            {repo.status === "indexing" ? "Indexing…" : repo.indexed_at ? "Re-index" : "Index"}
          </button>
          {repo.kind === "github" && (
            <button className="btn" disabled={busy || acting !== null} onClick={sync}>
              {repo.status === "syncing" ? "Pulling…" : repo.accessible ? "Pull" : "Retry clone"}
            </button>
          )}
          <button className="btn btn-danger" disabled={busy || acting !== null} onClick={disconnect}>
            Disconnect
          </button>
        </div>
      </div>

      {showSyncAuth && (
        <div className="card repo-form" style={{ maxWidth: 520 }}>
          <label htmlFor="sync-token">Access token for {repo.name}</label>
          <input
            id="sync-token"
            type="password"
            value={syncToken}
            onChange={(e) => setSyncToken(e.target.value)}
            autoComplete="off"
            placeholder="Leave empty to use the server GITHUB_TOKEN"
          />
          <div className="btn-row">
            <button
              className="btn btn-primary"
              disabled={acting !== null}
              onClick={() =>
                act("sync", async () => {
                  await api.syncRepository(id, { token: syncToken.trim(), use_server_token: !syncToken.trim(), reindex: true });
                  setSyncToken("");
                  setShowSyncAuth(false);
                })
              }
            >
              Pull
            </button>
            <button className="btn" onClick={() => { setShowSyncAuth(false); setSyncToken(""); }}>Cancel</button>
          </div>
        </div>
      )}

      {repo.status === "error" && repo.status_detail && <div className="callout callout-danger">{repo.status_detail}</div>}
      {!repo.accessible && repo.status !== "cloning" && repo.status !== "error" && (
        <div className="callout callout-danger">Path not found or unreadable: <code>{repo.local_path}</code></div>
      )}
      {actionError && <div className="callout callout-danger">{actionError}</div>}

      <div className="tabs">
        {(["files", "search", "rag", "workflows"] as Tab[]).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "files" ? "Files" : t === "search" ? "Search" : t === "rag" ? "RAG" : `Workflows${repo.workflow_count ? ` (${repo.workflow_count})` : ""}`}
          </button>
        ))}
      </div>

      {!usable && tab !== "workflows" ? (
        <div className="empty-state">{repo.status === "cloning" ? "Cloning…" : "Repository files are not available."}</div>
      ) : tab === "files" ? (
        <FilesTab repoId={id} open={openFile} onOpen={setOpenFile} />
      ) : tab === "search" ? (
        <SearchTab
          repo={repo}
          onOpenMatch={(path, line) => {
            setOpenFile({ path, line });
            setTab("files");
          }}
        />
      ) : tab === "rag" ? (
        <RagTab repo={repo} onReindex={() => act("reindex", () => api.reindexRepository(id))} />
      ) : (
        <WorkflowsTab repoId={id} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------
function FilesTab({
  repoId,
  open,
  onOpen,
}: {
  repoId: string;
  open: { path: string; line?: number } | null;
  onOpen: (f: { path: string; line?: number }) => void;
}) {
  const [children, setChildren] = useState<Record<string, RepoTreeEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set([""]));
  const [treeError, setTreeError] = useState("");
  const [file, setFile] = useState<RepoFile | null>(null);
  const [fileError, setFileError] = useState("");
  const [fileLoading, setFileLoading] = useState(false);

  const loadDir = useCallback(
    (path: string) =>
      api
        .getRepoTree(repoId, path)
        .then((r) => setChildren((c) => ({ ...c, [path]: r.entries })))
        .catch((e) => setTreeError(errText(e))),
    [repoId]
  );

  useEffect(() => {
    loadDir("");
  }, [loadDir]);

  // Expand ancestors of a file opened from search.
  useEffect(() => {
    if (!open) return;
    const parts = open.path.split("/");
    const ancestors = parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
    setExpanded((prev) => new Set([...prev, ...ancestors]));
    ancestors.forEach((a) => {
      if (!children[a]) loadDir(a);
    });
    setFileLoading(true);
    setFileError("");
    api
      .getRepoFile(repoId, open.path)
      .then(setFile)
      .catch((e) => {
        setFile(null);
        setFileError(errText(e));
      })
      .finally(() => setFileLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, repoId]);

  function toggle(entry: RepoTreeEntry) {
    if (entry.type === "file") {
      onOpen({ path: entry.path });
      return;
    }
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(entry.path)) next.delete(entry.path);
      else {
        next.add(entry.path);
        if (!children[entry.path]) loadDir(entry.path);
      }
      return next;
    });
  }

  function renderDir(path: string, depth: number): React.ReactNode {
    const entries = children[path];
    if (!entries) return <div className="tree-row muted" style={{ paddingLeft: 10 + depth * 14 }}>…</div>;
    if (entries.length === 0) return <div className="tree-row muted" style={{ paddingLeft: 10 + depth * 14 }}>empty</div>;
    return entries.map((e) => (
      <div key={e.path}>
        <button
          type="button"
          className={`tree-row ${open?.path === e.path ? "selected" : ""} ${e.ignored || e.restricted ? "muted" : ""}`}
          style={{ paddingLeft: 10 + depth * 14 }}
          onClick={() => toggle(e)}
          title={e.restricted ? "May contain secrets — not shown" : e.ignored ? "Excluded from indexing" : e.path}
        >
          <span className="tree-caret">{e.type === "dir" ? (expanded.has(e.path) ? "▾" : "▸") : ""}</span>
          {e.name}
        </button>
        {e.type === "dir" && expanded.has(e.path) && renderDir(e.path, depth + 1)}
      </div>
    ));
  }

  return (
    <div className="ws-files">
      <div className="ws-tree">{treeError ? <div className="callout callout-danger">{treeError}</div> : renderDir("", 0)}</div>
      <div className="ws-viewer">
        {fileLoading ? (
          <div className="empty-state">Loading…</div>
        ) : fileError ? (
          <div className="empty-state">{fileError}</div>
        ) : file ? (
          <CodeView file={file} line={open?.line} />
        ) : (
          <div className="empty-state">Select a file.</div>
        )}
      </div>
    </div>
  );
}

function CodeView({ file, line }: { file: RepoFile; line?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!line || !ref.current) return;
    // Scroll only the code pane (scrollIntoView would also shift the outer layout).
    const el = ref.current.querySelector<HTMLElement>(`[data-line="${line}"]`);
    if (el) ref.current.scrollTop = el.offsetTop - ref.current.clientHeight / 2;
  }, [file, line]);
  const lines = file.content.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return (
    <>
      <div className="ws-viewer-head">
        <span className="mono">{file.path}</span>
        <span>
          {file.language} · {file.lines} lines · {(file.size / 1024).toFixed(1)} KB
        </span>
      </div>
      <div className="code-view" ref={ref}>
        {lines.map((l, i) => (
          <div key={i} data-line={i + 1} className={`code-line ${line === i + 1 ? "hl" : ""}`}>
            <span className="ln">{i + 1}</span>
            <span className="lc">{l || " "}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function SearchTab({ repo, onOpenMatch }: { repo: ManagedRepository; onOpenMatch: (path: string, line?: number) => void }) {
  const [mode, setMode] = useState<"text" | "semantic">("text");
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState<{ results: RepoTextMatch[]; truncated: boolean; files_scanned: number } | null>(null);
  const [semantic, setSemantic] = useState<RetrievalEvidenceItem[] | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      if (mode === "text") {
        setText(await api.grepRepository(repo.id, query, caseSensitive));
      } else {
        setSemantic((await api.searchRepository(repo.id, query, 10)).results);
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setLoading(false);
    }
  }

  const grouped = text
    ? text.results.reduce<Record<string, RepoTextMatch[]>>((acc, r) => {
        (acc[r.file] ||= []).push(r);
        return acc;
      }, {})
    : {};

  return (
    <div>
      <form className="search-bar" onSubmit={run}>
        <div className="seg">
          <button type="button" className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Text</button>
          <button type="button" className={mode === "semantic" ? "on" : ""} onClick={() => setMode("semantic")}>Semantic</button>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={mode === "text" ? "Exact text, e.g. def process_payment" : "Describe what you're looking for"}
          spellCheck={false}
          autoFocus
        />
        {mode === "text" && (
          <label className="check" style={{ whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} /> Aa
          </label>
        )}
        <button className="btn btn-primary" disabled={loading || !query.trim() || (mode === "semantic" && !repo.indexed_at)}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>
      {mode === "semantic" && !repo.indexed_at && <div className="hint">Index the repository to enable semantic search.</div>}
      {error && <div className="callout callout-danger">{error}</div>}

      {mode === "text" && text && (
        <div className="search-results">
          <div className="hint">
            {text.results.length} matches in {Object.keys(grouped).length} files{text.truncated ? " (truncated)" : ""} · {text.files_scanned} files scanned
          </div>
          {Object.entries(grouped).map(([file, matches]) => (
            <div key={file} className="match-group">
              <button type="button" className="match-file mono" onClick={() => onOpenMatch(file)}>{file}</button>
              {matches.map((m) => (
                <button key={m.line} type="button" className="match-line" onClick={() => onOpenMatch(file, m.line)}>
                  <span className="ln">{m.line}</span>
                  <span className="mono">{m.text}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {mode === "semantic" && semantic && (
        <div className="search-results">
          {semantic.length === 0 ? (
            <div className="empty-state">No matches.</div>
          ) : (
            semantic.map((r, i) => (
              <div key={i} className="match-group">
                <button type="button" className="match-file mono" onClick={() => onOpenMatch(r.file, r.start_line)}>
                  {r.file}:{r.start_line}–{r.end_line}
                  {r.symbol ? ` · ${r.symbol}` : ""}
                </button>
                <div className="hint" style={{ margin: "2px 0 6px" }}>{r.retrieval_method} · {r.reason}</div>
                {r.content_preview && <pre className="mono-block" style={{ maxHeight: 140 }}>{r.content_preview}</pre>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RAG
// ---------------------------------------------------------------------------
function RagTab({ repo, onReindex }: { repo: ManagedRepository; onReindex: () => void }) {
  const [insights, setInsights] = useState<RepoInsights | null>(null);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<{ answer: string; cited_files: string[] } | null>(null);

  useEffect(() => {
    if (repo.status === "indexing") return;
    api.getRepoInsights(repo.id).then(setInsights).catch((e) => setError(errText(e)));
  }, [repo.id, repo.indexed_at, repo.status]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError("");
    try {
      const r = await api.askRepository(repo.id, question);
      setAnswer({ answer: r.answer, cited_files: r.cited_files });
    } catch (err) {
      setError(errText(err));
    } finally {
      setAsking(false);
    }
  }

  if (repo.status === "indexing") return <div className="empty-state">Indexing…</div>;
  if (error) return <div className="callout callout-danger">{error}</div>;
  if (!insights) return <div className="empty-state">Loading…</div>;
  if (!insights.indexed) {
    return (
      <div className="empty-state">
        Not indexed.{" "}
        <button className="btn btn-primary" style={{ marginLeft: 8 }} onClick={onReindex}>Index now</button>
      </div>
    );
  }

  return (
    <div>
      <div className="kv-strip">
        <div><span className="k">Files</span><span className="v">{insights.files}</span></div>
        <div><span className="k">Chunks</span><span className="v">{insights.chunks}</span></div>
        <div><span className="k">Symbols</span><span className="v">{insights.symbols}</span></div>
        <div><span className="k">Indexed</span><span className="v">{timeAgo(insights.indexed_at ?? null)}</span></div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div>
          <div className="section-label">Languages</div>
          <table className="compact">
            <tbody>
              {insights.languages?.map((l) => (
                <tr key={l.language}><td>{l.language}</td><td className="num">{l.files} files</td></tr>
              ))}
            </tbody>
          </table>
          <div className="section-label" style={{ marginTop: 14 }}>Chunk types</div>
          <table className="compact">
            <tbody>
              {insights.chunk_types?.map((c) => (
                <tr key={c.type}><td>{c.type}</td><td className="num">{c.count}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <div className="section-label">Most chunks</div>
          <table className="compact">
            <tbody>
              {insights.largest_files?.map((f) => (
                <tr key={f.file}><td className="mono">{f.file}</td><td className="num">{f.chunks}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <form className="search-bar" style={{ marginTop: 20 }} onSubmit={ask}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about this codebase" />
        <button className="btn btn-primary" disabled={asking || !question.trim()}>{asking ? "Asking…" : "Ask"}</button>
      </form>
      {answer && (
        <div className="answer">
          <p>{answer.answer}</p>
          {answer.cited_files.length > 0 && (
            <div className="ws-meta">{answer.cited_files.map((f) => <span key={f} className="mono">{f}</span>)}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------
function WorkflowsTab({ repoId }: { repoId: string }) {
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.getRepoWorkflows(repoId).then(setWorkflows).catch((e) => setError(errText(e)));
  }, [repoId]);

  if (error) return <div className="callout callout-danger">{error}</div>;
  if (!workflows) return <div className="empty-state">Loading…</div>;
  if (workflows.length === 0) return <div className="empty-state">No workflow runs for this repository.</div>;
  return (
    <table>
      <thead>
        <tr><th>Intent</th><th>State</th><th>Branch</th><th>Started</th></tr>
      </thead>
      <tbody>
        {workflows.map((w) => (
          <tr key={w.id}>
            <td><Link to={`/workflows/${w.id}`}>{w.intent.length > 90 ? `${w.intent.slice(0, 90)}…` : w.intent}</Link></td>
            <td><StatusBadge state={w.state} /></td>
            <td className="mono">{w.branch_name || "—"}</td>
            <td>{timeAgo(w.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
