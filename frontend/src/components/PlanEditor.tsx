import { useEffect, useState } from "react";
import type { PlanDetail, PlanStep, PlanStepUpdate } from "../types";
import { api } from "../services/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  workflowId: string;
  plan: PlanDetail;
  state: string;
  busy: boolean;
  onPlanChange: (p: PlanDetail) => void;
  onApprove: (comment: string) => void;
  onReject: (comment: string) => void;
}

function stepToUpdate(s: PlanStep): PlanStepUpdate {
  return { id: s.id, description: s.description, files: s.files ?? [] };
}

export function PlanEditor({ workflowId, plan, state, busy, onPlanChange, onApprove, onReject }: Props) {
  const [steps, setSteps] = useState<PlanStepUpdate[]>(() => plan.steps.map(stepToUpdate));
  const [summary, setSummary] = useState(plan.summary);
  const [criteria, setCriteria] = useState<string[]>(plan.acceptance_criteria);
  const [editingStep, setEditingStep] = useState<string | null>(null);
  const [editingCriterion, setEditingCriterion] = useState<number | null>(null);
  const [newCriterion, setNewCriterion] = useState("");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const [dirty, setDirty] = useState(false);

  const canEdit = state === "AWAITING_PLAN_APPROVAL" || state === "PLAN_REJECTED";

  // sync from parent when plan prop changes (e.g. after refresh)
  useEffect(() => {
    setSteps(plan.steps.map(stepToUpdate));
    setSummary(plan.summary);
    setCriteria(plan.acceptance_criteria);
    setDirty(false);
  }, [plan.id]);

  async function saveEdits() {
    setSaving(true);
    setSaveErr("");
    try {
      const updated = await api.updatePlan(workflowId, {
        summary,
        steps,
        acceptance_criteria: criteria,
      });
      onPlanChange(updated);
      setDirty(false);
    } catch (e) {
      setSaveErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  function updateStep(id: string, patch: Partial<PlanStepUpdate>) {
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    setDirty(true);
  }

  function removeStep(id: string) {
    setSteps((prev) => prev.filter((s) => s.id !== id));
    setDirty(true);
  }

  function moveStep(id: string, dir: -1 | 1) {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === id);
      if (idx < 0) return prev;
      const next = [...prev];
      const swap = idx + dir;
      if (swap < 0 || swap >= next.length) return prev;
      [next[idx], next[swap]] = [next[swap], next[idx]];
      return next;
    });
    setDirty(true);
  }

  function addStep() {
    const id = `step-${Date.now()}`;
    setSteps((prev) => [...prev, { id, description: "New step", files: [] }]);
    setEditingStep(id);
    setDirty(true);
  }

  function removeCriterion(i: number) {
    setCriteria((prev) => prev.filter((_, idx) => idx !== i));
    setDirty(true);
  }

  function updateCriterion(i: number, val: string) {
    setCriteria((prev) => prev.map((c, idx) => (idx === i ? val : c)));
    setDirty(true);
  }

  function addCriterion() {
    if (!newCriterion.trim()) return;
    setCriteria((prev) => [...prev, newCriterion.trim()]);
    setNewCriterion("");
    setDirty(true);
  }

  return (
    <div>
      {/* Summary */}
      <div style={{ marginBottom: 18 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Plan summary</div>
        {canEdit ? (
          <textarea
            value={summary}
            onChange={(e) => { setSummary(e.target.value); setDirty(true); }}
            style={{ minHeight: 72, fontSize: 13 }}
          />
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>{plan.summary}</p>
        )}
      </div>

      {/* Steps */}
      <div style={{ marginBottom: 18 }}>
        <div className="sec-header">
          <span className="sec-header-title">Implementation steps ({steps.length})</span>
          {canEdit && (
            <button className="sec-link" onClick={addStep} type="button">+ Add step</button>
          )}
        </div>
        <div className="plan-step-list">
          {steps.map((s, idx) => (
            <div key={s.id} className={`plan-step-row${editingStep === s.id ? " editing" : ""}`}>
              <span className="plan-step-drag" title="Drag to reorder">⋮⋮</span>
              <div className="plan-step-body">
                {editingStep === s.id && canEdit ? (
                  <div className="plan-step-edit-area">
                    <textarea
                      value={s.description}
                      onChange={(e) => updateStep(s.id, { description: e.target.value })}
                      style={{ minHeight: 52, fontSize: 13 }}
                      autoFocus
                    />
                    <input
                      type="text"
                      placeholder="Files (comma-separated)"
                      value={s.files.join(", ")}
                      onChange={(e) =>
                        updateStep(s.id, { files: e.target.value.split(",").map((f) => f.trim()).filter(Boolean) })
                      }
                    />
                    <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setEditingStep(null)}>
                      Done
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="plan-step-desc">
                      <span style={{ color: "var(--text-faint)", fontSize: 11, marginRight: 6 }}>{idx + 1}.</span>
                      {s.description}
                    </div>
                    {s.files.length > 0 && (
                      <div className="plan-step-files">
                        {s.files.map((f) => (
                          <span key={f} className="plan-step-file-tag">{f}</span>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
              {canEdit && editingStep !== s.id && (
                <div className="plan-step-actions">
                  <button className="icon-btn" title="Move up" onClick={() => moveStep(s.id, -1)} disabled={idx === 0}>↑</button>
                  <button className="icon-btn" title="Move down" onClick={() => moveStep(s.id, 1)} disabled={idx === steps.length - 1}>↓</button>
                  <button className="icon-btn" title="Edit" onClick={() => setEditingStep(s.id)}>✎</button>
                  <button className="icon-btn danger" title="Remove" onClick={() => removeStep(s.id)}>✕</button>
                </div>
              )}
            </div>
          ))}
          {steps.length === 0 && (
            <div className="empty-state" style={{ padding: "14px 0" }}>No steps. Add at least one before approving.</div>
          )}
        </div>
      </div>

      {/* Acceptance criteria */}
      <div style={{ marginBottom: 18 }}>
        <div className="sec-header">
          <span className="sec-header-title">Acceptance criteria</span>
        </div>
        <ul className="plan-criteria-list">
          {criteria.map((c, i) => (
            <li key={i}>
              {editingCriterion === i && canEdit ? (
                <div className="inline-edit" style={{ flex: 1 }}>
                  <textarea
                    value={c}
                    onChange={(e) => updateCriterion(i, e.target.value)}
                    style={{ minHeight: 44 }}
                    autoFocus
                  />
                  <button className="icon-btn" onClick={() => setEditingCriterion(null)}>Done</button>
                </div>
              ) : (
                <span style={{ flex: 1 }}>{c}</span>
              )}
              {canEdit && editingCriterion !== i && (
                <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                  <button className="icon-btn" onClick={() => setEditingCriterion(i)}>✎</button>
                  <button className="icon-btn danger" onClick={() => removeCriterion(i)}>✕</button>
                </div>
              )}
            </li>
          ))}
        </ul>
        {canEdit && (
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <input
              type="text"
              placeholder="Add acceptance criterion…"
              value={newCriterion}
              onChange={(e) => setNewCriterion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addCriterion()}
              style={{ flex: 1 }}
            />
            <button className="btn" onClick={addCriterion} disabled={!newCriterion.trim()}>Add</button>
          </div>
        )}
      </div>

      {/* Risks + files affected */}
      {plan.risks.length > 0 && (
        <details style={{ marginBottom: 14 }}>
          <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "var(--warn)" }}>
            {plan.risks.length} stated risk{plan.risks.length !== 1 ? "s" : ""}
          </summary>
          <ul style={{ margin: "8px 0 0 0", paddingLeft: 18 }}>
            {plan.risks.map((r, i) => <li key={i} style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 3 }}>{r}</li>)}
          </ul>
        </details>
      )}
      {plan.files_likely_to_change.length > 0 && (
        <details style={{ marginBottom: 14 }}>
          <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "var(--text-muted)" }}>
            {plan.files_likely_to_change.length} file{plan.files_likely_to_change.length !== 1 ? "s" : ""} targeted
          </summary>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
            {plan.files_likely_to_change.map((f) => (
              <span key={f} className="plan-step-file-tag">{f}</span>
            ))}
          </div>
        </details>
      )}

      {saveErr && <div className="callout callout-danger" style={{ marginBottom: 8 }}>{saveErr}</div>}

      {/* Save edits */}
      {canEdit && dirty && (
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <button className="btn btn-primary" onClick={saveEdits} disabled={saving}>
            {saving ? "Saving…" : "Save edits"}
          </button>
          <span style={{ fontSize: 12, color: "var(--text-faint)", alignSelf: "center" }}>
            Unsaved changes — save before approving.
          </span>
        </div>
      )}

      {/* Approval */}
      {plan.approved === true && (
        <div className="callout" style={{ background: "var(--success-soft)", color: "var(--success)", border: "none" }}>
          <StatusBadge state="PASSED" /> Plan approved{plan.approval_comment ? ` — "${plan.approval_comment}"` : ""}.
        </div>
      )}
      {plan.approved === false && (
        <div className="callout callout-danger">
          Plan rejected{plan.approval_comment ? ` — "${plan.approval_comment}"` : ""}. Generate a new plan or edit and re-submit.
        </div>
      )}
      {canEdit && plan.approved == null && (
        <div>
          <label>Review comment (optional)</label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Add review notes…"
            style={{ marginBottom: 10 }}
          />
          <div className="btn-row">
            <button
              className="btn btn-success"
              disabled={busy || dirty || steps.length === 0}
              onClick={() => onApprove(comment)}
              title={dirty ? "Save edits first" : ""}
            >
              Approve plan
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => onReject(comment)}>
              Reject / Revise
            </button>
          </div>
          {dirty && (
            <div style={{ fontSize: 11.5, color: "var(--warn)", marginTop: 6 }}>
              Save your edits before approving.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
