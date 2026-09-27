import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { Project, Repository, RetrievalEvidenceItem } from "../types";
import { EvidencePanel } from "../components/EvidencePanel";

export function RepositoryIntelligencePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repositoryId, setRepositoryId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [newProjectName, setNewProjectName] = useState("Demo Project");
  const [newRepoPath, setNewRepoPath] = useState("../demo-repository");
  const [indexing, setIndexing] = useState(false);

  const [searchQuery, setSearchQuery] = useState("Where is payment processing implemented?");
  const [searchTopK, setSearchTopK] = useState(8);
  const [searchResults, setSearchResults] = useState<RetrievalEvidenceItem[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [question, setQuestion] = useState("Where can duplicate payment requests occur?");
  const [asking, setAsking] = useState(false);
  const [qa, setQa] = useState<{ question: string; answer: string; cited_files: string[]; evidence: RetrievalEvidenceItem[] } | null>(null);

  function loadAll() {
    setLoading(true);
    Promise.all([api.listProjects(), api.listRepositories()])
      .then(([projs, repos]) => {
        setProjects(projs);
        setRepositories(repos);
        if (repos.length > 0 && !repositoryId) setRepositoryId(repos[0].id);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleIndex() {
    setIndexing(true);
    setError("");
    try {
      let project = projects.find((p) => p.name === newProjectName);
      if (!project) project = await api.createProject(newProjectName);
      const repo = await api.indexRepository(project.id, newRepoPath);
      loadAll();
      setRepositoryId(repo.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setIndexing(false);
    }
  }

  async function handleSearch() {
    if (!repositoryId || !searchQuery.trim()) return;
    setSearching(true);
    setError("");
    try {
      const r = await api.searchRepository(repositoryId, searchQuery, searchTopK);
      setSearchResults(r.results);
    } catch (e) {
      setError(String(e));
    } finally {
      setSearching(false);
    }
  }

  async function handleAsk() {
    if (!repositoryId || !question.trim()) return;
    setAsking(true);
    setError("");
    try {
      const r = await api.askRepository(repositoryId, question);
      setQa({ question, ...r });
    } catch (e) {
      setError(String(e));
    } finally {
      setAsking(false);
    }
  }

  const activeRepo = repositories.find((r) => r.id === repositoryId);
  const projectName = (repo: Repository) => projects.find((p) => p.id === repo.project_id)?.name || repo.project_id;

  return (
    <div>
      <h1 className="page-title">Repository Intelligence</h1>
      <p className="page-subtitle">
        Real indexing, real ChromaDB retrieval, real repository-grounded Q&amp;A — nothing here is hardcoded or
        pre-scripted.
      </p>

      {error && (
        <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
          {error}
        </div>
      )}

      <div className="grid grid-2">
        <div className="card">
          <div className="card-title">Repository</div>
          {loading ? (
            <div className="empty-state">Loading…</div>
          ) : repositories.length === 0 ? (
            <div className="empty-state">No repositories indexed yet — index one on the right.</div>
          ) : (
            <>
              <select value={repositoryId} onChange={(e) => { setRepositoryId(e.target.value); setSearchResults(null); setQa(null); }}>
                {repositories.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.source} ({projectName(r)})
                  </option>
                ))}
              </select>
              {activeRepo && (
                <div style={{ marginTop: 12, fontSize: 12.5, color: "var(--text-muted)" }}>
                  <div><b>Files indexed:</b> {activeRepo.file_count}</div>
                  <div><b>Chunks created:</b> {activeRepo.chunk_count}</div>
                  <div><b>Vector store:</b> ChromaDB</div>
                  <div>
                    <b>Status:</b>{" "}
                    {activeRepo.indexed_at ? (
                      <span className="badge badge-success">Indexed</span>
                    ) : (
                      <span className="badge badge-neutral">Not indexed</span>
                    )}
                  </div>
                  <div><b>Indexed at:</b> {activeRepo.indexed_at ? new Date(activeRepo.indexed_at).toLocaleString() : "—"}</div>
                  <div><b>Local path:</b> <code style={{ fontSize: 11.5 }}>{activeRepo.local_path}</code></div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="card">
          <div className="card-title">Index a Repository</div>
          <label>Project name</label>
          <input value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} />
          <label>Repository path (local)</label>
          <input value={newRepoPath} onChange={(e) => setNewRepoPath(e.target.value)} placeholder="../demo-repository" />
          <div className="btn-row">
            <button className="btn btn-primary" disabled={indexing || !newRepoPath} onClick={handleIndex}>
              {indexing ? "Indexing…" : "Index Repository"}
            </button>
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 8 }}>
            Re-indexing the same path replaces its ChromaDB collection — indexing is idempotent, it never
            accumulates duplicate chunks.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Semantic Search</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Where is payment processing implemented?" />
          <input
            type="number"
            min={1}
            max={20}
            value={searchTopK}
            onChange={(e) => setSearchTopK(Number(e.target.value) || 8)}
            style={{ width: 70 }}
          />
          <button className="btn btn-primary" disabled={searching || !repositoryId} onClick={handleSearch}>
            {searching ? "Searching…" : "Search"}
          </button>
        </div>
        {searchResults && (
          <div style={{ marginTop: 14 }}>
            {searchResults.length === 0 ? (
              <div className="empty-state">No matching chunks retrieved for this query.</div>
            ) : (
              <EvidencePanel evidence={searchResults} />
            )}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">RAG Q&amp;A</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Where can duplicate payment requests occur?" />
          <button className="btn btn-primary" disabled={asking || !repositoryId} onClick={handleAsk}>
            {asking ? "Thinking…" : "Ask"}
          </button>
        </div>
        {qa && (
          <div style={{ marginTop: 14 }}>
            <div className="gr-field-label">Question</div>
            <p style={{ fontSize: 13.5 }}>{qa.question}</p>
            <div className="gr-field-label">Answer</div>
            <p style={{ fontSize: 13.5 }}>{qa.answer}</p>
            <div className="gr-field-label">Retrieved Sources</div>
            {qa.cited_files.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--text-faint)" }}>No sources were cited.</p>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {qa.cited_files.map((f) => (
                  <code key={f} className="badge badge-accent">{f}</code>
                ))}
              </div>
            )}
            <div className="gr-field-label">Source Preview</div>
            <EvidencePanel evidence={qa.evidence} />
          </div>
        )}
      </div>
    </div>
  );
}
