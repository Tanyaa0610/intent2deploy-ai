import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import type {
  AuditEventItem,
  FinalReport,
  GeneratedTestItem,
  PlanDetail,
  ProposedChangeItem,
  RepairAttemptItem,
  RetrievalEvidenceItem,
  ValidationResultItem,
  Workflow,
} from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { EvidencePanel } from "../components/EvidencePanel";
import { DiffViewer } from "../components/DiffViewer";
import { ApprovalControls } from "../components/ApprovalControls";

type TabKey = "plan" | "repo" | "changes" | "tests" | "ci" | "report";

export function WorkflowDetailPage() {
  const { id = "" } = useParams();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [tab, setTab] = useState<TabKey>("plan");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [wf, ev] = await Promise.all([api.getWorkflow(id), api.getEvents(id)]);
      setWorkflow(wf);
      setEvents(ev.events);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function act<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!workflow) {
    return <div className="empty-state">{error || "Loading workflow…"}</div>;
  }

  const state = workflow.state;

  return (
    <div>
      <h1 className="page-title">Workflow</h1>
      <p className="page-subtitle">{workflow.intent}</p>

      <div className="grid grid-3">
        <div className="card">
          <div className="card-title">Status</div>
          <StatusBadge state={state} />
          <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--text-muted)" }}>
            Branch: {workflow.branch_name || "—"}
            <br />
            Human interventions: {workflow.human_intervention_count}
            <br />
            Repair attempts: {workflow.repair_attempts}
          </div>
        </div>
        <div className="card">
          <div className="card-title">Pipeline Actions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {state === "CREATED" && (
              <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.runIndexing(id))}>
                Index Repository
              </button>
            )}
            {state === "INDEXED" && (
              <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.runPlanning(id))}>
                Generate Plan
              </button>
            )}
            {state === "VALIDATION_FAILED" && workflow.repair_attempts < 2 && (
              <button className="btn" disabled={busy} onClick={() => act(() => api.proposeRepair(id))}>
                Diagnose &amp; Propose Repair
              </button>
            )}
            {state === "COMMITTED" && (
              <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.completeWorkflow(id))}>
                Finalize Workflow
              </button>
            )}
            {!["CREATED", "INDEXED", "VALIDATION_FAILED", "COMMITTED"].includes(state) && (
              <span style={{ fontSize: 12.5, color: "var(--text-faint)" }}>
                Use the tab below matching the current stage to continue.
              </span>
            )}
          </div>
        </div>
        <div className="card">
          <div className="card-title">Timing</div>
          <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            Indexing: {workflow.indexing_ms ?? "—"}ms
            <br />
            Planning: {workflow.planning_ms ?? "—"}ms
            <br />
            Codegen: {workflow.codegen_ms ?? "—"}ms
            <br />
            Test gen: {workflow.testgen_ms ?? "—"}ms
            <br />
            Validation: {workflow.validation_ms ?? "—"}ms
          </div>
        </div>
      </div>

      {error && (
        <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
          {error}
        </div>
      )}

      <div className="tabs">
        {(["plan", "repo", "changes", "tests", "ci", "report"] as TabKey[]).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {{ plan: "Plan", repo: "Repository Intelligence", changes: "Proposed Changes", tests: "Tests", ci: "CI/CD", report: "Final Report" }[t]}
          </button>
        ))}
      </div>

      {tab === "plan" && <PlanTab id={id} workflow={workflow} busy={busy} act={act} />}
      {tab === "repo" && <RepoTab workflow={workflow} />}
      {tab === "changes" && <ChangesTab id={id} workflow={workflow} busy={busy} act={act} />}
      {tab === "tests" && <TestsTab id={id} workflow={workflow} busy={busy} act={act} />}
      {tab === "ci" && <CITab id={id} workflow={workflow} busy={busy} act={act} />}
      {tab === "report" && <ReportTab id={id} />}

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-title">Workflow Timeline</div>
        <Timeline events={events} />
      </div>
    </div>
  );
}

