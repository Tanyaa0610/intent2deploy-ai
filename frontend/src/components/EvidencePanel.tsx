import type { RetrievalEvidenceItem } from "../types";

function relevance(score: number): { label: string; cls: string } {
  if (score >= 0.75) return { label: "High relevance", cls: "high" };
  if (score >= 0.5) return { label: "Relevant", cls: "medium" };
  return { label: "Supporting evidence", cls: "low" };
}

export function EvidencePanel({ evidence }: { evidence: RetrievalEvidenceItem[] }) {
  if (evidence.length === 0) {
    return <div className="empty-state">No retrieval evidence recorded yet.</div>;
  }
  return (
    <div className="evidence-list">
      {evidence.map((e, i) => {
        const r = relevance(e.score);
        return (
          <div className="evidence-row" key={i}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
              <span className="evidence-file">
                {e.file}:{e.start_line}-{e.end_line}
                {e.symbol && <span style={{ color: "var(--text-faint)" }}> [{e.symbol}]</span>}
              </span>
              <span className={`evidence-relevance ${r.cls}`}>{r.label}</span>
            </div>
            <div className="evidence-reason">
              via {e.retrieval_method} — {e.reason}
            </div>
            {e.content_preview && <pre className="mono-block" style={{ marginTop: 6, maxHeight: 120 }}>{e.content_preview}</pre>}
          </div>
        );
      })}
    </div>
  );
}
