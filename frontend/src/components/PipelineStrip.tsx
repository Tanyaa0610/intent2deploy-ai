import type { PipelineStage } from "../types";

const STAGE_CLASS: Record<string, string> = {
  PASSED: "done",
  FAILED: "attention",
  BLOCKED: "attention",
  AWAITING_APPROVAL: "warn",
  RUNNING: "active",
  SKIPPED: "",
  NOT_APPLICABLE: "",
  PENDING: "",
};

export function PipelineStrip({ stages }: { stages: PipelineStage[] }) {
  if (stages.length === 0) return null;
  return (
    <div className="stepper-wrap">
      <div className="stepper">
        {stages.map((s) => (
          <div key={s.name} className={`stepper-step ${STAGE_CLASS[s.status] || ""}`} title={s.output || s.status}>
            <span className="marker" />
            <span className="label">{s.name}</span>
            <span className="meta">{s.status.replace(/_/g, " ").toLowerCase()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
