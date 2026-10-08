import type { RetrievalEvidenceItem } from "../types";

// Deliberately does not display line ranges or numeric retrieval scores —
// the RAG evidence view communicates "what was retrieved and why," not
// low-level ranking details. That data remains available internally
// (RetrievalEvidenceItem still carries start_line/end_line/score) for
// workflow evaluation metrics; see app/services/workflow_evaluation.py.
export function EvidencePanel({ evidence }: { evidence: RetrievalEvidenceItem[] }) {
  if (evidence.length === 0) {
    return <div className="empty-state">No retrieval evidence recorded yet.</div>;
  }
  return (
    <div className="evidence-list">
      {evidence.map((e, i) => (
        <div className="evidence-row" key={i}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
            <span className="evidence-file">
              {e.file}
              {e.symbol && <span style={{ color: "var(--text-faint)" }}> [{e.symbol}]</span>}
            </span>
            {e.chunk_type && <span className="tag">{e.chunk_type}</span>}
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
