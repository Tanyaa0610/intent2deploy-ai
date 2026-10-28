import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import type {
  RepoFile,
  AddOnItem,
  AuditEventItem,
  CheckDetails,
  PreviewInfo,
  GreenfieldDesign,
  GeneratedTestItem,
  PipelineStage,
  PlanDetail,
  ProposedChangeItem,
  RepairAttemptItem,
  RetrievalEvidenceItem,
  RiskItem,
  ValidationResultItem,
  Workflow,
} from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { EvidencePanel } from "../components/EvidencePanel";
import { DiffViewer } from "../components/DiffViewer";
import { PlanEditor } from "../components/PlanEditor";
import { DiffReview } from "../components/DiffReview";
import { Expand } from "../components/DataDisplay";

// ─── Stage navigator ────────────────────────────────────────────────────────

// Map each pipeline stage name to a short label
const STAGE_LABELS: Record<string, string> = {
  "Developer Intent": "Intent",
  "Intent Understanding": "RAG / Plan",
  "Production Context": "Context",
  "Repository RAG": "Retrieval",
  "Architecture Analysis": "Arch",
  "Risk Analysis": "Risks",
  "Engineering Plan": "Plan",
  "Human Approval": "Approval",
  "Code Generation": "Codegen",
  "Test Generation": "Tests",
  "Resilience Testing": "Resilience",
  "Chaos Simulation": "Chaos",
  "Validation": "Validate",
  "AI Repair": "Repair",
  "Production Readiness": "Readiness",
  "CI/CD": "CI/CD",
  "GitHub / PR": "PR",
  "Final Report": "Report",
};

// Stage to show when the workflow enters a state.
const STAGE_FOR_STATE: Record<string, string> = {
  INDEXED: "Engineering Plan",
  AWAITING_PLAN_APPROVAL: "Engineering Plan",
  PLAN_REJECTED: "Engineering Plan",
  CHANGES_GENERATING: "Code Generation",
  AWAITING_CHANGE_APPROVAL: "Code Generation",
  CHANGES_REJECTED: "Code Generation",
  TESTS_GENERATING: "Validation",
  VALIDATING: "Validation",
  VALIDATION_FAILED: "Validation",
  REPAIRING: "Validation",
  AWAITING_COMMIT_APPROVAL: "Production Readiness",
  COMMITTED: "GitHub / PR",
  COMPLETED: "Final Report",
};

// States that sit between a human approval and the next automatic step.
// Approving runs that step directly; this resumes it if it was interrupted.
const AUTOMATIC_STEPS: Record<string, { label: string; run: (id: string) => Promise<unknown> }> = {
  CHANGES_GENERATING: { label: "generate changes", run: (id) => api.generateChanges(id) },
  TESTS_GENERATING: {
    label: "generate tests & validate",
    run: async (id) => {
      await api.generateTests(id);
      await api.runValidation(id);
    },
  },
  VALIDATING: { label: "run validation", run: (id) => api.runValidation(id) },
};

function statusClass(status: string): string {
  switch (status) {
    case "PASSED": return "passed";
    case "FAILED": return "failed";
    case "BLOCKED": return "blocked";
    case "RUNNING": return "running";
    case "AWAITING_APPROVAL": return "awaiting";
    case "SKIPPED": return "skipped";
    case "NOT_APPLICABLE": return "na";
    default: return "";
  }
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").toLowerCase();
}

function nextActionForState(state: string): { label: string; tone: string } | null {
  const MAP: Record<string, { label: string; tone: string }> = {
    AWAITING_PLAN_APPROVAL:   { label: "Review & approve plan", tone: "approval" },
    AWAITING_CHANGE_APPROVAL: { label: "Review & approve changes", tone: "approval" },
    AWAITING_COMMIT_APPROVAL: { label: "Approve commit", tone: "approval" },
    REPAIRING:                { label: "Review repair proposal", tone: "approval" },
    VALIDATION_FAILED:        { label: "Diagnose & repair", tone: "failure" },
    PLAN_REJECTED:            { label: "Regenerate plan", tone: "failure" },
    CHANGES_REJECTED:         { label: "Regenerate changes", tone: "failure" },
    CREATED:                  { label: "Start indexing", tone: "info" },
    INDEXED:                  { label: "Generate plan", tone: "info" },
    COMMITTED:                { label: "Finalize workflow", tone: "info" },
  };
  return MAP[state] ?? null;
}

// ─── Stage content panels ────────────────────────────────────────────────────

function IntentPanel({ workflow, stage }: { workflow: Workflow; stage: PipelineStage }) {
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 6 }}>Developer intent</div>
      <p style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 12 }}>{workflow.intent}</p>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
        <div><span className="eyebrow">Repository</span><br/><code style={{ fontSize: 12 }}>{workflow.branch_name || workflow.base_branch}</code></div>
        <div><span className="eyebrow">Environment</span><br/><code style={{ fontSize: 12 }}>{(workflow as unknown as Record<string,string>).environment ?? "sandbox"}</code></div>
        <div><span className="eyebrow">Base branch</span><br/><code style={{ fontSize: 12 }}>{workflow.base_branch}</code></div>
      </div>
      {stage.timestamp && (
        <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 10 }}>
          Created {new Date(stage.timestamp).toLocaleString()}
        </div>
      )}
    </div>
  );
}

type AskLocation = { file: string; start_line: number; end_line: number; symbol: string; why: string };

