import { useState } from "react";
import type { ProposedChangeItem } from "../types";
import { DiffViewer } from "./DiffViewer";

interface Props {
  changes: ProposedChangeItem[];
  state: string;
  busy: boolean;
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
}

function opClass(op: string) {
  if (op === "create") return "create";
  if (op === "delete") return "delete";
  return "modify";
}

function confidenceLabel(c: number) {
  if (c >= 0.8) return { label: `${Math.round(c * 100)}% confidence`, cls: "success" };
  if (c >= 0.5) return { label: `${Math.round(c * 100)}% confidence`, cls: "warn" };
  return { label: `${Math.round(c * 100)}% confidence`, cls: "danger" };
}

export function DiffReview({ changes, state, busy, onApprove, onReject }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [comment, setComment] = useState("");

  const canApprove = state === "AWAITING_CHANGE_APPROVAL";
  const current = changes[selectedIdx] ?? null;

  if (changes.length === 0) {
    if (!canApprove) return <div className="empty-state">No proposed changes yet.</div>;
    return (
      <div>
        <div className="empty-state">No code changes were generated, so there is nothing to approve.</div>
        <div className="btn-row">
          <button className="btn btn-danger" disabled={busy} onClick={() => onReject(comment)}>
            Reject / Request revision
          </button>
        </div>
      </div>
    );
  }

  // A proposed change with an empty patch changes nothing (e.g. mock mode had
  // no strategy for this intent) and must not be presented as a modification.
  const hasDiff = (c: ProposedChangeItem) => c.patch.trim().length > 0;
  const real = changes.filter(hasDiff);
  const noChange = changes.length - real.length;
  const added = real.filter((c) => c.operation === "create").length;
  const modified = real.filter((c) => c.operation === "modify").length;
  const deleted = real.filter((c) => c.operation === "delete").length;
  // Clicking the open file again closes it.
  const toggle = (i: number) => setSelectedIdx((prev) => (prev === i ? -1 : i));

  const detail = (c: ProposedChangeItem) => (
    <>
      <div className="diff-content-header">
        <span className="diff-file-path">{c.file}</span>
        <span className={`diff-confidence tag ${confidenceLabel(c.confidence).cls}`}>
          {confidenceLabel(c.confidence).label}
        </span>
      </div>
      <div className="diff-reason-block">
        {c.reason}
        {c.acceptance_criterion && (
          <span style={{ marginLeft: 10, color: "var(--success)", fontSize: 12 }}>
            ✓ {c.acceptance_criterion}
          </span>
        )}
      </div>
      {c.risks.length > 0 && (
        <div className="diff-risk-block">
          ⚠ {c.risks.join(" · ")}
        </div>
      )}
      <DiffViewer patch={c.patch} />
    </>
  );

  return (
    <div>
      {/* Summary row */}
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {changes.length} file{changes.length !== 1 ? "s" : ""}
        </span>
        {added > 0 && <span className="tag success">+{added} created</span>}
        {modified > 0 && <span className="tag accent">{modified} modified</span>}
        {deleted > 0 && <span className="tag danger">{deleted} deleted</span>}
        {noChange > 0 && <span className="tag">{noChange} no change</span>}
      </div>

      {/* File list + diff panel. On narrow screens the panel is hidden and the
          selected file's diff opens right under its row instead. */}
      <div className="diff-layout">
        {/* Left: file list */}
        <div className="diff-file-list">
          {changes.map((c, i) => (
            <div key={c.id}>
              <div
                className={`diff-file-item${i === selectedIdx ? " selected" : ""}`}
                onClick={() => toggle(i)}
                role="button"
                tabIndex={0}
                aria-expanded={i === selectedIdx}
                onKeyDown={(e) => e.key === "Enter" && toggle(i)}
              >
                <span className={`diff-op-tag ${hasDiff(c) ? opClass(c.operation) : ""}`}>{hasDiff(c) ? c.operation : "no change"}</span>
                <span className="diff-file-name" title={c.file}>{c.file.split("/").pop()}</span>
              </div>
              {i === selectedIdx && <div className="diff-inline">{detail(c)}</div>}
            </div>
          ))}
        </div>

        {/* Right: diff content */}
        <div className="diff-content-area">
          {current ? detail(current) : <div className="empty-state">Select a file to view its diff.</div>}
        </div>
      </div>

      {/* Approval controls */}
      {canApprove && (
        <div style={{ marginTop: 16 }}>
          <label>Review comment (optional)</label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Notes for this approval or rejection…"
            style={{ marginBottom: 10 }}
          />
          <div className="btn-row">
            <button className="btn btn-success" disabled={busy || real.length === 0} onClick={() => onApprove(comment)}>
              Approve all changes
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => onReject(comment)}>
              Reject / Request revision
            </button>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 6 }}>
            {real.length === 0
              ? "Nothing to approve: no code was generated. Set LLM_MODE=live with an API key for real code generation."
              : "Approving applies all changes. Rejecting regenerates the diff from the plan."}
          </div>
        </div>
      )}

      {state === "CHANGES_REJECTED" && (
        <div className="callout callout-danger" style={{ marginTop: 12 }}>
          Changes rejected. Regenerate from the plan to produce a new diff.
        </div>
      )}
    </div>
  );
}
