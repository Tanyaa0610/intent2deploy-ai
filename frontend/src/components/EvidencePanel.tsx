import { useMemo, useState, type ReactNode } from "react";
import type { RetrievalEvidenceItem } from "../types";

// Deliberately does not display line ranges or numeric retrieval scores —
// the RAG evidence view communicates "what was retrieved and why," not
// low-level ranking details. That data remains available internally
// (RetrievalEvidenceItem still carries start_line/end_line/score) for
// workflow evaluation metrics; see app/services/workflow_evaluation.py.
//
// Interactive: filter by kind, search, group by file, expand a chunk to read it.

const KIND_ICONS: Record<string, string> = {
  module: "📦", function: "ƒ", class: "◆", test: "🧪", config: "⚙️", doc: "📄", other: "•",
};
const METHOD_LABELS: Record<string, string> = { semantic: "meaning", keyword: "keywords", symbol: "symbol name" };

function methods(e: RetrievalEvidenceItem): string[] {
  return (e.retrieval_method || "").split("+").map((m) => m.trim()).filter(Boolean);
}

/** The "why" in plain words, without the similarity numbers. */
function whyMatched(e: RetrievalEvidenceItem): string {
  const parts = methods(e).map((m) => METHOD_LABELS[m] ?? m);
  const symbol = e.reason.match(/symbol '([^']+)'/)?.[1];
  return `Matched by ${parts.join(" + ") || "retrieval"}${symbol ? ` — the name '${symbol}' fits the request` : ""}.`;
}

function ChunkCard({ e, rank, open, onToggle }: { e: RetrievalEvidenceItem; rank: number; open: boolean; onToggle: () => void }) {
  const [copied, setCopied] = useState(false);
  const firstLine = (e.content_preview || "").split("\n").find((l) => l.trim()) ?? "";
  return (
    <div className={`ev-card${open ? " open" : ""}`} style={{ animationDelay: `${Math.min(rank, 12) * 35}ms` }}>
      <button type="button" className="ev-card-head" onClick={onToggle} aria-expanded={open}>
        <span className="ev-rank">#{rank + 1}</span>
        <span className="ev-kind" title={e.chunk_type}>{KIND_ICONS[e.chunk_type] ?? "•"}</span>
        <span className="ev-title">
          {e.symbol ? <><strong>{e.symbol}</strong><span className="ev-file-dim"> · {e.file}</span></> : <strong>{e.file}</strong>}
        </span>
        <span className="ev-methods">
          {methods(e).map((m) => <span key={m} className={`ev-method ${m}`}>{METHOD_LABELS[m] ?? m}</span>)}
        </span>
        <span className="ev-chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {!open && firstLine && <div className="ev-peek">{firstLine.trim()}</div>}
      {open && (
        <div className="ev-body">
          <div className="ev-why">{whyMatched(e)}</div>
          {e.content_preview && (
            <div className="ev-code-wrap">
              <button
                type="button"
                className="ev-copy"
                onClick={() => {
                  navigator.clipboard?.writeText(e.content_preview).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1200);
                  });
                }}
              >
                {copied ? "Copied ✓" : "Copy"}
              </button>
              <pre className="mono-block ev-code">{e.content_preview}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function EvidencePanel({ evidence, belowToolbar }: { evidence: RetrievalEvidenceItem[]; belowToolbar?: ReactNode }) {
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [byFile, setByFile] = useState(true);
  const [open, setOpen] = useState<Set<number>>(new Set([0]));
  const [closedFiles, setClosedFiles] = useState<Set<string>>(new Set());

  const ranked = useMemo(() => evidence.map((e, i) => ({ e, i })), [evidence]);
  const kinds = useMemo(() => {
    const counts: Record<string, number> = {};
    evidence.forEach((e) => { counts[e.chunk_type || "other"] = (counts[e.chunk_type || "other"] ?? 0) + 1; });
    return counts;
  }, [evidence]);
  const files = new Set(evidence.map((e) => e.file));

  const q = query.trim().toLowerCase();
  const visible = ranked.filter(({ e }) =>
    (kind === "all" || (e.chunk_type || "other") === kind) &&
    (!q || e.file.toLowerCase().includes(q) || e.symbol?.toLowerCase().includes(q) || e.content_preview?.toLowerCase().includes(q))
  );
  const groups = useMemo(() => {
    const out: { file: string; items: typeof visible }[] = [];
    for (const v of visible) {
      const g = out.find((x) => x.file === v.e.file);
      if (g) g.items.push(v);
      else out.push({ file: v.e.file, items: [v] });
    }
    return out;
  }, [visible]);

  if (evidence.length === 0) {
    return <div className="empty-state">No retrieval evidence recorded yet.</div>;
  }

  const toggle = (i: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  const allOpen = visible.length > 0 && visible.every(({ i }) => open.has(i));

  return (
    <div className="ev">
      <div className="ev-summary">
        <div><strong>{evidence.length}</strong><span>pieces of code</span></div>
        <div><strong>{files.size}</strong><span>files</span></div>
        <div><strong>{Object.keys(kinds).length}</strong><span>kinds</span></div>
      </div>

      <div className="ev-toolbar">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search files, functions or code…"
          aria-label="Search retrieved code"
        />
        <div className="ev-filters" role="group" aria-label="Filter by kind">
          <button type="button" className={`ev-filter${kind === "all" ? " active" : ""}`} onClick={() => setKind("all")}>
            All <span>{evidence.length}</span>
          </button>
          {Object.entries(kinds).map(([k, n]) => (
            <button key={k} type="button" className={`ev-filter${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
              {KIND_ICONS[k] ?? "•"} {k} <span>{n}</span>
            </button>
          ))}
        </div>
        <div className="ev-actions">
          <button type="button" className="btn" onClick={() => setByFile((v) => !v)}>
            {byFile ? "☰ List view" : "🗂 Group by file"}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setOpen(allOpen ? new Set() : new Set(visible.map(({ i }) => i)))}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        </div>
      </div>

      {belowToolbar}

      {visible.length === 0 && (
        <div className="empty-state">
          Nothing matches.{" "}
          <button type="button" className="btn" onClick={() => { setQuery(""); setKind("all"); }}>Clear filters</button>
        </div>
      )}

      {byFile
        ? groups.map((g) => {
            const closed = closedFiles.has(g.file);
            return (
              <div key={g.file} className="ev-group">
                <button
                  type="button"
                  className="ev-group-head"
                  onClick={() =>
                    setClosedFiles((prev) => {
                      const next = new Set(prev);
                      if (next.has(g.file)) next.delete(g.file);
                      else next.add(g.file);
                      return next;
                    })
                  }
                  aria-expanded={!closed}
                >
                  <span className="ev-chevron" aria-hidden="true">{closed ? "▸" : "▾"}</span>
                  <code>{g.file}</code>
                  <span className="ev-group-count">{g.items.length} piece{g.items.length !== 1 ? "s" : ""}</span>
                </button>
                {!closed && g.items.map(({ e, i }) => (
                  <ChunkCard key={i} e={e} rank={i} open={open.has(i)} onToggle={() => toggle(i)} />
                ))}
              </div>
            );
          })
        : visible.map(({ e, i }) => <ChunkCard key={i} e={e} rank={i} open={open.has(i)} onToggle={() => toggle(i)} />)}
    </div>
  );
}
