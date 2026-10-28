import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import type { AlertCounts, AlertItem, PreviewInfo } from "../types";

type Deployment = PreviewInfo & { key: string };

const SEVERITY_CLASS: Record<string, string> = { CRITICAL: "danger", WARNING: "warn", INFO: "success" };

function ago(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const s = Math.max(0, Math.round(Date.now() / 1000 - seconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

/** Live deployments (what users see right now) and the alerts they raised. */
export function MonitoringPage() {
  const [deployments, setDeployments] = useState<Deployment[] | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [open, setOpen] = useState<AlertCounts | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [d, a] = await Promise.all([api.listDeployments(), api.listAlerts(!showAll)]);
      setDeployments(d.deployments);
      setAlerts(a.alerts);
      setOpen(a.open);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [showAll]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000); // live view: refresh every 10 s
    return () => clearInterval(timer);
  }, [load]);

  async function ack(id?: string) {
    if (id) await api.ackAlert(id);
    else await api.ackAllAlerts();
    load();
  }

  return (
    <div>
      <h1 className="page-title">Monitoring &amp; Alerts</h1>
      <p className="page-subtitle">
        Running deployments are released blue-green with a hot standby and watched continuously. Failures raise alerts here —
        they don't take the site down.
      </p>
      {error && <div className="callout callout-danger">{error}</div>}

      <div className="sec-header" style={{ marginBottom: 8 }}>
        <span className="sec-header-title">Live deployments</span>
      </div>
      {deployments && deployments.length === 0 && (
        <div className="empty-state" style={{ marginBottom: 18 }}>
          Nothing is deployed right now. Run a staging preview from a workflow's GitHub panel to deploy it here.
        </div>
      )}
      {deployments?.map((d) => {
        const m = d.monitor;
        const healthy = d.running && (m?.consecutive_failures ?? 0) === 0 && !m?.down_since;
        return (
          <div key={d.key} className="card" style={{ padding: "12px 14px", marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span className={`tag ${healthy ? "success" : "danger"}`}>{healthy ? "● Healthy" : "● Degraded"}</span>
              <strong>{d.key}</strong>
              <a href={d.open_url ?? d.url} target="_blank" rel="noreferrer">{d.url}</a>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{d.strategy}</span>
            </div>
            <div className="kpi-strip" style={{ marginTop: 10 }}>
              <div className="kpi-cell">
                <div className={`kpi-value ${m?.availability != null && m.availability < 99.9 ? "warn" : "success"}`}>
                  {m?.availability != null ? `${m.availability}%` : "—"}
                </div>
                <div className="kpi-label">Availability ({m?.checks ?? 0} checks)</div>
              </div>
              <div className="kpi-cell">
                <div className="kpi-value">{m?.last_latency_ms != null ? `${m.last_latency_ms} ms` : "—"}</div>
                <div className="kpi-label">Last check {ago(m?.last_check)}</div>
              </div>
              <div className="kpi-cell">
                <div className="kpi-value accent">#{d.release} · {d.sha}</div>
                <div className="kpi-label">Live release</div>
              </div>
              <div className="kpi-cell">
                <div className={`kpi-value ${d.standby ? "success" : "warn"}`}>{d.standby ? "Ready" : "None"}</div>
                <div className="kpi-label">Hot standby</div>
              </div>
              <div className="kpi-cell">
                <div className="kpi-value">{d.traffic?.failovers ?? 0}</div>
                <div className="kpi-label">Failovers · {d.traffic?.requests ?? 0} requests</div>
              </div>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
              {d.previous
                ? <>Previous release #{d.previous.number} ({d.previous.sha}) {d.previous.warm ? "is warm for instant rollback" : "can be restarted for rollback"}.</>
                : "No previous release yet."}{" "}
              <button className="btn" style={{ padding: "2px 8px", fontSize: 12 }} onClick={() => setExpanded(expanded === d.key ? null : d.key)}>
                {expanded === d.key ? "Hide" : "Releases & incidents"}
              </button>
            </div>
            {expanded === d.key && (
              <div style={{ marginTop: 8, fontSize: 12.5 }}>
                {d.releases?.map((r) => (
                  <div key={r.number} style={{ padding: "4px 0", borderTop: "1px solid var(--border)" }}>
                    <span className={`tag ${r.status === "live" ? "success" : r.status === "blocked" ? "danger" : ""}`}>{r.status}</span>{" "}
                    #{r.number} <code>{r.sha}</code> · {ago(r.created_at)}
                    {r.reason && <span style={{ color: "var(--danger)" }}> — {r.reason}</span>}
                  </div>
                ))}
                {(m?.incidents.length ?? 0) > 0 && <div className="eyebrow" style={{ marginTop: 8 }}>Incidents</div>}
                {m?.incidents.map((i) => (
                  <div key={i.at + i.text}>{ago(i.at)} — {i.text}</div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <div className="sec-header" style={{ margin: "18px 0 8px", display: "flex", alignItems: "center", gap: 10 }}>
        <span className="sec-header-title">Alerts</span>
        {open && (
          <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            {open.CRITICAL} critical · {open.WARNING} warning · {open.INFO} info open
          </span>
        )}
        <label className="check" style={{ marginLeft: "auto", fontSize: 12.5 }}>
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show acknowledged
        </label>
        <button className="btn" onClick={() => ack()}>Acknowledge all</button>
      </div>
      {alerts && alerts.length === 0 && <div className="empty-state">No open alerts. ✅</div>}
      {alerts?.map((a) => (
        <div key={a.id} className="card" style={{ padding: "10px 14px", marginBottom: 8, opacity: a.acknowledged ? 0.6 : 1 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className={`tag ${SEVERITY_CLASS[a.severity] ?? ""}`}>{a.severity}</span>
            <strong style={{ fontSize: 13.5 }}>{a.title}</strong>
            <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
              {new Date(a.created_at).toLocaleString()} · {a.source}
              {a.deployment && <> · {a.deployment}</>}
              {a.delivered_to && <> · sent to {a.delivered_to}</>}
            </span>
            {a.workflow_id && <Link to={`/workflows/${a.workflow_id}`} style={{ fontSize: 12 }}>open workflow</Link>}
            {!a.acknowledged && (
              <button className="btn" style={{ marginLeft: "auto", padding: "2px 10px", fontSize: 12 }} onClick={() => ack(a.id)}>
                Acknowledge
              </button>
            )}
          </div>
          {a.detail && <pre className="mono-block" style={{ marginTop: 6, maxHeight: 160, whiteSpace: "pre-wrap" }}>{a.detail}</pre>}
        </div>
      ))}
    </div>
  );
}