function PlanTab({
  id,
  workflow,
  busy,
  act,
}: {
  id: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    api.getPlan(id).then(setPlan).catch((e) => setLoadErr(String(e)));
  }, [id, workflow.state]);

  if (!plan) return <div className="empty-state">{loadErr || "No plan generated yet."}</div>;

  return (
    <div className="card">
      <div className="card-title">Interpreted Requirement</div>
      <p>{plan.summary}</p>

      <div className="card-title" style={{ marginTop: 16 }}>Assumptions</div>
      <ul>{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Acceptance Criteria</div>
      <ul>{plan.acceptance_criteria.map((a, i) => <li key={i}>{a}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Implementation Steps</div>
      <table>
        <thead><tr><th>ID</th><th>Description</th><th>Files</th></tr></thead>
        <tbody>
          {plan.steps.map((s) => (
            <tr key={s.id}>
              <td>{s.id}</td>
              <td>{s.description}</td>
              <td>{s.files.map((f) => <code key={f} style={{ display: "block" }}>{f}</code>)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="card-title" style={{ marginTop: 16 }}>Files Likely to Change</div>
      {plan.files_likely_to_change.map((f) => <code key={f} style={{ display: "block" }}>{f}</code>)}

      <div className="card-title" style={{ marginTop: 16 }}>Test Strategy</div>
      <ul>{plan.test_strategy.map((t, i) => <li key={i}>{t}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Risks</div>
      <ul>{plan.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>

      {plan.approved === null && workflow.state === "AWAITING_PLAN_APPROVAL" && (
        <>
          <div className="card-title" style={{ marginTop: 20 }}>Human Approval Required</div>
          <ApprovalControls
            disabled={busy}
            approveLabel="Approve Plan"
            rejectLabel="Reject / Request Revision"
            onApprove={(comment) => act(() => api.approvePlan(id, true, comment))}
            onReject={(comment) => act(() => api.approvePlan(id, false, comment))}
          />
        </>
      )}
      {plan.approved !== null && (
        <div style={{ marginTop: 12 }}>
          <span className={`badge ${plan.approved ? "badge-success" : "badge-danger"}`}>
            {plan.approved ? "Plan approved" : "Plan rejected"}
          </span>
        </div>
      )}
    </div>
  );
}

function RepoTab({ workflow }: { workflow: Workflow }) {
  const [evidence, setEvidence] = useState<RetrievalEvidenceItem[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ answer: string; cited_files: string[] } | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    api.getEvidence(workflow.id).then((r) => setEvidence(r.evidence));
  }, [workflow.id, workflow.state]);

  async function ask() {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const result = await api.askRepository(workflow.repository_id, question);
      setAnswer(result);
    } finally {
      setAsking(false);
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-title">Ask about this repository…</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Where is authentication handled?" />
          <button className="btn btn-primary" disabled={asking} onClick={ask}>
            {asking ? "Thinking…" : "Ask"}
          </button>
        </div>
        {answer && (
          <div style={{ marginTop: 12 }}>
            <p>{answer.answer}</p>
            <div style={{ fontSize: 12, color: "var(--text-faint)" }}>
              Cited: {answer.cited_files.join(", ") || "none"}
            </div>
          </div>
        )}
      </div>
      <div className="card">
        <div className="card-title">Retrieval Evidence for This Workflow's Plan</div>
        <EvidencePanel evidence={evidence} />
      </div>
    </>
  );
}

function ChangesTab({
  id,
  workflow,
  busy,
  act,
}: {
  id: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [changes, setChanges] = useState<ProposedChangeItem[]>([]);
  const [approval, setApproval] = useState<boolean | null>(null);

  useEffect(() => {
    api.getChanges(id).then((r) => setChanges(r.changes));
  }, [id, workflow.state]);

  const canGenerate = workflow.state === "CHANGES_GENERATING";
  const canApprove = workflow.state === "AWAITING_CHANGE_APPROVAL" && approval === null;

  return (
    <div className="card">
      {canGenerate && (
        <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.generateChanges(id))}>
          Generate Change Proposal
        </button>
      )}
      {changes.length === 0 ? (
        <div className="empty-state">No changes proposed yet.</div>
      ) : (
        changes.map((c) => (
          <div key={c.id} style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <code style={{ fontWeight: 700 }}>{c.file}</code>
              <span className="badge badge-accent">{c.operation} · confidence {c.confidence.toFixed(2)}</span>
            </div>
            <p style={{ fontSize: 13 }}>{c.reason}</p>
            {c.risks.length > 0 && (
              <ul style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                {c.risks.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
            <DiffViewer patch={c.patch} />
          </div>
        ))
      )}
      {canApprove && (
        <>
          <div className="card-title" style={{ marginTop: 20 }}>Human Approval Required</div>
          <ApprovalControls
            disabled={busy}
            approveLabel="Approve Changes"
            rejectLabel="Reject Changes"
            onApprove={(comment) => act(() => api.approveChanges(id, true, comment)).then(() => setApproval(true))}
            onReject={(comment) => act(() => api.approveChanges(id, false, comment)).then(() => setApproval(false))}
          />
        </>
      )}
    </div>
  );
}

function TestsTab({
  id,
  workflow,
  busy,
  act,
}: {
  id: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [tests, setTests] = useState<GeneratedTestItem[]>([]);
  const [validation, setValidation] = useState<ValidationResultItem[]>([]);

  useEffect(() => {
    api.getTests(id).then((r) => setTests(r.tests));
    api.getValidation(id).then((r) => setValidation(r.results));
  }, [id, workflow.state]);

  return (
    <>
      <div className="card">
        <div className="card-title">Generated Tests</div>
        {workflow.state === "TESTS_GENERATING" && tests.length === 0 && (
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.generateTests(id))}>
            Generate Tests
          </button>
        )}
        {tests.length === 0 ? (
          <div className="empty-state">No tests generated yet.</div>
        ) : (
          tests.map((t) => (
            <div key={t.id} style={{ marginBottom: 14 }}>
              <code style={{ fontWeight: 700 }}>{t.file}</code> <span className="badge badge-neutral">{t.category}</span>
              <p style={{ fontSize: 13 }}>{t.rationale}</p>
              <pre className="mono-block">{t.content}</pre>
            </div>
          ))
        )}
        {workflow.state === "TESTS_GENERATING" && tests.length > 0 && (
          <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.runValidation(id))}>
            Run Validation
          </button>
        )}
      </div>
      <div className="card">
        <div className="card-title">Validation Results</div>
        {validation.length === 0 ? (
          <div className="empty-state">No validation runs yet.</div>
        ) : (
          <table>
            <thead><tr><th>Stage</th><th>Status</th><th>Attempt</th><th>Duration</th></tr></thead>
            <tbody>
              {validation.map((v, i) => (
                <tr key={i}>
                  <td>{v.stage}</td>
                  <td><StatusBadge state={v.status} /></td>
                  <td>{v.attempt}</td>
                  <td>{v.duration_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {validation.some((v) => v.status !== "passed") && (
          <div style={{ marginTop: 10 }}>
            {validation
              .filter((v) => v.status !== "passed")
              .map((v, i) => (
                <pre key={i} className="mono-block">{`[${v.stage}]\n${v.stdout}\n${v.stderr}`}</pre>
              ))}
          </div>
        )}
        {workflow.state === "VALIDATION_FAILED" && <RepairPanel id={id} workflow={workflow} busy={busy} act={act} />}
        {workflow.state === "AWAITING_COMMIT_APPROVAL" && (
          <div style={{ marginTop: 12 }}>
            <span className="badge badge-success">Validation passed — see CI/CD tab to commit</span>
          </div>
        )}
      </div>
    </>
  );
}

function RepairPanel({
  id,
  workflow,
  busy,
  act,
}: {
  id: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [repairs, setRepairs] = useState<RepairAttemptItem[]>([]);

  useEffect(() => {
    api.getRepairs(id).then((r) => setRepairs(r.repairs));
  }, [id, workflow.state, workflow.repair_attempts]);

  const pending = repairs.find((r) => r.approved === null);

  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
      <div className="card-title">Failure Analysis / Repair Loop</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
        Repair attempts so far: {workflow.repair_attempts} / 2 (MAX_REPAIR_ATTEMPTS)
      </p>
      {repairs.map((r) => (
        <div key={r.id} style={{ marginBottom: 12 }}>
          <strong>Attempt {r.attempt_number}</strong> — {r.result}
          <p style={{ fontSize: 13 }}>{r.diagnosis}</p>
          {r.repair_patch && <DiffViewer patch={r.repair_patch} />}
        </div>
      ))}
      {pending && (
        <ApprovalControls
          disabled={busy}
          approveLabel="Apply Repair"
          rejectLabel="Discard Repair"
          onApprove={() => act(() => api.approveRepair(id, pending.id, true))}
          onReject={() => act(() => api.approveRepair(id, pending.id, false))}
        />
      )}
      {!pending && workflow.repair_attempts < 2 && (
        <button className="btn" disabled={busy} onClick={() => act(() => api.proposeRepair(id))}>
          Diagnose &amp; Propose Repair
        </button>
      )}
    </div>
  );
}

function CITab({
  id,
  workflow,
  busy,
  act,
}: {
  id: string;
  workflow: Workflow;
  busy: boolean;
  act: <T>(fn: () => Promise<T>) => Promise<void>;
}) {
  const [ci, setCi] = useState<{ provider: string; status: string; detail: string; url: string } | null>(null);

  return (
    <div className="card">
      <div className="card-title">Local Validation</div>
      <p style={{ fontSize: 13 }}>See the Tests tab for the sandboxed local validation pipeline results.</p>

      {workflow.state === "AWAITING_COMMIT_APPROVAL" && (
        <>
          <div className="card-title" style={{ marginTop: 16 }}>External Action: Commit</div>
          <ApprovalControls
            disabled={busy}
            approveLabel="Approve Commit"
            rejectLabel="Abandon Workflow"
            onApprove={(comment) => act(() => api.approveCommit(id, true, comment))}
            onReject={(comment) => act(() => api.approveCommit(id, false, comment))}
          />
        </>
      )}

      {workflow.state === "COMMITTED" && (
        <>
          <div className="card-title" style={{ marginTop: 16 }}>GitHub Actions CI/CD</div>
          <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            Requires GITHUB_TOKEN/GITHUB_OWNER/GITHUB_REPO to be configured; otherwise only LOCAL VALIDATION is
            available and is clearly labeled as such.
          </p>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              act(async () => {
                const result = await api.getCIStatus(id);
                setCi(result);
              })
            }
          >
            Check GitHub Actions Status
          </button>
          {ci && (
            <div style={{ marginTop: 10 }}>
              <span className="badge badge-accent">{ci.provider.toUpperCase()}</span>{" "}
              <span className="badge badge-neutral">{ci.status}</span>
              <p style={{ fontSize: 12.5 }}>{ci.detail}</p>
              {ci.url && <a href={ci.url} target="_blank" rel="noreferrer">{ci.url}</a>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ReportTab({ id }: { id: string }) {
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getReport(id).then(setReport).catch((e) => setError(String(e)));
  }, [id]);

  if (!report) return <div className="empty-state">{error || "Loading report…"}</div>;

  function downloadJson() {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}-report.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="card">
      <div className="btn-row" style={{ marginTop: 0, marginBottom: 16 }}>
        <button className="btn" onClick={downloadJson}>Export JSON</button>
        <a className="btn" href={api.getReportMarkdownUrl(id)} target="_blank" rel="noreferrer">
          Export Markdown
        </a>
      </div>

      <div className="card-title">Executive Summary</div>
      <p>{report.executive_summary}</p>

      <div className="card-title" style={{ marginTop: 16 }}>Outcome</div>
      <StatusBadge state={report.final_status} /> · Final validation: {report.final_validation || "—"} · Repairs:{" "}
      {report.repair_attempts} · Human interventions: {report.human_intervention_count}

      <div className="card-title" style={{ marginTop: 16 }}>Changes</div>
      <ul>
        {report.changes.map((c, i) => (
          <li key={i}><code>{c.file}</code> ({c.operation}, confidence {c.confidence}) — {c.reason}</li>
        ))}
      </ul>

      <div className="card-title" style={{ marginTop: 16 }}>Tests</div>
      <ul>
        {report.tests.map((t, i) => (
          <li key={i}><code>{t.file}</code> [{t.category}] — {t.rationale}</li>
        ))}
      </ul>

      <div className="card-title" style={{ marginTop: 16 }}>Git Operations</div>
      <ul>
        {report.git_operations.map((g, i) => (
          <li key={i}>{g.operation}: {g.detail}</li>
        ))}
      </ul>
    </div>
  );
}
