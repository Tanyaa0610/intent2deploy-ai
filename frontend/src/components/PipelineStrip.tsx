import type { PipelineStage } from "../types";

const STAGE_CLASS: Record<string, string> = {
  PASSED: "clear",
  FAILED: "attention",
  BLOCKED: "attention",
  AWAITING_APPROVAL: "warn",
  RUNNING: "warn",
  SKIPPED: "",
  NOT_APPLICABLE: "",
  PENDING: "",
};

export function PipelineStrip({ stages }: { stages: PipelineStage[] }) {
  if (stages.length === 0) return null;
  return (
    <div className="gr-pipeline" style={{ marginBottom: 4 }}>
      {stages.map((s, i) => (
        <div key={s.name} style={{ display: "flex", alignItems: "center" }}>
          <div className={`gr-pipeline-node ${STAGE_CLASS[s.status] || ""}`} title={s.output || s.status}>
            <div className="n">{s.name}</div>
            <div className="c">{s.status.replace(/_/g, " ").toLowerCase()}</div>
          </div>
          {i < stages.length - 1 && <span className="gr-pipeline-arrow">→</span>}
        </div>
      ))}
    </div>
  );
}
