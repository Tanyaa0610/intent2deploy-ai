import type { AuditEventItem } from "../types";

export function Timeline({ events }: { events: AuditEventItem[] }) {
  if (events.length === 0) {
    return <div className="empty-state">No workflow events yet.</div>;
  }
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div className="timeline-item" key={i}>
          <div className="timeline-event">{e.event_type.replace(/_/g, " ")}</div>
          <div className="timeline-meta">
            {new Date(e.timestamp).toLocaleTimeString()} {e.stage && `· ${e.stage}`} {e.message && `· ${e.message}`}
          </div>
        </div>
      ))}
    </div>
  );
}
