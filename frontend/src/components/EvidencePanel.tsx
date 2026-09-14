import type { RetrievalEvidenceItem } from "../types";

export function EvidencePanel({ evidence }: { evidence: RetrievalEvidenceItem[] }) {
  if (evidence.length === 0) {
    return <div className="empty-state">No retrieval evidence recorded yet.</div>;
  }
  return (
    <div>
      {evidence.map((e, i) => (
        <div className="evidence-item" key={i}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span className="evidence-file">
              {e.file}:{e.start_line}-{e.end_line}
              {e.symbol && <span style={{ color: "var(--text-faint)" }}> [{e.symbol}]</span>}
            </span>
            <span className="badge badge-accent">score {e.score.toFixed(2)}</span>
          </div>
          <div className="evidence-reason">
            via {e.retrieval_method} — {e.reason}
          </div>
          {e.content_preview && <pre className="mono-block" style={{ marginTop: 6, maxHeight: 120 }}>{e.content_preview}</pre>}
        </div>
      ))}
    </div>
  );
}
