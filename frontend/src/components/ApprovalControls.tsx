import { useState } from "react";

export function ApprovalControls({
  onApprove,
  onReject,
  approveLabel = "Approve",
  rejectLabel = "Reject / Request Revision",
  disabled,
}: {
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
  approveLabel?: string;
  rejectLabel?: string;
  disabled?: boolean;
}) {
  const [comment, setComment] = useState("");
  return (
    <div>
      <label>Comment (optional)</label>
      <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add review notes..." />
      <div className="btn-row">
        <button className="btn btn-success" disabled={disabled} onClick={() => onApprove(comment)}>
          {approveLabel}
        </button>
        <button className="btn btn-danger" disabled={disabled} onClick={() => onReject(comment)}>
          {rejectLabel}
        </button>
      </div>
    </div>
  );
}