/** Ask this workflow's repository a question: answers with where the code is, and opens the file. */
function AskRepository({ repositoryId, workflowId }: { repositoryId: string; workflowId: string }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<{ answer: string; locations: AskLocation[] } | null>(null);
  const [opened, setOpened] = useState<{ loc: AskLocation; file: RepoFile } | null>(null);
  const [opening, setOpening] = useState("");
  const viewer = useRef<HTMLDivElement>(null);

  async function ask() {
    if (!q.trim()) return;
    setBusy(true);
    setErr("");
    setResult(null);
    setOpened(null);
    try {
      const r = await api.askRepository(repositoryId, q);
      setResult({ answer: r.answer, locations: r.locations ?? [] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function open(loc: AskLocation) {
    setOpening(loc.file);
    setErr("");
    try {
      setOpened({ loc, file: await api.getWorkflowFile(workflowId, loc.file) });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setOpening("");
    }
  }

  // Jump to the matching lines when a file opens.
  useEffect(() => {
    if (!opened || !viewer.current) return;
    const line = viewer.current.querySelector<HTMLElement>(`[data-line="${opened.loc.start_line}"]`);
    if (line) viewer.current.scrollTop = line.offsetTop - 40;
  }, [opened]);

  const whole = (l: AskLocation, f?: RepoFile) => l.start_line <= 1 && (!f || l.end_line >= f.lines);

  return (
    <div className="ask-card">
      <div className="eyebrow" style={{ marginBottom: 6 }}>🔎 Ask the repository</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Where is the Docker configuration?  ·  Where is the login logic?"
          onKeyDown={(e) => e.key === "Enter" && ask()}
          style={{ flex: 1 }}
          aria-label="Ask a question about this repository"
        />
        <button className="btn btn-primary" onClick={ask} disabled={busy || !q.trim()}>{busy ? "Searching…" : "Ask"}</button>
      </div>
      {err && <div className="callout callout-danger" style={{ marginTop: 8 }}>{err}</div>}

      {result && (
        <div style={{ marginTop: 10 }}>
          {result.locations.length === 0 ? (
            <div className="empty-state">Nothing in this repository matches that question.</div>
          ) : (
            <>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>📍 Found in</div>
              {result.locations.map((l, i) => (
                <div key={`${l.file}:${l.start_line}`} className={`ask-loc${opened?.loc === l ? " active" : ""}`} style={{ animationDelay: `${i * 50}ms` }}>
                  <div style={{ minWidth: 0 }}>
                    <code className="ask-path">{l.file}</code>
                    <span className="ask-lines">
                      {whole(l) ? "whole file" : `lines ${l.start_line}–${l.end_line}`}
                      {l.symbol && <> · <strong>{l.symbol}</strong></>}
                    </span>
                    <div className="ask-why">{l.why}</div>
                  </div>
                  <button className="btn" disabled={opening === l.file} onClick={() => (opened?.loc === l ? setOpened(null) : open(l))}>
                    {opening === l.file ? "Opening…" : opened?.loc === l ? "Close" : "📂 Open file"}
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {opened && (
        <div className="file-viewer">
          <div className="file-viewer-head">
            <code>{opened.file.path}</code>
            <span>
              {opened.file.lines} lines · {opened.file.language}
              {!whole(opened.loc, opened.file) && <> · showing lines {opened.loc.start_line}–{opened.loc.end_line}</>}
            </span>
            <button className="btn" style={{ padding: "1px 8px", fontSize: 12 }} onClick={() => setOpened(null)}>✕</button>
          </div>
          <div className="file-viewer-body" ref={viewer}>
            {opened.file.content.split(/\r?\n/).map((text, i) => {
              const n = i + 1;
              const hit = !whole(opened.loc, opened.file) && n >= opened.loc.start_line && n <= opened.loc.end_line;
              return (
                <div key={n} data-line={n} className={`fv-line${hit ? " hit" : ""}`}>
                  <span className="fv-n">{n}</span>
                  <span className="fv-t">{text || " "}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function RetrievalPanel({
  workflowId,
  stage,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  stage: PipelineStage;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [evidence, setEvidence] = useState<RetrievalEvidenceItem[] | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    api.getEvidence(workflowId)
      .then((r) => setEvidence(r.evidence))
      .catch((e) => setLoadErr(String(e)));
  }, [workflowId]);

  return (
    <div>
      {stage.output && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          {/^[\w.-]+=[^\s]+(\s+[\w.-]+=[^\s]+)*$/.test(stage.output.trim())
            ? stage.output.trim().split(/\s+/).map((kv) => (
                <span key={kv} className="tag">{kv.replace("=", ": ")}</span>
              ))
            : <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{stage.output}</span>}
          {stage.duration_ms != null && <span style={{ fontSize: 11.5, color: "var(--text-faint)" }}>{stage.duration_ms}ms</span>}
        </div>
      )}

      {/* Indexing action if not yet indexed */}
      {workflow.state === "CREATED" && (
        <div style={{ marginBottom: 14 }}>
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.runIndexing(workflowId))}>
            Index Repository
          </button>
        </div>
      )}

      {loadErr && <div className="callout callout-danger">{loadErr}</div>}

      {evidence === null ? (
        <div className="empty-state">Loading retrieval evidence…</div>
      ) : evidence.length === 0 ? (
        <div className="empty-state">No retrieval evidence yet. Index the repository and generate a plan to populate this.</div>
      ) : (
        <>
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 10px" }}>
            The code Intent2Deploy found most relevant to this request, best match first. Click a piece to read it.
          </p>
          <EvidencePanel
            evidence={evidence}
            belowToolbar={<AskRepository repositoryId={workflow.repository_id} workflowId={workflowId} />}
          />
        </>
      )}

      {/* No retrieved code yet: the question box still works on its own. */}
      {evidence !== null && evidence.length === 0 && (
        <AskRepository repositoryId={workflow.repository_id} workflowId={workflowId} />
      )}
    </div>
  );
}

function PlanPanel({
  workflowId,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    api.getPlan(workflowId).then(setPlan).catch((e) => setLoadErr(String(e)));
  }, [workflowId, workflow.state]);

  const canGenerate = workflow.state === "INDEXED";
  const canRegenerate = workflow.state === "PLAN_REJECTED";

  return (
    <div>
      {(canGenerate || canRegenerate) && (
        <div style={{ marginBottom: 14 }}>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => act(() => api.runPlanning(workflowId))}
          >
            {canRegenerate ? "Regenerate Plan" : "Generate Plan"}
          </button>
        </div>
      )}
      {loadErr && <div className="empty-state">{loadErr}</div>}
      {plan ? (
        <PlanEditor
          workflowId={workflowId}
          plan={plan}
          state={workflow.state}
          busy={busy}
          onPlanChange={setPlan}
          onApprove={(comment) =>
            act(async () => {
              await api.approvePlan(workflowId, true, comment);
              await api.generateChanges(workflowId);
            })
          }
          onReject={(comment) => act(() => api.approvePlan(workflowId, false, comment))}
        />
      ) : (
        !loadErr && (
          <div className="empty-state">
            {workflow.state === "PLANNING" ? "Generating plan…" : "No plan generated yet."}
          </div>
        )
      )}
    </div>
  );
}

const SEVERITY_ORDER: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

function RiskPanel({
  workflowId,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [risks, setRisks] = useState<RiskItem[] | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    api.getRisks(workflowId).then((r) => setRisks(r.risks)).catch((e) => setLoadErr(String(e)));
  }, [workflowId, workflow.state, workflow.updated_at]);

  const hasPlan = !["CREATED", "INDEXING", "INDEXED", "PLANNING"].includes(workflow.state);
  const sorted = risks ? [...risks].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)) : [];

  return (
    <div>
      {loadErr && <div className="callout callout-danger">{loadErr}</div>}
      {!hasPlan ? (
        <div className="empty-state">Risks are derived from the plan. Generate a plan first.</div>
      ) : risks === null ? (
        <div className="empty-state">Loading…</div>
      ) : (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
              {risks.length === 0
                ? "No risks recorded."
                : `${risks.length} risk${risks.length !== 1 ? "s" : ""} · ${risks.filter((r) => r.status === "OPEN").length} open`}
            </span>
            <button className="btn" disabled={busy} onClick={() => act(() => api.analyzeRisks(workflowId))}>
              {risks.length === 0 ? "Run analysis" : "Re-run"}
            </button>
          </div>
          {sorted.length > 0 && (
            <table>
              <thead>
                <tr><th>Severity</th><th>Risk</th><th>Component</th><th>Mitigation</th><th>Status</th></tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.risk_id}>
                    <td><StatusBadge state={r.severity} /></td>
                    <td style={{ fontWeight: 600 }}>{r.title}</td>
                    <td><code style={{ fontSize: 11.5 }}>{r.component || "—"}</code></td>
                    <td style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{r.mitigation || "—"}</td>
                    <td style={{ fontSize: 12 }}>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

function CodegenPanel({
  workflowId,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [changes, setChanges] = useState<ProposedChangeItem[] | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    if (["CHANGES_READY", "AWAITING_CHANGE_APPROVAL", "CHANGES_REJECTED", "TESTS_GENERATING", "VALIDATING", "VALIDATION_FAILED", "VALIDATION_PASSED", "REPAIRING", "AWAITING_COMMIT_APPROVAL", "COMMITTED", "CI_RUNNING", "COMPLETED"].includes(workflow.state)) {
      api.getChanges(workflowId).then((r) => setChanges(r.changes)).catch((e) => setLoadErr(String(e)));
    }
  }, [workflowId, workflow.state]);

  const canGenerate = workflow.state === "CHANGES_GENERATING" || (workflow.state === "CHANGES_REJECTED");

  return (
    <div>
      {workflow.state === "AWAITING_PLAN_APPROVAL" && (
        <div className="callout" style={{ background: "var(--accent-soft)", color: "var(--accent-strong)", border: "none", marginBottom: 12 }}>
          Approve the plan first to generate code changes.
        </div>
      )}
      {canGenerate && (
        <div style={{ marginBottom: 14 }}>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => act(() => api.generateChanges(workflowId))}
          >
            {workflow.state === "CHANGES_REJECTED" ? "Regenerate Changes" : "Generate Changes"}
          </button>
        </div>
      )}
      {loadErr && <div className="callout callout-danger">{loadErr}</div>}
      {changes !== null ? (
        <DiffReview
          changes={changes}
          state={workflow.state}
          busy={busy}
          onApprove={(comment) =>
            act(async () => {
              await api.approveChanges(workflowId, true, comment);
              await api.generateTests(workflowId);
              await api.runValidation(workflowId);
            })
          }
          onReject={(comment) => act(() => api.approveChanges(workflowId, false, comment))}
        />
      ) : (
        !loadErr && workflow.state !== "AWAITING_PLAN_APPROVAL" && (
          <div className="empty-state">
            {["CHANGES_GENERATING"].includes(workflow.state) ? "Generating changes…" : "No code changes yet."}
          </div>
        )
      )}
    </div>
  );
}

// Production verification stages run the built app and test it live.
const VALIDATION_STAGE_LABELS: Record<string, string> = {
  docker_build: "docker build",
  prod_boot: "production · boot",
  prod_smoke: "production · smoke test",
  prod_api: "production · API contract",
  prod_robustness: "production · hostile input",
  prod_load: "production · load test",
  prod_recovery: "production · restart & recovery",
};

function ValidationPanel({
  workflowId,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [results, setResults] = useState<ValidationResultItem[] | null>(null);
  const [tests, setTests] = useState<GeneratedTestItem[] | null>(null);
  const [repairs, setRepairs] = useState<RepairAttemptItem[] | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    const validStates = ["VALIDATING", "VALIDATION_PASSED", "VALIDATION_FAILED", "REPAIRING", "AWAITING_COMMIT_APPROVAL", "COMMITTED", "CI_RUNNING", "COMPLETED"];
    if (validStates.includes(workflow.state)) {
      Promise.all([
        api.getValidation(workflowId),
        api.getTests(workflowId),
        api.getRepairs(workflowId),
      ])
        .then(([v, t, r]) => { setResults(v.results); setTests(t.tests); setRepairs(r.repairs); })
        .catch((e) => setLoadErr(String(e)));
    } else {
      // Populate tests if they've been generated
      if (["TESTS_GENERATING"].includes(workflow.state)) return;
      api.getTests(workflowId).then((t) => setTests(t.tests)).catch(() => {});
      api.getRepairs(workflowId).then((r) => setRepairs(r.repairs)).catch(() => {});
    }
  }, [workflowId, workflow.state]);

  const latestAttempt = results ? Math.max(0, ...results.map((r) => r.attempt)) : 0;
  const latestResults = results ? results.filter((r) => r.attempt === latestAttempt) : [];
  const passed = latestResults.filter((r) => r.status === "passed").length;
  const failed = latestResults.filter((r) => r.status === "failed" || r.status === "error").length;

  return (
    <div>
      {/* Generate tests action */}
      {workflow.state === "AWAITING_CHANGE_APPROVAL" && (
        <div className="callout" style={{ background: "var(--accent-soft)", color: "var(--accent-strong)", border: "none", marginBottom: 12 }}>
          Approve changes first to trigger test generation and validation.
        </div>
      )}

      {/* Summary banner */}
      {results && results.length > 0 && (
        <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
          <StatusBadge state={workflow.state.includes("PASSED") ? "VALIDATION_PASSED" : workflow.state === "VALIDATION_FAILED" ? "VALIDATION_FAILED" : workflow.state} />
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {passed} passed · {failed} failed
            {latestAttempt > 0 && <span> · attempt {latestAttempt}</span>}
          </span>
          {failed > 0 && (
            <span style={{ fontSize: 12.5, color: "var(--danger)", fontWeight: 600 }}>
              {failed} stage{failed !== 1 ? "s" : ""} need attention
            </span>
          )}
        </div>
      )}

      {loadErr && <div className="callout callout-danger">{loadErr}</div>}

      {/* Validation results */}
      {latestResults.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="sec-header" style={{ marginBottom: 8 }}>
            <span className="sec-header-title">Validation results (attempt {latestAttempt})</span>
          </div>
          {latestResults.map((r, i) => (
            <div key={i} className="validation-row">
              <span className="validation-stage">
                <StatusBadge state={r.status} />
              </span>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text)" }}>{VALIDATION_STAGE_LABELS[r.stage] ?? r.stage}</span>
              <span className="validation-cmd">{r.command || "—"}</span>
              <span style={{ fontSize: 11.5, color: "var(--text-faint)", whiteSpace: "nowrap" }}>
                {r.duration_ms}ms
              </span>
            </div>
          ))}
          {/* Expandable output for failed stages, and the live production
              reports (latency, findings) even when they pass. */}
          {latestResults.filter((r) => r.status !== "passed" || r.stage.startsWith("prod_")).map((r, i) => (
            <div key={`out-${i}`} style={{ marginTop: 8 }}>
              <Expand title={`${VALIDATION_STAGE_LABELS[r.stage] ?? r.stage} ${r.stage.startsWith("prod_") ? "report" : "output"}`}>
                {r.stdout && (
                  <pre className="mono-block" style={{ marginBottom: 6 }}>{r.stdout.slice(0, 3000)}</pre>
                )}
                {r.stderr && (
                  <pre className="mono-block" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
                    {r.stderr.slice(0, 3000)}
                  </pre>
                )}
              </Expand>
            </div>
          ))}
        </div>
      )}

      {/* Tests */}
      {tests && tests.length > 0 && (
        <details style={{ marginBottom: 14 }}>
          <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "var(--text-muted)" }}>
            {tests.length} generated test file{tests.length !== 1 ? "s" : ""}
          </summary>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
            {tests.map((t) => (
              <div key={t.id} style={{ border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "var(--bg-subtle)", fontSize: 12 }}>
                  <code>{t.file}</code>
                  <span className="tag">{t.category}</span>
                </div>
                <div style={{ padding: "6px 12px", fontSize: 12, color: "var(--text-muted)" }}>{t.rationale}</div>
                <Expand title="View test content">
                  <pre className="mono-block">{t.content}</pre>
                </Expand>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Repair section */}
      {(workflow.state === "VALIDATION_FAILED" || (repairs && repairs.length > 0)) && (
        <div>
          <div className="sec-header" style={{ marginBottom: 8 }}>
            <span className="sec-header-title">Repair attempts ({workflow.repair_attempts}/2)</span>
          </div>

          {repairs && repairs.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              {repairs.map((r) => (
                <div key={r.id} className="repair-attempt-row">
                  <div className="repair-attempt-header">
                    <span className="repair-number">Attempt {r.attempt_number}</span>
                    <StatusBadge state={r.result === "passed" ? "VALIDATION_PASSED" : r.result === "failed" ? "VALIDATION_FAILED" : r.result === "superseded" || (r.approved == null && !["REPAIRING", "VALIDATION_FAILED"].includes(workflow.state)) ? "SUPERSEDED" : "REPAIRING"} />
                  </div>
                  <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 8px 0" }}>{r.diagnosis}</p>
                  {r.repair_patch && (
                    <Expand title="View repair patch">
                      <DiffViewer patch={r.repair_patch} />
                    </Expand>
                  )}
                  {r.approved == null && workflow.state === "VALIDATION_FAILED" && (
                    <div className="btn-row" style={{ marginTop: 8 }}>
                      <button
                        className="btn btn-success"
                        disabled={busy || !r.repair_patch}
                        onClick={() => act(() => api.approveRepair(workflowId, r.id, true))}
                      >
                        Apply repair &amp; re-validate
                      </button>
                      <button className="btn" disabled={busy} onClick={() =>
                          act(async () => {
                            await api.approveRepair(workflowId, r.id, false);
                            setRepairs((await api.getRepairs(workflowId)).repairs);
                          })
                        }>
                        Discard
                      </button>
                      {!r.repair_patch && (
                        <span style={{ fontSize: 12, color: "var(--text-faint)" }}>No patch was proposed — discard it, or re-run validation.</span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {workflow.state === "VALIDATION_FAILED" && (
            <div className="btn-row">
              {workflow.repair_attempts < 2 && !repairs?.some((r) => r.approved == null) && (
                <button className="btn btn-primary" disabled={busy} onClick={() =>
                    act(async () => {
                      await api.proposeRepair(workflowId);
                      // State stays VALIDATION_FAILED, so the effect won't refetch on its own.
                      setRepairs((await api.getRepairs(workflowId)).repairs);
                    })
                  }>
                  Diagnose &amp; Propose Repair
                </button>
              )}
              <button className="btn" disabled={busy} onClick={() => act(() => api.runValidation(workflowId))}>
                Re-run validation
              </button>
            </div>
          )}

          {workflow.repair_attempts >= 2 && workflow.state === "VALIDATION_FAILED" && (
            <div className="callout callout-danger">
              Repair limit reached (2/2). Manual review required before continuing.
            </div>
          )}
        </div>
      )}

      {results === null && tests === null && !loadErr && (
        <div className="empty-state">
          {["TESTS_GENERATING", "VALIDATING"].includes(workflow.state)
            ? "Running…"
            : "No validation data yet. Approve changes to trigger test generation."}
        </div>
      )}
    </div>
  );
}

type PRState = Awaited<ReturnType<typeof api.getPRStatus>>;

/** Found something wrong while checking staging? Describe it and a revision
 * workflow is planned to fix it (it goes through approval and validation and
 * reaches staging through its own PR). */
function ReportProblem({ workflowId, staging }: { workflowId: string; staging: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState("");
  const [shots, setShots] = useState<{ name: string; url: string }[]>([]);
  const [dragging, setDragging] = useState(false);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  const [answer, setAnswer] = useState<RevisionAnswer | null>(null);
  const [upgrades, setUpgrades] = useState<AddOnItem[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) api.listAddons(workflowId).then((r) => setUpgrades(r.addons)).catch(() => setUpgrades([]));
  }, [open, workflowId]);

  async function addUpgrade(addonId: string) {
    setSending(true);
    setErr("");
    try {
      const result = await api.reviseWorkflow(workflowId, "", [], false, [addonId]);
      if (!result.already_satisfied) navigate(`/workflows/${result.workflow.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const upgradeList = upgrades.length > 0 && (
    <div style={{ margin: "8px 0", fontSize: 12.5 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>⚡ Upgrades you can add to {staging} (work without the live AI):</div>
      {upgrades.filter((u) => u.status !== "not_supported").map((u) => (
        <div key={u.id} style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 4 }}>
          {u.status === "applied" ? (
            <span className="tag success" style={{ whiteSpace: "nowrap" }}>✓ added</span>
          ) : (
            <button className="btn" style={{ padding: "2px 10px", fontSize: 12, whiteSpace: "nowrap" }} disabled={sending}
              onClick={() => addUpgrade(u.id)}>
              + Add
            </button>
          )}
          <span><strong>{u.title}</strong> — <span style={{ color: "var(--text-muted)" }}>{u.description}</span></span>
        </div>
      ))}
      {upgrades.every((u) => u.status === "not_supported") && (
        <div style={{ color: "var(--text-muted)" }}>No built-in upgrades fit this project yet.</div>
      )}
    </div>
  );

  // Screenshots: pasted (Ctrl+V), dropped, or picked. Checked again on the server.
  function addFiles(files: FileList | File[]) {
    setErr("");
    for (const file of Array.from(files)) {
      if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) {
        setErr(`${file.name || "That file"} isn't a PNG, JPEG, GIF or WebP image.`);
        continue;
      }
      if (file.size > 5 * 1024 * 1024) {
        setErr(`${file.name || "That screenshot"} is larger than 5 MB.`);
        continue;
      }
      const reader = new FileReader();
      reader.onload = () =>
        setShots((prev) =>
          prev.length >= 5 ? prev : [...prev, { name: file.name || `screenshot-${prev.length + 1}.png`, url: String(reader.result) }]
        );
      reader.readAsDataURL(file);
    }
  }

  function onPaste(e: React.ClipboardEvent) {
    const images = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
    if (images.length) {
      e.preventDefault();
      addFiles(images);
    }
  }

  async function submit(force = false) {
    setSending(true);
    setErr("");
    setAnswer(null);
    try {
      const result = await api.reviseWorkflow(workflowId, problem, shots.map((s) => s.url), force);
      if (result.already_satisfied) {
        setAnswer(result);
        return;
      }
      navigate(`/workflows/${result.workflow.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  if (!open) {
    return (
      <div style={{ margin: "2px 0 12px" }}>
        <button className="btn" onClick={() => setOpen(true)}>🐞 Found a problem on {staging}? Report it</button>
      </div>
    );
  }
  return (
    <div
      className="card"
      style={{
        padding: "10px 12px", margin: "2px 0 12px", background: "var(--bg-subtle)",
        outline: dragging ? "2px dashed var(--accent)" : "none",
      }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
    >
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>What's wrong on {staging}?</div>
      <textarea
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
        onPaste={onPaste}
        placeholder="e.g. There is no option to reset the password — the page only has Sign in and Create account. (Paste a screenshot with Ctrl+V)"
        rows={3}
        maxLength={2000}
        style={{ marginBottom: 6 }}
        autoFocus
      />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 6 }}>
        {shots.map((s, i) => (
          <div key={i} style={{ position: "relative" }}>
            <img src={s.url} alt={`Screenshot ${i + 1}`} style={{ height: 64, borderRadius: 6, border: "1px solid var(--border)" }} />
            <button
              type="button"
              aria-label={`Remove screenshot ${i + 1}`}
              onClick={() => setShots((prev) => prev.filter((_, j) => j !== i))}
              style={{
                position: "absolute", top: -6, right: -6, width: 20, height: 20, borderRadius: 10, border: "none",
                background: "var(--danger)", color: "#fff", cursor: "pointer", fontSize: 12, lineHeight: "20px", padding: 0,
              }}
            >
              ✕
            </button>
          </div>
        ))}
        {shots.length < 5 && (
          <button type="button" className="btn" style={{ fontSize: 12 }} onClick={() => fileInput.current?.click()}>
            📎 Add screenshot
          </button>
        )}
        <span style={{ fontSize: 11.5, color: "var(--text-faint)" }}>or paste (Ctrl+V) / drag it here · up to 5 images, 5 MB each</span>
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          multiple
          hidden
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />
      </div>
      <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginBottom: 6 }}>
        A fix is planned from your description and waits for your approval. It's built on the latest {staging}, validated,
        and goes into {staging} through its own pull request — nothing changes on {staging} until you approve and merge it.
      </div>
      {err && <div className="callout callout-danger" style={{ marginBottom: 6 }}>{err}</div>}
      {answer && (
        <div className="callout" style={{ marginBottom: 8, background: "var(--success-soft, #e7f6ec)", border: "none", color: "var(--text)" }}>
          {(() => {
            const allThere = answer.findings.length > 0 && answer.findings.every((f) => f.present);
            const nothingToChange = answer.message.startsWith("Nothing to change");
            return (
              <>
                <strong>
                  {allThere ? `✅ This already exists on ${staging} — nothing to change.` : `Nothing would change on ${staging}.`}
                </strong>{" "}
                {answer.findings.length > 0 ? "I checked the code there:" : answer.message}
                {answer.findings.length > 0 && (
                  <ul style={{ margin: "4px 0 6px", paddingLeft: 18 }}>
                    {answer.findings.map((f) => (
                      <li key={f.capability}>
                        {f.present ? "✅" : "❌"} <strong>{f.capability}</strong>
                        {f.evidence.length > 0 && <span style={{ color: "var(--text-muted)" }}> — {f.evidence.join("; ")}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {!allThere && answer.findings.length > 0 && <div style={{ fontSize: 12.5, marginBottom: 4 }}>{answer.message}</div>}
                <div style={{ fontSize: 12.5 }}>
                  <strong>Next:</strong> open the app (link above) and check it. If it works, release {staging} to main in
                  step 2 below. If something behaves wrongly, describe what happens (e.g. "clicking Reset password shows an
                  error") and report again.
                </div>
                {!nothingToChange && (
                  <button className="btn" style={{ marginTop: 6 }} disabled={sending} onClick={() => submit(true)}>
                    Plan a fix anyway
                  </button>
                )}
              </>
            );
          })()}
          {answer.upgrades.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12.5 }}>
              Looking for more? These upgrades can be added right away: {answer.upgrades.map((u) => u.title).join(", ")} (see below).
            </div>
          )}
        </div>
      )}
      {upgradeList}
      <div className="btn-row">
        <button className="btn btn-primary" disabled={sending || problem.trim().length < 5} onClick={() => submit()}>
          {sending ? "Checking staging & planning…" : "Report & plan a fix"}
        </button>
        <button className="btn" disabled={sending} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

type RevisionAnswer = Extract<Awaited<ReturnType<typeof api.reviseWorkflow>>, { already_satisfied: true }>;

/** A fix workflow (revision) that produced no changes: explain why, and what to
 * do without the live AI. If staging already does what was reported, say so. */
function NoChangesHelp({
  workflow,
  busy,
  act,
}: {
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const navigate = useNavigate();
  const [check, setCheck] = useState<Awaited<ReturnType<typeof api.revisionCheck>> | null>(null);
  useEffect(() => {
    api.revisionCheck(workflow.id).then(setCheck).catch(() => setCheck(null));
  }, [workflow.id]);

  async function removeThis() {
    if (!window.confirm("Delete this fix workflow? Nothing on staging or GitHub changes.")) return;
    await api.deleteWorkflow(workflow.id);
    navigate(workflow.revision_of ? `/workflows/${workflow.revision_of}` : "/workflows");
  }

  const box = { marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--danger-soft-border)", color: "var(--text)" };
  if (check?.already_satisfied) {
    return (
      <div style={box}>
        <strong>✅ Nothing to fix — this is already on staging.</strong>
        <ul style={{ margin: "4px 0 8px", paddingLeft: 18 }}>
          {check.findings.map((f) => (
            <li key={f.capability}>
              <strong>{f.capability}</strong>
              {f.evidence.length > 0 && <span style={{ color: "var(--text-muted)" }}> — {f.evidence.join("; ")}</span>}
            </li>
          ))}
        </ul>
        <div style={{ marginBottom: 8 }}>
          Open the app from the original workflow's <em>staging → main</em> panel and try it. If it works, release staging to
          main there. This fix workflow isn't needed.
        </div>
        <div className="btn-row" style={{ marginTop: 0 }}>
          {workflow.revision_of && (
            <Link to={`/workflows/${workflow.revision_of}`} className="btn btn-primary">Go to the original workflow</Link>
          )}
          <button className="btn" disabled={busy} onClick={removeThis}>Delete this fix workflow</button>
        </div>
      </div>
    );
  }
  const missing = check?.findings.filter((f) => !f.present).map((f) => f.capability) ?? [];
  return (
    <div style={box}>
      <strong>What you can do without the live AI:</strong>
      <ol style={{ margin: "4px 0 8px", paddingLeft: 18 }}>
        <li>
          <strong>Make the change yourself</strong>
          {missing.length > 0 && <> ({missing.join(", ")})</>}: open the repository in VS Code, create a branch from{" "}
          <code>staging</code>, change the code, push it and open a pull request into <code>staging</code>. GitHub CI still
          runs the tests, Docker build and production checks on it, and the staging preview, monitoring and alerts work as
          usual.
        </li>
        <li>
          <strong>Describe it differently:</strong>{" "}
          {workflow.revision_of ? <Link to={`/workflows/${workflow.revision_of}`}>go back to the original workflow</Link> : "go back"}{" "}
          and report what you see happening (e.g. "clicking Reset password shows an error"). The built-in templates cover
          sign-in with password reset, food delivery, and dashboard apps with search and add/edit/delete.
        </li>
        <li>
          <strong>Later, with an API key:</strong> set <code>LLM_MODE=live</code> in <code>.env</code>, restart the backend,
          then{" "}
          <button className="btn" style={{ padding: "1px 8px", fontSize: 12 }} disabled={busy} onClick={() => act(() => api.resumeWorkflow(workflow.id))}>
            Resume
          </button>{" "}
          — the AI will then edit the code on staging.
        </li>
      </ol>
      <button className="btn" disabled={busy} onClick={removeThis}>Delete this fix workflow</button>
    </div>
  );
}

/** Links between a workflow and its revisions (fixes for reported problems). */
function RevisionLinks({ workflow }: { workflow: Workflow }) {
  const [revisions, setRevisions] = useState<Workflow[]>([]);
  useEffect(() => {
    api.listRevisions(workflow.id).then(setRevisions).catch(() => setRevisions([]));
  }, [workflow.id, workflow.state]);
  if (!workflow.revision_of && revisions.length === 0) return null;
  let shots: string[] = [];
  try {
    shots = JSON.parse(workflow.revision_attachments || "[]");
  } catch {
    shots = [];
  }
  return (
    <div className="callout" style={{ marginBottom: 10, background: "var(--accent-soft)", border: "none" }}>
      {workflow.revision_of && (
        <div>
          🔧 <strong>Revision</strong> of <Link to={`/workflows/${workflow.revision_of}`}>the original workflow</Link> — fixing the
          problem reported on staging: <em>“{workflow.revision_note}”</em>
          {shots.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              {shots.map((name) => (
                <a key={name} href={api.attachmentUrl(workflow.id, name)} target="_blank" rel="noreferrer" title="Open full size">
                  <img src={api.attachmentUrl(workflow.id, name)} alt={`Screenshot ${name}`}
                    style={{ height: 90, borderRadius: 6, border: "1px solid var(--border)" }} />
                </a>
              ))}
            </div>
          )}
        </div>
      )}
      {revisions.length > 0 && (
        <div style={{ marginTop: workflow.revision_of ? 6 : 0 }}>
          🐞 Problems reported on staging:
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {revisions.map((r) => (
              <li key={r.id}>
                <Link to={`/workflows/${r.id}`}>“{r.revision_note}”</Link> — <StatusBadge state={r.state} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** After a feature is merged into staging: run staging locally, then release it to main. */
function StagingRelease({
  workflowId,
  staging,
  token,
  tokenMissing,
  busy,
  act,
}: {
  workflowId: string;
  staging: string;
  token: string;
  tokenMissing: boolean;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [preview, setPreview] = useState<PreviewInfo | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [starting, setStarting] = useState(false);
  const [release, setRelease] = useState<PRState | null>(null);
  const [releaseError, setReleaseError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verified, setVerified] = useState(false);
  const [approve, setApprove] = useState(false);

  const loadRelease = useCallback(
    async (tok: string) => {
      setLoading(true);
      setReleaseError("");
      try {
        setRelease(await api.releaseStatus(workflowId, tok));
      } catch (e) {
        setReleaseError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [workflowId]
  );

  useEffect(() => {
    api.previewInfo(workflowId).then(setPreview).catch(() => setPreview(null));
    loadRelease("");
  }, [workflowId, loadRelease]);

  async function startPreview() {
    setStarting(true);
    setPreviewError("");
    try {
      setPreview(await api.previewStart(workflowId, token));
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  const released = release?.published && release.state === "merged";

  return (
    <div className="card" style={{ padding: "12px 14px", marginTop: 14 }}>
      <div className="card-title" style={{ marginBottom: 6 }}>
        {staging} → main
      </div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 10px" }}>
        The feature is in <code>{staging}</code>. Run it and check it works, then release <code>{staging}</code> to{" "}
        <code>main</code>.
      </p>

      {/* 1. Run and check staging */}
      <div className="eyebrow" style={{ marginBottom: 4 }}>1 · Run {staging}</div>
      {preview?.running ? (
        <div style={{ fontSize: 12.5, marginBottom: 10 }}>
          ▶️ Running <code>{preview.branch}</code>@<code>{preview.sha}</code> ·{" "}
          <a href={preview.open_url ?? preview.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
            Open app ({preview.open_url ?? preview.url})
          </a>{" "}
          · <a href={`${preview.url}/docs`} target="_blank" rel="noreferrer">API docs</a>
          {preview.comment_url && (
            <> · <a href={preview.comment_url} target="_blank" rel="noreferrer">address posted on the PR</a></>
          )}
          <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 2 }}>
            {preview.mode === "docker"
              ? "Running in a Docker container built from the branch's Dockerfile. "
              : "Running as a local process (start Docker Desktop to run staging from its Dockerfile). "}
            Port {preview.port} is this project's preview port — the same every time for this repository.
          </div>
          {preview.last_release?.status === "blocked" && (
            <div className="callout callout-danger" style={{ marginTop: 6 }}>
              Release #{preview.last_release.number} ({preview.last_release.sha}) was <strong>not put live</strong>:{" "}
              {preview.last_release.reason} The site keeps serving release #{preview.release} — nothing went down. See{" "}
              <Link to="/monitoring">Monitoring &amp; Alerts</Link>.
            </div>
          )}
          <div style={{ fontSize: 12, marginTop: 6, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <span>🟢 Release #{preview.release} live</span>
            <span>{preview.standby ? "🛡️ Hot standby ready" : "⚠️ No standby"}</span>
            {preview.monitor?.availability != null && (
              <span>📈 {preview.monitor.availability}% available · checked every {preview.monitor.interval_seconds}s</span>
            )}
            {preview.previous && <span>↩️ Previous: #{preview.previous.number} ({preview.previous.sha})</span>}
          </div>
          <div className="btn-row" style={{ marginTop: 6 }}>
            <button className="btn" disabled={starting} onClick={startPreview}>
              {starting ? "Releasing…" : `Release latest ${staging} (zero downtime)`}
            </button>
            {preview.previous && (
              <button
                className="btn"
                disabled={starting}
                onClick={async () => {
                  setPreviewError("");
                  try {
                    setPreview(await api.previewRollback(workflowId));
                  } catch (e) {
                    setPreviewError(e instanceof Error ? e.message : String(e));
                  }
                }}
              >
                Roll back to #{preview.previous.number}
              </button>
            )}
            <button className="btn" onClick={async () => setPreview(await api.previewStop(workflowId))}>Stop</button>
          </div>
        </div>
      ) : (
        <div style={{ marginBottom: 10 }}>
          <button className="btn btn-primary" disabled={starting} onClick={startPreview}>
            {starting ? `Starting ${staging}…` : `Run ${staging} preview`}
          </button>
          {preview && preview.exit_code != null && (
            <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 4 }}>The last preview stopped (exit code {preview.exit_code}).</div>
          )}
        </div>
      )}
      {previewError && <pre className="mono-block" style={{ maxHeight: 160, marginBottom: 10 }}>{previewError}</pre>}

      <ReportProblem workflowId={workflowId} staging={staging} />

      {/* 2. Release to main */}
      <div className="eyebrow" style={{ margin: "6px 0 4px" }}>2 · Release to main</div>
      {releaseError && <div className="callout callout-danger" style={{ marginBottom: 8 }}>{releaseError}</div>}
      {release && !release.published && (
        <button
          className="btn btn-primary"
          disabled={busy || tokenMissing}
          onClick={() => act(async () => { await api.releaseOpen(workflowId, token); await loadRelease(token); })}
        >
          Open release pull request ({staging} → main)
        </button>
      )}
      {release?.published && release.needs_token && (
        <div style={{ fontSize: 12.5 }}>
          <a href={release.url} target="_blank" rel="noreferrer">Release PR #{release.number}</a> — enter your token above, then{" "}
          <button className="btn" disabled={loading || tokenMissing} onClick={() => loadRelease(token)}>Load release status</button>
        </div>
      )}
      {release?.published && !release.needs_token && (
        <div style={{ fontSize: 12.5 }}>
          <a href={release.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>#{release.number} {release.title}</a>
          {released ? (
            <p style={{ margin: "8px 0 0" }}>✅ Released to <code>main</code> as <code>{release.merge_sha?.slice(0, 8)}</code>.</p>
          ) : (
            <>
              <div style={{ marginTop: 6 }}>
                <strong>Checks:</strong>{" "}
                {release.checks_summary && release.checks_summary.total > 0
                  ? `${release.checks_summary.passed} passed · ${release.checks_summary.pending} running · ${release.checks_summary.failed} failed`
                  : "No GitHub checks on this branch"}
              </div>
              {release.checks?.map((c) => <CheckRow key={`${c.id}-${c.url}`} workflowId={workflowId} check={c} token={token} />)}
              <div style={{ marginTop: 4 }}>
                <strong>Branch:</strong> {MERGE_STATE_LABEL[release.mergeable_state ?? "unknown"] ?? release.mergeable_state}
              </div>
              {release.blockers && release.blockers.length > 0 ? (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, color: "var(--danger)" }}>
                  {release.blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              ) : (
                <p style={{ color: "var(--success)", margin: "8px 0 0" }}>Checks passed — ready to release once you've verified {staging}.</p>
              )}
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button className="btn" disabled={loading || tokenMissing} onClick={() => loadRelease(token)}>
                  {loading ? "Checking…" : "Refresh"}
                </button>
              </div>
              <div style={{ borderTop: "1px solid var(--border)", marginTop: 10, paddingTop: 8 }}>
                <label className="check" style={{ marginBottom: 6 }}>
                  <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> I ran{" "}
                  <code>{staging}</code> and it works
                </label>
                <label className="check" style={{ marginTop: 6 }}>
                  <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} disabled={!release.can_merge} /> I approve
                  releasing <code>{staging}</code> to <code>main</code>
                </label>
                <button
                  className="btn btn-success"
                  style={{ marginTop: 8, display: "block" }}
                  disabled={busy || !release.can_merge || !verified || !approve || tokenMissing}
                  onClick={() =>
                    act(async () => {
                      await api.releaseMerge(workflowId, true, true, "", token);
                      await loadRelease(token);
                    })
                  }
                >
                  Release to main
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
type PRCheck = NonNullable<PRState["checks"]>[number];

const EVENT_LABEL: Record<string, string> = { push: "push", pull_request: "pull request" };

function outcomeIcon(status: string, conclusion: string): string {
  if (status && status !== "completed") return "⏳";
  if (["success", "neutral"].includes(conclusion)) return "✅";
  if (conclusion === "skipped") return "⏭️";
  return "❌";
}

function secs(n: number | null | undefined): string {
  if (n == null) return "";
  return n < 60 ? `${Math.round(n)}s` : `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
}

/** One CI check; click to see its steps, output and individual tests. */
function CheckRow({ workflowId, check, token }: { workflowId: string; check: PRCheck; token: string }) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<CheckDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || details || !check.id) return;
    setLoading(true);
    setError("");
    try {
      setDetails(await api.getCheckDetails(workflowId, check.id, token));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const passed = details?.tests.filter((t) => ["PASSED", "XFAIL"].includes(t.outcome)).length ?? 0;
  return (
    <div style={{ paddingLeft: 10 }}>
      <button
        type="button"
        onClick={toggle}
        disabled={!check.id}
        style={{ background: "none", border: "none", padding: "2px 0", color: "var(--text)", cursor: check.id ? "pointer" : "default", font: "inherit" }}
        title={check.id ? "Show steps, output and tests" : undefined}
      >
        {check.id ? (open ? "▾ " : "▸ ") : ""}
        {outcomeIcon(check.status, check.conclusion)} {check.name}
        {check.event && <span style={{ color: "var(--text-faint)" }}> · {EVENT_LABEL[check.event] ?? check.event}</span>}
      </button>

      {open && (
        <div style={{ borderLeft: "2px solid var(--border)", margin: "4px 0 8px 6px", padding: "4px 0 4px 12px" }}>
          {loading && <div style={{ color: "var(--text-faint)" }}>Loading…</div>}
          {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
          {details && (
            <>
              <div style={{ color: "var(--text-muted)", marginBottom: 6 }}>
                {details.conclusion || details.status}
                {details.seconds != null && ` · ${secs(details.seconds)}`} ·{" "}
                <a href={details.url} target="_blank" rel="noreferrer">Open on GitHub</a>
              </div>

              {details.steps.length > 0 && (
                <>
                  <div className="eyebrow" style={{ marginBottom: 2 }}>Steps</div>
                  {details.steps.map((st) => (
                    <div key={`${st.number}-${st.name}`} style={{ display: "flex", gap: 8 }}>
                      <span>{outcomeIcon(st.status, st.conclusion)}</span>
                      <span style={{ flex: 1 }}>{st.name}</span>
                      <span style={{ color: "var(--text-faint)" }}>{secs(st.seconds)}</span>
                    </div>
                  ))}
                </>
              )}

              <div className="eyebrow" style={{ margin: "8px 0 2px" }}>Tests</div>
              {details.tests.length > 0 ? (
                <>
                  <div style={{ color: "var(--text-muted)" }}>
                    {passed}/{details.tests.length} passed{details.test_summary && ` · ${details.test_summary}`}
                  </div>
                  {details.tests.map((t) => (
                    <div key={t.name} style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>
                      {t.outcome === "PASSED" ? "✅" : t.outcome === "SKIPPED" ? "⏭️" : "❌"} {t.name}
                    </div>
                  ))}
                </>
              ) : details.test_summary ? (
                <div style={{ color: "var(--text-muted)" }}>
                  {details.test_summary}
                  <div style={{ fontSize: 11.5, color: "var(--text-faint)" }}>
                    Test names aren't in the log because CI runs <code>pytest -q</code>; use <code>pytest -v</code> in
                    .github/workflows/ci.yml to list each test.
                  </div>
                </div>
              ) : (
                <div style={{ color: "var(--text-faint)" }}>
                  {details.logs_available ? "No pytest output found in this job." : "Log not available (token needs Actions: read)."}
                </div>
              )}

              {details.sections.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>Output ({details.sections.length} steps)</summary>
                  {details.sections.map((sec, i) => (
                    <div key={i} style={{ marginTop: 6 }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 11.5, fontWeight: 600 }}>{sec.title}</div>
                      {sec.output.length > 0 ? (
                        <pre className="mono-block" style={{ maxHeight: 180, margin: "2px 0 0" }}>{sec.output.join("\n")}</pre>
                      ) : (
                        <div style={{ fontSize: 11.5, color: "var(--text-faint)" }}>(no output)</div>
                      )}
                    </div>
                  ))}
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

const MERGE_STATE_LABEL: Record<string, string> = {
  clean: "Up to date with base, no conflicts",
  behind: "Behind base — update the branch",
  dirty: "Merge conflicts with base",
  blocked: "Blocked by branch protection",
  unstable: "Some checks are still running or not passing",
  draft: "Draft pull request",
  unknown: "GitHub is still checking mergeability",
  has_hooks: "Mergeable",
};

const READINESS_LABELS: Record<string, string> = {
  functional_correctness: "Validation (tests, lint, syntax)",
  ci: "CI checks",
  regression_safety: "No regressions",
  security: "No secrets / security blocks",
  resilience: "Resilience experiments",
  rollback: "Rollback plan",
  open_risk: "Open risks",
  cost: "Cost budget",
  container: "Docker image",
  production_tests: "Production checks (live)",
};
const READINESS_GOOD = ["PASSED", "NONE", "NOT_APPLICABLE"];
const READINESS_WARN = ["SKIPPED", "WARNING", "UNKNOWN", "HIGH"];

/** Production Readiness: the release decision, why, and the checklist behind it. */
function ReadinessPanel({
  workflowId,
  workflow,
  busy,
  act,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.getReadiness>> | null>(null);
  useEffect(() => {
    api.getReadiness(workflowId).then(setData).catch(() => setData(null));
  }, [workflowId, workflow.state]);

  const tone = data?.decision === "READY" ? "success" : data?.decision === "READY_WITH_WARNINGS" ? "warn" : "danger";
  return (
    <div>
      {data?.decision ? (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
            <span className={`tag ${tone}`} style={{ fontSize: 13 }}>{data.decision.replace(/_/g, " ")}</span>
            <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>The release decision, from every check this workflow ran.</span>
          </div>
          <ul style={{ margin: "0 0 12px", paddingLeft: 18, fontSize: 13 }}>
            {data.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Checklist</div>
          <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse", marginBottom: 14 }}>
            <tbody>
              {Object.entries(data.checklist).map(([key, value]) => (
                <tr key={key} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "5px 4px" }}>{READINESS_LABELS[key] ?? key}</td>
                  <td style={{ padding: "5px 4px", textAlign: "right" }}>
                    <span className={`tag ${READINESS_GOOD.includes(value) ? "success" : READINESS_WARN.includes(value) ? "warn" : "danger"}`}>
                      {value.replace(/_/g, " ").toLowerCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <div className="empty-state" style={{ marginBottom: 12 }}>Readiness is assessed after validation.</div>
      )}
      {/* The commit is approved here, once readiness is known. */}
      {workflow.state === "AWAITING_COMMIT_APPROVAL" && (
        <CommitCIPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />
      )}
    </div>
  );
}

const STEP_LABELS: Record<string, string> = {
  "actions/checkout@v4": "Check out the code",
  "actions/setup-python@v5": "Set up Python",
};
// What each GitHub Actions step does, shown when its chip is clicked.
const STEP_HELP: Record<string, string> = {
  "Check out the code": "Downloads the commit being tested onto a fresh GitHub machine.",
  "Set up Python": "Installs Python 3.12 on the machine.",
  "Install dependencies": "Installs everything in requirements.txt, plus the linter.",
  Lint: "ruff check . — style mistakes, unused code and likely bugs.",
  "Security scan": "ruff check --select S . — insecure code patterns (hard-coded secrets, unsafe calls…).",
  Tests: "python -m pytest -v — the project's whole test suite.",
  "Build image": "docker build — builds the production image from the Dockerfile.",
  "Run container": "Starts that image exactly as it will run in production.",
  "Check the running container": "Waits until the container answers its health check.",
  "Production checks (smoke, API, hostile input, load)":
    "Runs .github/scripts/production_check.py against the container: every endpoint, the API contract, hostile input and a load test.",
  "Restart and recovery": "Restarts the container and checks it comes back healthy.",
  "Container logs": "Prints the container's logs so a failure can be diagnosed.",
};

type CIGroup = { key: string; label: string; icon: string; items: ValidationResultItem[] };

function groupStages(results: ValidationResultItem[]): CIGroup[] {
  const groups: CIGroup[] = [];
  const add = (key: string, label: string, icon: string, item: ValidationResultItem) => {
    const g = groups.find((x) => x.key === key);
    if (g) g.items.push(item);
    else groups.push({ key, label, icon, items: [item] });
  };
  for (const r of results) {
    if (r.stage === "syntax") add("syntax", "Syntax", "🧩", r);
    else if (r.stage.startsWith("prod_")) add("prod", "Production checks", "🚀", r);
    else if (r.stage === "lint") add("lint", "Lint", "🧹", r);
    else if (r.stage === "unit_tests") add("tests", "Unit tests", "🧪", r);
    else if (r.stage === "docker_build") add("docker", "Docker build", "🐳", r);
    else if (r.stage === "security") add("security", "Security scan", "🔒", r);
    else add(r.stage, VALIDATION_STAGE_LABELS[r.stage] ?? r.stage.replace(/_/g, " "), "⚙️", r);
  }
  return groups;
}

function groupStatus(g: CIGroup): string {
  if (g.items.some((i) => i.status === "failed" || i.status === "error")) return "failed";
  if (g.items.every((i) => i.status === "skipped")) return "skipped";
  return "passed";
}

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** CI/CD: exactly what runs — the sandbox pipeline, the GitHub Actions jobs, and delivery. Interactive. */
function CIPanel({ workflowId, workflow, stage }: { workflowId: string; workflow: Workflow; stage: PipelineStage }) {
  const [results, setResults] = useState<ValidationResultItem[]>([]);
  const [actions, setActions] = useState<Awaited<ReturnType<typeof api.getCIWorkflows>>["workflows"]>([]);
  const [remote, setRemote] = useState<Awaited<ReturnType<typeof api.getCIStatus>> | null>(null);
  const [deploy, setDeploy] = useState<PreviewInfo | null>(null);
  const [revealed, setRevealed] = useState(0); // how many pipeline nodes have "run" in the animation
  const [selected, setSelected] = useState<string | null>(null);
  const [stepInfo, setStepInfo] = useState<string | null>(null);
  const [run, setRun] = useState(0); // bump to replay

  useEffect(() => {
    api.getValidation(workflowId).then((v) => setResults(v.results)).catch(() => setResults([]));
    api.getCIWorkflows(workflowId).then((w) => setActions(w.workflows)).catch(() => setActions([]));
    api.getCIStatus(workflowId).then(setRemote).catch(() => setRemote(null));
    api.previewInfo(workflowId).then(setDeploy).catch(() => setDeploy(null));
  }, [workflowId, workflow.state]);

  const attempt = results.length ? Math.max(...results.map((r) => r.attempt)) : 0;
  const latest = results.filter((r) => r.attempt === attempt);
  const groups = groupStages(latest);

  // Replay: light the pipeline up node by node.
  useEffect(() => {
    if (!groups.length) return;
    if (prefersReducedMotion()) {
      setRevealed(groups.length);
      return;
    }
    setRevealed(0);
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setRevealed(n);
      if (n >= groups.length) clearInterval(timer);
    }, 380);
    return () => clearInterval(timer);
  }, [groups.length, run]);

  const totalMs = latest.reduce((a, r) => a + (r.duration_ms || 0), 0);
  const passed = latest.filter((r) => r.status === "passed").length;
  const prodCount = latest.filter((r) => r.stage.startsWith("prod_")).length;
  const actionsUrl = remote?.repository ? `https://github.com/${remote.repository}/actions` : "";
  const progress = groups.length ? Math.round((revealed / groups.length) * 100) : 0;
  const current = groups.find((g) => g.key === selected) ?? null;

  // CD: which delivery step we are on.
  const cdStep = deploy?.running ? 2 : 0; // running on staging = merged and released

  return (
    <div>
      {/* Summary strip */}
      <div className="ci-summary">
        <div><strong>{groups.length || "—"}</strong><span>stages</span></div>
        <div><strong className="ok">{passed}</strong><span>checks passed</span></div>
        <div><strong>{prodCount}</strong><span>live production checks</span></div>
        <div><strong>{totalMs ? `${(totalMs / 1000).toFixed(1)}s` : "—"}</strong><span>total time</span></div>
        <div><strong>{actions.length}</strong><span>GitHub workflows</span></div>
      </div>

      {/* 1. Sandbox pipeline */}
      <div className="ci-section">
        <div className="ci-section-head">
          <span className="eyebrow">1 · CI in Intent2Deploy's sandbox (before the commit)</span>
          {groups.length > 0 && (
            <button className="btn" style={{ padding: "2px 10px", fontSize: 12 }} onClick={() => { setSelected(null); setRun((x) => x + 1); }}>
              ▶ Replay
            </button>
          )}
        </div>
        {groups.length === 0 ? (
          <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Runs after the changes are approved.</div>
        ) : (
          <>
            <div className="ci-progress"><span style={{ width: `${progress}%` }} /></div>
            <div className="ci-flow">
              {groups.map((g, i) => {
                const st = groupStatus(g);
                const shown = i < revealed;
                const running = i === revealed && revealed < groups.length;
                return (
                  <div key={g.key} className="ci-flow-item">
                    {i > 0 && <span className={`ci-connector${shown ? " lit" : ""}`} aria-hidden="true" />}
                    <button
                      type="button"
                      className={`ci-node ${shown ? st : running ? "running" : "waiting"}${selected === g.key ? " selected" : ""}`}
                      onClick={() => setSelected(selected === g.key ? null : g.key)}
                      aria-expanded={selected === g.key}
                      title="Click for details"
                    >
                      <span className="ci-node-icon">{shown ? (st === "passed" ? "✓" : st === "failed" ? "✕" : "–") : g.icon}</span>
                      <span className="ci-node-label">{g.label}</span>
                      {g.items.length > 1 && <span className="ci-node-count">×{g.items.length}</span>}
                    </button>
                  </div>
                );
              })}
            </div>
            {current ? (
              <div className="ci-detail" key={current.key}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{current.icon} {current.label}</div>
                {current.items.map((r, i) => (
                  <details key={i} className="ci-detail-row" open={current.items.length === 1}>
                    <summary>
                      <StatusBadge state={r.status} />
                      <span style={{ fontWeight: 600 }}>{VALIDATION_STAGE_LABELS[r.stage] ?? r.stage.replace(/_/g, " ")}</span>
                      <code className="ci-cmd">{r.command || "—"}</code>
                      <span className="ci-ms">{r.duration_ms}ms</span>
                    </summary>
                    {(r.stdout || r.stderr) ? (
                      <pre className="mono-block" style={{ maxHeight: 260, margin: "6px 0 0" }}>{(r.stdout || r.stderr).slice(0, 4000)}</pre>
                    ) : (
                      <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 0" }}>No output — it passed cleanly.</div>
                    )}
                  </details>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
                {stage.status === "PASSED" ? "✅ All required stages passed." : stage.output} Click a stage to see its checks and output.
              </div>
            )}
          </>
        )}
      </div>

      {/* 2. GitHub Actions */}
      <div className="ci-section">
        <div className="ci-section-head">
          <span className="eyebrow">2 · CI on GitHub Actions (on the pull request and after each merge)</span>
          {(remote?.url || actionsUrl) && (
            <a href={remote?.url || actionsUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Open on GitHub ↗</a>
          )}
        </div>
        {actions.length === 0 && (
          <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>No GitHub Actions workflows in this project.</div>
        )}
        {actions.map((w) => (
          <div key={w.file} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>{w.name}</strong> <code style={{ fontSize: 11.5 }}>{w.file}</code>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}> — runs on {w.triggers.join(" and ")}</span>
            </div>
            {w.jobs.map((j) => (
              <div key={j.id} className="ci-chips">
                {j.steps.map((raw, i) => {
                  const label = STEP_LABELS[raw] ?? raw;
                  const id = `${w.file}:${i}`;
                  return (
                    <div key={id} className="ci-chip-wrap">
                      {i > 0 && <span className="ci-chip-arrow" aria-hidden="true">→</span>}
                      <button
                        type="button"
                        className={`ci-chip${stepInfo === id ? " selected" : ""}`}
                        style={{ animationDelay: `${i * 60}ms` }}
                        onClick={() => setStepInfo(stepInfo === id ? null : id)}
                      >
                        <span className="ci-chip-n">{i + 1}</span> {label}
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
            {stepInfo?.startsWith(`${w.file}:`) && (() => {
              const idx = Number(stepInfo.split(":").pop());
              const label = STEP_LABELS[w.jobs[0]?.steps[idx]] ?? w.jobs[0]?.steps[idx];
              return (
                <div className="ci-detail" style={{ marginTop: 6 }}>
                  <strong>{label}:</strong> {STEP_HELP[label] ?? "A step of this workflow."}
                </div>
              );
            })()}
          </div>
        ))}
        <div style={{ fontSize: 12.5 }}>
          <strong>Latest result on GitHub:</strong>{" "}
          {remote
            ? remote.status === "needs_token"
              ? "enter your GitHub token in the GitHub / PR step to see each check here, or open the Actions page."
              : `${remote.status} — ${remote.detail}`
            : "—"}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
          A failing or still-running check blocks the merge in the GitHub / PR step.
        </div>
      </div>

      {/* 3. CD */}
      <div className="ci-section">
        <div className="ci-section-head"><span className="eyebrow">3 · CD: delivery after the merge</span></div>
        <div className="cd-stepper">
          {[
            { title: "Merge into staging", text: "After its checks pass and you approve the pull request." },
            {
              title: "Zero-downtime release",
              text: "The new version starts next to the live one, passes live production checks, then takes the traffic.",
            },
            { title: "Live on staging", text: "A hot standby and a watchdog keep it up; failures raise alerts." },
            { title: "Release to main", text: "The release pull request takes staging to main — CI runs again there." },
          ].map((s, i) => (
            <div key={s.title} className={`cd-step${i < cdStep ? " done" : i === cdStep ? " current" : ""}`}>
              <div className="cd-dot">{i < cdStep ? "✓" : i + 1}</div>
              <div>
                <div className="cd-title">{s.title}</div>
                <div className="cd-text">{s.text}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12.5, marginTop: 8 }}>
          <strong>Staging right now:</strong>{" "}
          {deploy?.running ? (
            <>
              <span className="live-dot" aria-hidden="true" /> release #{deploy.release} ({deploy.sha}) live at{" "}
              <a href={deploy.open_url ?? deploy.url} target="_blank" rel="noreferrer">{deploy.url}</a>
              {deploy.standby ? " · hot standby ready" : ""}
              {deploy.monitor?.availability != null ? ` · ${deploy.monitor.availability}% available` : ""} ·{" "}
              <Link to="/monitoring">Monitoring &amp; Alerts</Link>
            </>
          ) : (
            "not running — start it from the GitHub / PR step (staging → main)."
          )}
        </div>
      </div>
    </div>
  );
}

function CommitCIPanel({
  workflowId,
  workflow,
  busy,
  act,
  pipelineStage,
}: {
  workflowId: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
  pipelineStage?: PipelineStage; // what Intent2Deploy recorded (merges, releases), shown when GitHub can't be read
}) {
  const [comment, setComment] = useState("");
  const [target, setTarget] = useState<Awaited<ReturnType<typeof api.getGitHubTarget>> | null>(null);
  const [token, setToken] = useState("");
  const [pr, setPR] = useState<PRState | null>(null);
  const [prError, setPRError] = useState("");
  const [loading, setLoading] = useState(false);
  const [approve, setApprove] = useState(false);
  const [mergeComment, setMergeComment] = useState("");

  const committed = ["COMMITTED", "CI_RUNNING", "COMPLETED"].includes(workflow.state);

  const loadStatus = useCallback(
    async (tok: string) => {
      setLoading(true);
      setPRError("");
      try {
        setPR(await api.getPRStatus(workflowId, tok));
      } catch (e) {
        setPRError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [workflowId]
  );

  useEffect(() => {
    if (!committed) return;
    api
      .getGitHubTarget(workflowId)
      .then((t) => {
        setTarget(t);
        if (t.configured) loadStatus("");
      })
      .catch(() => setTarget(null));
  }, [workflowId, committed, loadStatus]);

  const needsToken = !!target && target.configured && !target.server_token;
  const tok = token.trim();
  const tokenMissing = needsToken && !tok;

  function publish() {
    return act(async () => {
      await api.publishPR(workflowId, tok);
      await loadStatus(tok);
    });
  }

  function updateBranch() {
    return act(async () => {
      await api.updatePRBranch(workflowId, tok);
      await loadStatus(tok);
    });
  }

  function merge() {
    return act(async () => {
      await api.mergePR(workflowId, true, mergeComment, tok);
      setApprove(false);
      await loadStatus(tok);
    });
  }

  const merged = pr?.published && pr.state === "merged";

  return (
    <div>
      {/* Commit approval */}
      {workflow.state === "AWAITING_COMMIT_APPROVAL" && (
        <div style={{ marginBottom: 18 }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Commit approval required</div>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
            Validation passed. Approve to commit the changes to feature branch{" "}
            <code>{workflow.branch_name || "(not yet created)"}</code> (from <code>{workflow.base_branch}</code>).{" "}
            <code>{workflow.base_branch}</code> itself is not changed.
          </p>
          <label>Comment (optional)</label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Commit notes…" style={{ marginBottom: 10 }} />
          <div className="btn-row">
            <button className="btn btn-success" disabled={busy} onClick={() => act(() => api.approveCommit(workflowId, true, comment))}>
              Approve &amp; Commit
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => act(() => api.approveCommit(workflowId, false, comment))}>
              Reject
            </button>
          </div>
        </div>
      )}

      {committed && workflow.branch_name && (
        <div className="ci-status-block" style={{ marginBottom: 14 }}>
          <span className="ci-status-icon">🌿</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              Feature branch <code>{workflow.branch_name}</code> → <code>{workflow.base_branch}</code>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              {merged
                ? `Merged into ${pr?.base} via PR #${pr?.number}.`
                : pr?.needs_token && pipelineStage?.output && /^(Merged|Released)/.test(pipelineStage.output)
                  ? pipelineStage.output
                  : pr?.needs_token
                    ? `Pull request #${pr.number} — enter your GitHub token to see whether it is still open.`
                    : pr?.published
                      ? `Pull request #${pr.number} is open; ${workflow.base_branch} changes only when it is merged.`
                      : `Committed locally. ${workflow.base_branch} is untouched; changes reach it only through a pull request.`}
            </div>
          </div>
        </div>
      )}

      {committed && target && !target.configured && (
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          This repository isn't linked to GitHub, so there is no pull request flow. Connect it from GitHub on the Repositories page.
        </p>
      )}

      {committed && target?.configured && (
        <div style={{ marginBottom: 14 }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Pull request → {target.repository}</div>

          {needsToken && !merged && (
            <div style={{ maxWidth: 420, marginBottom: 10 }}>
              <label htmlFor="gh-token">GitHub token (Contents, Pull requests, Checks: read &amp; write)</label>
              <input id="gh-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="github_pat_…" autoComplete="off" />
              <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 4 }}>Used for each action only. Not stored.</div>
            </div>
          )}

          {prError && <div className="callout callout-danger" style={{ marginBottom: 8 }}>{prError}</div>}

          {pr && !pr.published && (
            <button className="btn btn-primary" disabled={busy || tokenMissing} onClick={publish}>
              Push branch &amp; open pull request → {pr.base}
            </button>
          )}

          {!pr && prError && (
            <button className="btn" disabled={loading || busy || tokenMissing} onClick={() => loadStatus(tok)}>
              {loading ? "Loading…" : "Retry"}
            </button>
          )}

          {pr?.published && pr.needs_token && (
            <div className="card" style={{ padding: "12px 14px", marginBottom: 0 }}>
              <a href={pr.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
                Pull request #{pr.number}
              </a>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                <code>{pr.head}</code> → <code>{pr.base}</code>
              </div>
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0" }}>
                Enter your GitHub token above, then load the checks, merge status and merge option.
              </p>
              <button className="btn btn-primary" disabled={loading || busy || tokenMissing} onClick={() => loadStatus(tok)}>
                {loading ? "Loading…" : "Load PR status"}
              </button>
            </div>
          )}

          {pr?.published && !pr.needs_token && (
            <div className="card" style={{ padding: "12px 14px", marginBottom: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "baseline" }}>
                <a href={pr.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
                  #{pr.number} {pr.title}
                </a>
                <span className={`tag ${merged ? "success" : pr.state !== "open" ? "danger" : pr.can_merge ? "success" : "warn"}`}>
                  {merged ? "Merged" : pr.state !== "open" ? "Closed" : pr.can_merge ? "Ready to merge" : "Not ready to merge"}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                <code>{pr.head}</code> → <code>{pr.base}</code>
              </div>

              {merged ? (
                <p style={{ fontSize: 13, margin: "10px 0 0" }}>
                  ✅ Merged into <code>{pr.base}</code> as <code>{pr.merge_sha?.slice(0, 8)}</code>.
                </p>
              ) : (
                <>
                  <div style={{ marginTop: 10, fontSize: 12.5 }}>
                    <div>
                      <strong>Checks:</strong>{" "}
                      {pr.checks_summary && pr.checks_summary.total > 0
                        ? `${pr.checks_summary.passed} passed · ${pr.checks_summary.pending} running · ${pr.checks_summary.failed} failed`
                        : `No GitHub checks on this branch — local validation ${pr.local_validation_passed ? "passed" : "did not pass"}`}
                    </div>
                    {pr.checks?.map((c) => (
                      <CheckRow key={`${c.id}-${c.url}`} workflowId={workflowId} check={c} token={tok} />
                    ))}
                    <div style={{ marginTop: 4 }}>
                      <strong>Branch:</strong> {MERGE_STATE_LABEL[pr.mergeable_state ?? "unknown"] ?? pr.mergeable_state}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      <strong>Reviewer:</strong> {pr.viewer} {pr.viewer_can_merge ? "(can merge)" : "(no write access)"}
                    </div>
                  </div>

                  {pr.blockers && pr.blockers.length > 0 ? (
                    <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: 12.5, color: "var(--danger)" }}>
                      {pr.blockers.map((b) => <li key={b}>{b}</li>)}
                    </ul>
                  ) : (
                    <p style={{ fontSize: 12.5, color: "var(--success)", margin: "10px 0 0" }}>All checks passed — ready to merge with your approval.</p>
                  )}

                  <div className="btn-row" style={{ marginTop: 10 }}>
                    <button className="btn" disabled={loading || busy || tokenMissing} onClick={() => loadStatus(tok)}>
                      {loading ? "Checking…" : "Refresh"}
                    </button>
                    {(pr.mergeable_state === "behind" || pr.mergeable_state === "dirty") && (
                      <button className="btn" disabled={busy || tokenMissing} onClick={updateBranch}>
                        Update branch from {pr.base}
                      </button>
                    )}
                  </div>

                  <div style={{ borderTop: "1px solid var(--border)", marginTop: 12, paddingTop: 10 }}>
                    <label className="check" style={{ marginBottom: 8 }}>
                      <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} disabled={!pr.can_merge} />{" "}
                      I approve merging PR #{pr.number} into <code>{pr.base}</code>
                    </label>
                    <input
                      value={mergeComment}
                      onChange={(e) => setMergeComment(e.target.value)}
                      placeholder="Approval note (optional)"
                      style={{ maxWidth: 420, display: "block", marginTop: 8 }}
                    />
                    <button
                      className="btn btn-success"
                      style={{ marginTop: 8 }}
                      disabled={busy || !pr.can_merge || !approve || tokenMissing}
                      onClick={merge}
                    >
                      Merge into {pr.base}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {committed && target?.configured && merged && pr?.base && pr.base !== "main" && pr.base !== "master" && (
        <StagingRelease workflowId={workflowId} staging={pr.base} token={tok} tokenMissing={tokenMissing} busy={busy} act={act} />
      )}

      {/* Finalize without merging (e.g. no GitHub link) */}
      {workflow.state === "COMMITTED" && !merged && (
        <div style={{ marginTop: 14 }}>
          <button className="btn" disabled={busy} onClick={() => act(() => api.completeWorkflow(workflowId))}>
            Finalize workflow without merging
          </button>
        </div>
      )}
    </div>
  );
}

function ReportPanel({ workflowId }: { workflowId: string }) {
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.getReport(workflowId)
      .then((r) => setReport(r as unknown as Record<string, unknown>))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [workflowId]);

  if (loading) return <div className="empty-state">Loading report…</div>;
  if (err) return <div className="callout callout-danger">{err}</div>;
  if (!report) return <div className="empty-state">No report available yet.</div>;

  const summary = (report.workflow_summary as Record<string, unknown>) ?? {};
  const guardrails = (report.guardrails as Record<string, unknown>) ?? {};
  const timing = (report.timing_ms as Record<string, number | null>) ?? {};
  const finalStatus = String(report.final_status ?? "COMPLETED");
  const execSummary = report.executive_summary ? String(report.executive_summary) : null;
  const humanCount = typeof summary.human_intervention_count === "number" ? summary.human_intervention_count : null;
  const repairCount = typeof summary.repair_attempts === "number" ? summary.repair_attempts : null;
  const guardrailsPassed = typeof guardrails.passed === "number" ? guardrails.passed : null;
  const guardrailsWarnings = typeof guardrails.warnings === "number" ? guardrails.warnings as number : 0;
  const guardrailsBlocked = typeof guardrails.blocked === "number" ? guardrails.blocked as number : 0;

  return (
    <div>
      {/* Outcome */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <StatusBadge state={finalStatus} />
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {humanCount !== null && `${humanCount} human checkpoint${humanCount !== 1 ? "s" : ""}`}
          {repairCount !== null && ` · ${repairCount} repair attempt${repairCount !== 1 ? "s" : ""}`}
        </span>
      </div>

      {execSummary && (
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
          {execSummary}
        </p>
      )}

      {/* Guardrails summary */}
      {guardrailsPassed !== null && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 16 }}>
          <span className="tag success">{guardrailsPassed} guardrails passed</span>
          {guardrailsWarnings > 0 && <span className="tag warn">{guardrailsWarnings} warnings</span>}
          {guardrailsBlocked > 0 && <span className="tag danger">{guardrailsBlocked} blocked</span>}
        </div>
      )}

      {/* Timing */}
      {Object.keys(timing).length > 0 && (
        <div className="timing-chips" style={{ marginBottom: 16 }}>
          {Object.entries(timing).map(([k, v]) => v != null && (
            <span key={k} className="timing-chip">{k}: <span>{v}ms</span></span>
          ))}
        </div>
      )}

      {/* Changes */}
      {Array.isArray(report.changes) && (report.changes as unknown[]).length > 0 && (
        <Expand title={`${(report.changes as unknown[]).length} files changed`}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "8px 0" }}>
            {(report.changes as { file: string; operation: string }[]).map((c, i) => (
              <span key={i} className="plan-step-file-tag">{c.operation}: {c.file}</span>
            ))}
          </div>
        </Expand>
      )}

      {/* Validation summary */}
      {Array.isArray(report.validation_results) && (
        <Expand title="Validation results">
          <table style={{ marginTop: 8 }}>
            <thead><tr><th>Stage</th><th>Status</th><th>Attempt</th><th>Duration</th></tr></thead>
            <tbody>
              {(report.validation_results as { stage: string; status: string; attempt: number; duration_ms: number }[]).map((r, i) => (
                <tr key={i}>
                  <td>{r.stage}</td>
                  <td><StatusBadge state={r.status} /></td>
                  <td>{r.attempt}</td>
                  <td>{r.duration_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Expand>
      )}

      {/* Audit trail */}
      {Array.isArray(report.audit_trail) && (
        <Expand title={`Audit trail (${(report.audit_trail as unknown[]).length} events)`}>
          <div className="timeline" style={{ marginTop: 8 }}>
            {(report.audit_trail as { event_type: string; stage: string; timestamp: string }[]).map((e, i) => (
              <div key={i} className="timeline-item">
                <div className="timeline-event">{e.event_type.replace(/_/g, " ")}</div>
                <div className="timeline-meta">{new Date(e.timestamp).toLocaleString()} {e.stage && `· ${e.stage}`}</div>
              </div>
            ))}
          </div>
        </Expand>
      )}

      {/* Downloads */}
      <div className="btn-row" style={{ marginTop: 16 }}>
        <a className="btn" href={api.getReportMarkdownUrl(workflowId)} download>
          Download .md
        </a>
        <a className="btn" href={api.getReportJsonUrl(workflowId)} download>
          Download .json
        </a>
      </div>
    </div>
  );
}

// ─── Stage name → panel mapping ─────────────────────────────────────────────

function StagePanel({
  stageName,
  stage,
  workflow,
  busy,
  act,
  workflowId,
  events,
}: {
  stageName: string;
  stage: PipelineStage;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
  workflowId: string;
  events: AuditEventItem[];
}) {
  // Retrieval-related stages all show the retrieval panel
  if (["Developer Intent"].includes(stageName)) {
    return <IntentPanel workflow={workflow} stage={stage} />;
  }
  if (workflow.project_mode === "greenfield" && ["Repository RAG", "Architecture Analysis", "Intent Understanding"].includes(stageName)) {
    return <GreenfieldDesignPanel workflow={workflow} />;
  }
  if (["Repository RAG", "Architecture Analysis", "Intent Understanding", "Production Context"].includes(stageName)) {
    return <RetrievalPanel workflowId={workflowId} stage={stage} workflow={workflow} busy={busy} act={act} />;
  }
  if (stageName === "Risk Analysis") {
    return <RiskPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />;
  }
  if (["Engineering Plan", "Human Approval"].includes(stageName)) {
    return <PlanPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />;
  }
  if (["Code Generation"].includes(stageName)) {
    return <CodegenPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />;
  }
  if (["Test Generation", "Validation", "AI Repair", "Resilience Testing", "Chaos Simulation"].includes(stageName)) {
    return <ValidationPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />;
  }
  if (stageName === "Production Readiness") {
    return <ReadinessPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} />;
  }
  if (stageName === "CI/CD") {
    return <CIPanel workflowId={workflowId} workflow={workflow} stage={stage} />;
  }
  if (stageName === "GitHub / PR") {
    return <CommitCIPanel workflowId={workflowId} workflow={workflow} busy={busy} act={act} pipelineStage={stage} />;
  }
  if (["Final Report"].includes(stageName)) {
    return <ReportPanel workflowId={workflowId} />;
  }

  // Generic fallback: show stage metadata + recent events
  return (
    <div>
      {stage.output && (
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>{stage.output}</p>
      )}
      {stage.evidence.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Evidence</div>
          <ul style={{ paddingLeft: 18, margin: 0 }}>
            {stage.evidence.map((e, i) => <li key={i} style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 3 }}>{e}</li>)}
          </ul>
        </div>
      )}
      {stage.guardrails_triggered.length > 0 && (
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Guardrails</div>
          {stage.guardrails_triggered.map((g) => (
            <div key={g.guardrail_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
              <code style={{ fontSize: 11 }}>{g.guardrail_id}</code>
              <span style={{ flex: 1, color: "var(--text-muted)" }}>{g.name}</span>
              <StatusBadge state={g.status} />
            </div>
          ))}
        </div>
      )}
      {events.length === 0 && !stage.output && (
        <div className="empty-state">No data recorded for this stage yet.</div>
      )}
    </div>
  );
}

// ─── Greenfield (new project) ────────────────────────────────────────────────

function parseDesign(workflow: Workflow): GreenfieldDesign | null {
  if (!workflow.greenfield_design_json) return null;
  try {
    return JSON.parse(workflow.greenfield_design_json) as GreenfieldDesign;
  } catch {
    return null;
  }
}

const GF_ORDER = [
  "CREATED", "INDEXING", "INDEXED", "PLANNING", "PLAN_READY", "AWAITING_PLAN_APPROVAL", "PLAN_REJECTED",
  "CHANGES_GENERATING", "CHANGES_READY", "AWAITING_CHANGE_APPROVAL", "CHANGES_REJECTED", "TESTS_GENERATING",
  "VALIDATING", "VALIDATION_FAILED", "REPAIRING", "VALIDATION_PASSED", "AWAITING_COMMIT_APPROVAL",
  "COMMITTED", "CI_RUNNING", "COMPLETED",
];

/** Generation checklist for a project being built from scratch. */
function GreenfieldProgress({ workflow, pipeline, busy }: { workflow: Workflow; pipeline: PipelineStage[]; busy: boolean }) {
  const design = parseDesign(workflow);
  const at = (s: string) => GF_ORDER.indexOf(workflow.state) >= GF_ORDER.indexOf(s);
  const stage = (name: string) => pipeline.find((p) => p.name === name)?.status;
  const codegen = stage("Code Generation");
  const validation = stage("Validation");
  const failed = workflow.state === "FAILED";

  type Step = { label: string; detail?: string; status: "done" | "active" | "error" | "" };
  const steps: Step[] = [
    {
      label: "Requirements analyzed",
      detail: design ? `${design.requirements.length} requirements · ${design.acceptance_criteria.length} acceptance criteria` : undefined,
      status: design ? "done" : workflow.state === "PLANNING" ? "active" : "",
    },
    {
      label: "Architecture designed",
      detail: design ? `${design.stack} · ${design.components.length} components` : undefined,
      status: design ? "done" : workflow.state === "PLANNING" ? "active" : "",
    },
    {
      label: "Project files generated",
      detail: codegen === "PASSED" && design ? `${design.files.length} files` : undefined,
      status: codegen === "PASSED" ? "done" : codegen === "BLOCKED" ? "error" : workflow.state === "CHANGES_GENERATING" && busy ? "active" : "",
    },
    {
      label: "Files written to workspace",
      status: at("TESTS_GENERATING") && !failed ? "done" : "",
    },
    {
      label: "Tests, lint and security checks run",
      detail: validation === "PASSED" ? "passed" : validation === "FAILED" ? "failed — see Validate" : undefined,
      status: validation === "PASSED" ? "done" : validation === "FAILED" ? "error" : workflow.state === "VALIDATING" || (busy && at("TESTS_GENERATING")) ? "active" : "",
    },
    {
      label: "Committed",
      status: at("COMMITTED") && !failed ? "done" : "",
    },
  ];

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div className="card-title" style={{ marginBottom: 4 }}>New project</div>
        {design?.template && (
          <span className="tag warn" title="Set LLM_MODE=live for intent-specific generation">
            Mock mode · built-in “{design.template.replace(/_/g, " ")}” template
          </span>
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 10px" }}>
        The repository had no source code, so Intent2Deploy is generating the project from scratch. Retrieval and
        existing-code analysis are skipped.
      </p>
      <div className="step-list">
        {steps.map((st) => (
          <div key={st.label} className={`step-item ${st.status}`}>
            <span className="dot" />
            <span>
              {st.label}
              {st.detail && <span style={{ color: "var(--text-faint)" }}> — {st.detail}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Requirements + architecture for a generated project. */
function GreenfieldDesignPanel({ workflow }: { workflow: Workflow }) {
  const design = parseDesign(workflow);
  if (!design) {
    return (
      <div className="empty-state">
        {workflow.state === "PLANNING" ? "Analyzing requirements and designing the architecture…" : "No design yet — generate the plan."}
      </div>
    );
  }
  return (
    <div>
      <p style={{ fontSize: 13.5, margin: "0 0 12px" }}>{design.summary}</p>
      <div className="grid grid-2">
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Requirements</div>
          <ul style={{ paddingLeft: 18, margin: "0 0 12px", fontSize: 12.5 }}>
            {design.requirements.map((r) => <li key={r}>{r}</li>)}
          </ul>
          {design.non_functional.length > 0 && (
            <>
              <div className="eyebrow" style={{ marginBottom: 6 }}>Non-functional</div>
              <ul style={{ paddingLeft: 18, margin: "0 0 12px", fontSize: 12.5, color: "var(--text-muted)" }}>
                {design.non_functional.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </>
          )}
        </div>
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>Architecture</div>
          <div style={{ fontSize: 12.5, marginBottom: 8 }}><strong>{design.stack}</strong></div>
          {design.components.map((c) => (
            <div key={c.name} style={{ fontSize: 12.5, marginBottom: 8 }}>
              <div style={{ fontWeight: 600 }}>{c.name}</div>
              <div style={{ color: "var(--text-muted)" }}>{c.responsibility}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 10px", marginTop: 2 }}>
                {c.files.map((f) => <code key={f} style={{ fontSize: 11 }}>{f}</code>)}
              </div>
            </div>
          ))}
          {design.run_command && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Run: <code>{design.run_command}</code> · Test: <code>{design.test_command}</code>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export function WorkflowDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const prevState = useRef<string | null>(null);
  const railRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [wf, ev, pl] = await Promise.all([
        api.getWorkflow(id),
        api.getEvents(id),
        api.getPipeline(id),
      ]);
      setWorkflow(wf);
      setEvents(ev.events);
      setPipeline(pl.stages);

      // Auto-select the active/awaiting stage on first load or state change
      if (prevState.current !== wf.state) {
        prevState.current = wf.state;
        const byState = STAGE_FOR_STATE[wf.state];
        // After commit, the pull request is the step waiting for a person: open it
        // rather than readiness/report while it is still open or unmerged.
        const prWaiting = ["COMMITTED", "CI_RUNNING", "COMPLETED"].includes(wf.state)
          ? pl.stages.find((s) => s.name === "GitHub / PR" && ["AWAITING_APPROVAL", "RUNNING", "PENDING"].includes(s.status))
          : undefined;
        const activeStage =
          prWaiting ??
          (byState ? pl.stages.find((s) => s.name === byState) : undefined) ??
          pl.stages.find((s) => s.status === "AWAITING_APPROVAL" || s.status === "RUNNING") ??
          pl.stages.find((s) => s.status === "FAILED" || s.status === "BLOCKED");
        if (activeStage) {
          setSelectedStage(activeStage.name);
        }
      }
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Scroll selected stage into view in the rail
  useEffect(() => {
    if (!railRef.current || !selectedStage) return;
    const btn = railRef.current.querySelector(`[data-stage="${selectedStage}"]`) as HTMLElement | null;
    if (!btn) return;
    // Scroll only the rail; scrollIntoView would also scroll the page sideways.
    const rail = railRef.current;
    const offset = btn.getBoundingClientRect().left - rail.getBoundingClientRect().left;
    rail.scrollTo({ left: rail.scrollLeft + offset - rail.clientWidth / 2 + btn.offsetWidth / 2, behavior: "smooth" });
  }, [selectedStage]);

  async function act<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      // Refresh on failure too: a failed step can still change the workflow
      // state (e.g. to FAILED), and stale state offers actions that no longer apply.
      await refresh();
      setBusy(false);
    }
  }

  if (!workflow) {
    return (
      <div>
        <h1 className="page-title">Workflow</h1>
        <div className="empty-state">{error || "Loading…"}</div>
      </div>
    );
  }

  const state = workflow.state;
  const nextAction = nextActionForState(state);
  const prStage = pipeline.find((s) => s.name === "GitHub / PR");
  const failureMessage = [...events].reverse().find((e) => e.event_type === "WORKFLOW_FAILED")?.message || error || "";
  const currentStageData = pipeline.find((s) => s.name === selectedStage) ?? pipeline[0] ?? null;

  // Compute progress: how many stages are PASSED or FAILED (not PENDING)
  const doneCount = pipeline.filter((s) => ["PASSED", "FAILED", "BLOCKED", "SKIPPED"].includes(s.status)).length;
  const progressPct = pipeline.length > 0 ? Math.round((doneCount / pipeline.length) * 100) : 0;

  return (
    <div>
      {/* Compact page header */}
      <div style={{ marginBottom: 14 }}>
        <h1 className="page-title" style={{ fontSize: 20, marginBottom: 2 }}>
          {(() => {
            const title = workflow.revision_note ? `Fix: ${workflow.revision_note}` : workflow.intent;
            return title.length > 80 ? title.slice(0, 80) + "…" : title;
          })()}
        </h1>
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <StatusBadge state={state} />
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
            {workflow.branch_name || "no branch"} · {workflow.repair_attempts} repair{workflow.repair_attempts !== 1 ? "s" : ""}
          </span>
          <div className="progress-bar-wrap" style={{ maxWidth: 120 }}>
            <div
              className={`progress-bar-fill${state === "FAILED" ? " danger" : state === "COMPLETED" ? " success" : ""}`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span style={{ fontSize: 11.5, color: "var(--text-faint)" }}>{progressPct}%</span>
          <button
            className="btn"
            style={{ marginLeft: "auto", padding: "3px 10px", fontSize: 12, color: "var(--danger)" }}
            disabled={busy}
            onClick={async () => {
              if (!window.confirm("Delete this workflow and its local workspace? Your repository and anything already on GitHub are not affected.")) return;
              try {
                await api.deleteWorkflow(id);
                navigate("/workflows");
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e));
              }
            }}
          >
            Delete workflow
          </button>
        </div>
      </div>

      <RevisionLinks workflow={workflow} />

      {workflow.project_mode === "greenfield" && <GreenfieldProgress workflow={workflow} pipeline={pipeline} busy={busy} />}

      {state === "FAILED" ? (
        <div className="callout callout-danger" style={{ marginBottom: 10 }}>
          <strong>Workflow failed.</strong>{" "}
          {failureMessage || "See the audit timeline for details."}
          {workflow.failed_from === "INPUT_REFUSED" ? (
            <div style={{ marginTop: 8 }}>
              This request was refused by a guardrail, so it can't be resumed. <Link to="/new-workflow">Start a new workflow</Link> with a different request.
            </div>
          ) : workflow.failed_from === "NO_CHANGES" ||
            (workflow.revision_of && /^(Mock mode can't make this change|The regenerated project is identical|Nothing to change)/.test(failureMessage)) ? (
            <NoChangesHelp workflow={workflow} busy={busy} act={act} />
          ) : (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--danger-soft-border)" }}>
              <div style={{ color: "var(--text)", marginBottom: 8 }}>
                <strong>Fixed the cause?</strong>{" "}
                {workflow.failed_from === "AWAITING_COMMIT_APPROVAL"
                  ? "Resume goes back to the commit approval step."
                  : "Resume re-reads the repository (re-downloading it from GitHub) and continues this workflow from the step that failed — it keeps your approved plan if the repository is unchanged, or prepares a fresh plan for approval if it changed."}
              </div>
              {error && !failureMessage.includes(error.slice(0, 60)) && <div style={{ marginBottom: 8 }}>{error}</div>}
              <div className="btn-row" style={{ marginTop: 0 }}>
                <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.resumeWorkflow(id))}>
                  {busy ? "Resuming…" : "Resume from here"}
                </button>
                <Link to="/new-workflow" className="btn">Start a new workflow instead</Link>
              </div>
            </div>
          )}
        </div>
      ) : (
        error && <div className="callout callout-danger" style={{ marginBottom: 10 }}>{error}</div>
      )}

      {/* Workflow Navigator */}
      <div className="wf-nav-wrap" style={{ marginBottom: 14 }}>
        <div className="wf-nav-header">
          <span className="wf-nav-meta">
            {pipeline.filter((s) => s.status === "PASSED").length}/{pipeline.length} stages complete
          </span>
          {AUTOMATIC_STEPS[state] ? (
            <button
              className="btn btn-primary"
              style={{ padding: "4px 12px" }}
              disabled={busy}
              onClick={() => act(() => AUTOMATIC_STEPS[state].run(id))}
            >
              {busy ? "Working…" : `Continue: ${AUTOMATIC_STEPS[state].label}`}
            </button>
          ) : nextAction ? (
            <button
              type="button"
              className={`wf-nav-action-hint${nextAction.tone === "success" ? " success" : ""}`}
              style={{ cursor: STAGE_FOR_STATE[state] ? "pointer" : "default" }}
              title={STAGE_FOR_STATE[state] ? `Go to ${STAGE_FOR_STATE[state]}` : undefined}
              onClick={() => STAGE_FOR_STATE[state] && setSelectedStage(STAGE_FOR_STATE[state])}
            >
              → {nextAction.label}
            </button>
          ) : state === "COMPLETED" && prStage && !["PASSED", "NOT_APPLICABLE"].includes(prStage.status) ? (
            // CI passed, but nothing is delivered until the pull request is merged.
            <button
              type="button"
              className="wf-nav-action-hint"
              style={{ cursor: "pointer" }}
              title="Go to GitHub / PR"
              onClick={() => setSelectedStage(prStage.name)}
            >
              → {prStage.output.startsWith("Merged into") ? "Check staging, then release it to main" : "Approve & merge the pull request"}
            </button>
          ) : state === "COMPLETED" ? (
            <span className="wf-nav-action-hint success">✓ Workflow complete</span>
          ) : null}
        </div>

        <div className="wf-stage-rail" ref={railRef}>
          {pipeline.map((s) => (
            <button
              key={s.name}
              data-stage={s.name}
              className={`wf-stage-btn${selectedStage === s.name ? " selected" : ""}`}
              onClick={() => setSelectedStage(s.name)}
              title={`${s.name}: ${statusLabel(s.status)}${s.output ? " — " + s.output.slice(0, 80) : ""}`}
            >
              <span className={`wf-stage-indicator ${statusClass(s.status)}`} />
              <span className="wf-stage-name">{STAGE_LABELS[s.name] ?? s.name}</span>
              <span className="wf-stage-status">{statusLabel(s.status)}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Stage detail panel */}
      {currentStageData && selectedStage && (
        <div className="stage-detail-panel">
          <div className="stage-detail-header">
            <div>
              <span className="stage-detail-title">{selectedStage}</span>
              {currentStageData.duration_ms != null && (
                <span style={{ fontSize: 11.5, color: "var(--text-faint)", marginLeft: 10 }}>
                  {currentStageData.duration_ms}ms
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StatusBadge state={currentStageData.status} />
              {currentStageData.approval_state && currentStageData.approval_state !== "pending" && (
                <span className="tag" style={{ fontSize: 11 }}>{currentStageData.approval_state}</span>
              )}
            </div>
          </div>

          <div className="stage-detail-body">
            <StagePanel
              stageName={selectedStage}
              stage={currentStageData}
              workflow={workflow}
              busy={busy}
              act={act}
              workflowId={id}
              events={events}
            />
          </div>
        </div>
      )}

      {/* Timeline — collapsed by default */}
      <details style={{ marginTop: 16 }}>
        <summary style={{ fontSize: 12.5, fontWeight: 600, cursor: "pointer", color: "var(--text-muted)", padding: "8px 0" }}>
          Audit timeline ({events.length} events)
        </summary>
        <div className="card" style={{ marginTop: 8 }}>
          <Timeline events={events} />
        </div>
      </details>
    </div>
  );
}
