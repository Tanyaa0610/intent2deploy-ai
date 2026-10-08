import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import type {
  AuditEventItem,
  FinalReport,
  GeneratedTestItem,
  PipelineStage,
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
import { Tbl, Expand } from "../components/DataDisplay";
import { PipelineStrip } from "../components/PipelineStrip";

type TabKey = "plan" | "repo" | "changes" | "tests" | "ci" | "report";

export function WorkflowDetailPage() {
  const { id = "" } = useParams();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
  const [tab, setTab] = useState<TabKey>("plan");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [wf, ev, pl] = await Promise.all([api.getWorkflow(id), api.getEvents(id), api.getPipeline(id)]);
      setWorkflow(wf);
      setEvents(ev.events);
      setPipeline(pl.stages);
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

      <div className="card">
        <div className="card-title">Progression</div>
        <PipelineStrip stages={pipeline} />
      </div>

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
          <div className="card-title">Actions</div>
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

      {error && <div className="callout callout-danger">{error}</div>}

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
        <div className="card-title">Timeline</div>
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
      <div className="card-title">Summary</div>
      <p>{plan.summary}</p>

      <hr className="divider" />
      <div className="card-title">Assumptions</div>
      <ul>{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Acceptance criteria</div>
      <ul>{plan.acceptance_criteria.map((a, i) => <li key={i}>{a}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Implementation steps</div>
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

      <div className="card-title" style={{ marginTop: 16 }}>Affected files</div>
      {plan.files_likely_to_change.map((f) => <code key={f} style={{ display: "block" }}>{f}</code>)}

      <div className="card-title" style={{ marginTop: 16 }}>Test strategy</div>
      <ul>{plan.test_strategy.map((t, i) => <li key={i}>{t}</li>)}</ul>

      <div className="card-title" style={{ marginTop: 16 }}>Risks</div>
      <ul>{plan.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>

      {plan.approved === null && workflow.state === "AWAITING_PLAN_APPROVAL" && (
        <>
          <hr className="divider" />
          <div className="card-title">Human approval required</div>
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
          <span className={`status ${plan.approved ? "success" : "danger"}`}>
            <span className="dot" />
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
        <div className="card-title">Retrieval evidence for this plan</div>
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
              <span className="tag accent">{c.operation} · confidence {c.confidence.toFixed(2)}</span>
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
          <hr className="divider" />
          <div className="card-title">Human approval required</div>
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

  const refreshTests = useCallback(() => {
    api.getTests(id).then((r) => setTests(r.tests));
  }, [id]);

  useEffect(() => {
    refreshTests();
    api.getValidation(id).then((r) => setValidation(r.results));
  }, [id, workflow.state, refreshTests]);

  return (
    <>
      <div className="card">
        <div className="card-title">Generated tests</div>
        {workflow.state === "TESTS_GENERATING" && tests.length === 0 && (
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => act(() => api.generateTests(id)).then(refreshTests)}
          >
            Generate Tests
          </button>
        )}
        {tests.length === 0 ? (
          <div className="empty-state">No tests generated yet.</div>
        ) : (
          tests.map((t) => (
            <div key={t.id} style={{ marginBottom: 14 }}>
              <code style={{ fontWeight: 700 }}>{t.file}</code> <span className="tag">{t.category}</span>
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
        <div className="card-title">Validation results</div>
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
            <span className="status success">
              <span className="dot" />
              Validation passed — see CI/CD tab to commit
            </span>
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
      <div className="card-title">Failure analysis / repair loop</div>
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
      <div className="card-title">Local validation</div>
      <p style={{ fontSize: 13 }}>See the Tests tab for the sandboxed local validation pipeline results.</p>

      {workflow.state === "AWAITING_COMMIT_APPROVAL" && (
        <>
          <div className="card-title" style={{ marginTop: 16 }}>External action: commit</div>
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
              <span className="tag accent">{ci.provider.toUpperCase()}</span>{" "}
              <span className="tag">{ci.status}</span>
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

  const ws = report.workflow_summary;
  const timeline = report.timeline ?? [];
  const rag = report.repository_rag;
  const arch = report.architecture_analysis;
  const archOk = arch && !("error" in arch);
  const plan = report.engineering_plan;
  const pa = report.plan_approval;
  const cg = report.code_generation;
  const ca = report.change_approval;
  const tg = report.test_generation;
  const rt = report.resilience_testing;
  const cs = report.chaos_simulation;
  const gf = report.guardrails_full;
  const val = report.validation;
  const ar = report.ai_repair;
  const prf = report.production_readiness_full;
  const ci = report.ci_cd;
  const gh = report.github_pr;
  const fo = report.final_outcome;
  const ri = report.repository_indexing;
  const iu = report.intent_understanding;

  return (
    <div className="card">
      <div className="card-title" style={{ fontSize: 16 }}>FINAL REPORT</div>
      <div className="btn-row" style={{ marginTop: 8, marginBottom: 16 }}>
        <a className="btn btn-primary" href={api.getReportJsonUrl(id)} target="_blank" rel="noreferrer">
          Download JSON Report
        </a>
        <a className="btn" href={api.getReportMarkdownUrl(id)} target="_blank" rel="noreferrer">
          Download Markdown Report
        </a>
      </div>

      {/* 1. Executive Summary */}
      <div className="card-title">Executive summary</div>
      <p>{report.executive_summary}</p>
      <StatusBadge state={report.final_status} /> · Final validation: {report.final_validation || "—"} · Repairs:{" "}
      {report.repair_attempts} · Human interventions: {report.human_intervention_count}

      {/* Overall metrics */}
      {ws && (
        <>
          <div className="card-title" style={{ marginTop: 16 }}>Overall metrics</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 18px", fontSize: 12.5 }}>
            <span>Total time: {ws.total_duration_ms ?? "—"}ms</span>
            <span>Human interventions: {ws.human_intervention_count}</span>
            <span>Repair attempts: {ws.repair_attempts}</span>
            <span>Production readiness: {ws.production_readiness_decision}</span>
            <span>Requested change succeeded: {String(ws.requested_change_succeeded)}</span>
          </div>
        </>
      )}

      <hr className="divider" />

      {/* 23. Complete Workflow Timeline */}
      <div className="card-title">Complete workflow timeline</div>
      <Tbl
        headers={["Stage", "Status", "Timestamp / Duration", "Evidence", "Outcome"]}
        rows={timeline.map((s) => [
          s.name,
          s.status,
          s.timestamp ?? (s.duration_ms != null ? `${s.duration_ms}ms` : "—"),
          s.evidence.join("; "),
          s.output,
        ])}
      />

      <hr className="divider" />
      <div className="card-title">Stage details</div>

      <Expand title="2. Developer Intent">
        <p style={{ fontSize: 13 }}>{report.developer_intent?.text ?? report.intent}</p>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          Submitted: {report.developer_intent?.submitted_at ?? "—"} · Base branch: {report.developer_intent?.base_branch ?? "—"} ·
          Environment: {report.developer_intent?.environment ?? "—"}
        </p>
      </Expand>

      <Expand title="3. Intent Understanding">
        <p style={{ fontSize: 13 }}>Classified category: <code>{iu?.classified_category ?? "Not recorded"}</code></p>
        <p style={{ fontSize: 13 }}>Interpreted problem: {iu?.interpreted_problem ?? "Not recorded"}</p>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{iu?.note}</p>
      </Expand>

      <Expand title="4-5. Production Context & Repository Indexing">
        <p style={{ fontSize: 13 }}>Repository: {report.production_context?.repository_source ?? report.repository}</p>
        <p style={{ fontSize: 13 }}>Environment: {report.production_context?.environment ?? "—"}</p>
        <p style={{ fontSize: 13 }}>
          Files indexed: {ri?.files_indexed ?? "—"} · Chunks created: {ri?.chunks_created ?? "—"} · Vector store: {ri?.vector_store ?? "—"} ·
          Indexing duration: {ri?.indexing_duration_ms ?? "—"}ms
        </p>
      </Expand>

      <Expand title={`6. Repository RAG & Retrieved Evidence (${rag?.evidence.length ?? report.evidence.length})`}>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Query (developer intent): {rag?.query ?? report.intent}</p>
        <Tbl
          headers={["File", "Method", "Chunk type", "Reason"]}
          rows={(rag?.evidence ?? []).map((e) => [e.file, e.retrieval_method, e.chunk_type, e.reason])}
        />
      </Expand>

      <Expand title="7. Architecture Analysis">
        {archOk && "components" in arch! ? (
          <>
            <p style={{ fontSize: 12.5 }}>
              Total files: {arch.total_files} · Functions: {arch.total_functions} · Classes: {arch.total_classes} ·
              External dependencies: {arch.external_dependencies.join(", ") || "none detected"}
            </p>
            <Tbl headers={["Component", "Path", "Files", "Functions", "Classes"]} rows={arch.components.map((c) => [c.name, c.path, c.files.length, c.functions, c.classes])} />
          </>
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Not recorded.</p>
        )}
      </Expand>

      <Expand title={`8. Risk Analysis (${report.risk_analysis?.length ?? report.risks.length})`}>
        <Tbl
          headers={["Risk", "Category", "Severity", "Impact", "Existing Mitigation", "Recommended Mitigation", "Status"]}
          rows={(report.risk_analysis ?? []).map((r) => [r.title, r.category, r.severity, r.blast_radius, r.existing_mitigation, r.recommended_mitigation, r.status])}
        />
      </Expand>

      <Expand title="9. Engineering Plan">
        {plan ? (
          <>
            <p style={{ fontSize: 13 }}>{plan.summary}</p>
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>Assumptions</p>
            <ul>{plan.assumptions.map((a, i) => <li key={i} style={{ fontSize: 12.5 }}>{a}</li>)}</ul>
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>Acceptance criteria</p>
            <ul>{plan.acceptance_criteria.map((a, i) => <li key={i} style={{ fontSize: 12.5 }}>{a}</li>)}</ul>
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>Implementation steps</p>
            <Tbl headers={["ID", "Description", "Files"]} rows={plan.steps.map((s) => [s.id, s.description, s.files?.join(", ") ?? ""])} />
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>Proposed files</p>
            <p style={{ fontSize: 12.5 }}>{plan.files_likely_to_change.join(", ") || "Not recorded"}</p>
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>Test strategy</p>
            <ul>{plan.test_strategy.map((t, i) => <li key={i} style={{ fontSize: 12.5 }}>{t}</li>)}</ul>
            <p style={{ fontSize: 12.5 }}>Rollback strategy: {plan.rollback_strategy} · Constraints: {plan.constraints}</p>
          </>
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Not recorded.</p>
        )}
      </Expand>

      <Expand title="10. Human Plan Approval">
        <p style={{ fontSize: 13 }}>Status: {pa?.status ?? "Not recorded"} · Timestamp: {pa?.timestamp ?? "—"}</p>
        <p style={{ fontSize: 13 }}>Comment: {pa?.comment || "—"}</p>
      </Expand>

      <Expand title={`11. Code Generation (${cg?.applied ? "applied" : "proposed only"})`}>
        {(cg?.applied ? cg.files_modified : cg?.files_proposed_not_applied ?? []).map((c, i) => (
          <div key={i} style={{ marginBottom: 16 }}>
            <code style={{ fontWeight: 700 }}>{c.file}</code> <span className="tag accent">{c.operation} · confidence {c.confidence.toFixed(2)}</span>
            <p style={{ fontSize: 12.5 }}>{c.reason}</p>
            <DiffViewer patch={c.patch} />
          </div>
        ))}
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          Retrieved/read-only files (not modified): {cg?.retrieved_read_only_files.join(", ") || "none"}
        </p>
      </Expand>

      <Expand title="12. Human Change Approval">
        <p style={{ fontSize: 13 }}>Status: {ca?.status ?? "Not recorded"} · Timestamp: {ca?.timestamp ?? "—"}</p>
        <p style={{ fontSize: 13 }}>Comment: {ca?.comment || "—"}</p>
      </Expand>

      <Expand title={`13. Test Generation (${tg?.count ?? report.tests.length})`}>
        <p style={{ fontSize: 12.5 }}>Generation duration: {tg?.generation_duration_ms ?? "—"}ms</p>
        {(tg?.tests ?? []).map((t, i) => (
          <div key={i} style={{ marginBottom: 14 }}>
            <code style={{ fontWeight: 700 }}>{t.file}</code> <span className="tag">{t.category}</span>
            <p style={{ fontSize: 12.5 }}>{t.rationale}</p>
            <p style={{ fontSize: 12, color: "var(--text-muted)" }}>Functions: {t.test_functions.join(", ") || "—"}</p>
            <p style={{ fontSize: 11.5, color: "var(--text-faint)" }}>{t.execution_note}</p>
          </div>
        ))}
      </Expand>

      <Expand title="14. Resilience Testing">
        <p style={{ fontSize: 12.5 }}>Status: {rt?.status ?? "Not recorded"}</p>
        <Tbl
          headers={["Scenario", "Failure/Condition", "Expected Behavior", "Actual Result", "Status", "Evidence"]}
          rows={(rt?.scenarios ?? []).map((s) => [s.scenario, s.failure_injected, s.expected_behavior, s.actual_behavior, s.result, JSON.stringify(s.evidence)])}
        />
      </Expand>

      <Expand title="15. Chaos Simulation">
        <p style={{ fontSize: 12.5 }}>
          Status: {cs?.status ?? "Not recorded"} ({cs?.pass_count ?? 0}/{cs?.applicable_count ?? 0} applicable passed, {cs?.total_count ?? 0} total)
        </p>
        <Tbl
          headers={["Scenario ID", "Scenario", "Failure Injected", "Expected", "Actual", "Result", "Evidence"]}
          rows={(cs?.scenarios ?? []).map((s) => [s.experiment_id, s.scenario, s.failure_injected, s.expected_behavior, s.actual_behavior, s.result, JSON.stringify(s.evidence)])}
        />
        {cs?.limitations.map((l, i) => <p key={i} style={{ fontSize: 12, color: "var(--text-muted)" }}>Limitation: {l}</p>)}
      </Expand>

      <Expand title="16. Guardrails & Safety">
        <p style={{ fontSize: 12.5 }}>
          {gf?.total ?? report.guardrails.total} check(s) — {gf?.passed ?? report.guardrails.passed} passed, {gf?.warnings ?? report.guardrails.warnings} warnings,{" "}
          {gf?.blocked ?? report.guardrails.blocked} blocked, {gf?.failed ?? report.guardrails.failed} failed, {gf?.not_applicable ?? 0} not applicable.
          Approval-required: {gf?.approval_required ?? 0}. Altered execution: {String(gf?.altered_execution ?? false)}.
        </p>
        {Object.keys((gf?.by_category ?? report.guardrails.by_category)).length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", marginBottom: 8 }}>
            {Object.entries(gf?.by_category ?? report.guardrails.by_category).map(([cat, n]) => (
              <span key={cat} className="tag">{cat}: {n}</span>
            ))}
          </div>
        )}
        <Tbl
          headers={["Category", "Guardrail", "Result", "Action", "Evidence"]}
          rows={(gf?.checks ?? []).map((g) => [g.category, `[${g.guardrail_id}] ${g.name}`, g.status, g.action, JSON.stringify(g.evidence)])}
        />
      </Expand>

      <Expand title="17. Validation">
        <p style={{ fontSize: 12.5 }}>Final result: {val?.final_result ?? report.final_validation ?? "Not recorded"} · Repair triggered: {String(val?.repair_triggered ?? false)}</p>
        {(val?.runs ?? []).map((v, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            <p style={{ fontSize: 12.5, fontWeight: 700 }}>[{v.stage}] attempt {v.attempt} — {v.status}</p>
            <p style={{ fontSize: 12, color: "var(--text-muted)" }}>Command: <code>{v.command}</code> · Exit code: {v.exit_code ?? "—"} · Duration: {v.duration_ms}ms</p>
            {v.stderr && <pre className="mono-block" style={{ fontSize: 11 }}>{v.stderr.slice(0, 2000)}</pre>}
          </div>
        ))}
      </Expand>

      <Expand title="18. AI Repair">
        <p style={{ fontSize: 13 }}>Triggered: {String(ar?.triggered ?? false)}</p>
        {ar?.triggered ? (
          <Tbl headers={["Attempt", "Diagnosis", "Approved", "Result"]} rows={ar.attempts.map((a) => [a.attempt_number, a.diagnosis, String(a.approved), a.result])} />
        ) : (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{ar?.reason}</p>
        )}
      </Expand>

      <Expand title="19. Production Readiness" defaultOpen>
        {prf ? (
          <>
            <StatusBadge state={prf.decision} />
            <ul style={{ marginTop: 8 }}>{prf.reasons.map((r, i) => <li key={i} style={{ fontSize: 13 }}>{r}</li>)}</ul>
            <Tbl headers={["Check", "Result"]} rows={Object.entries(prf.checklist)} />
          </>
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Not yet assessed for this workflow.</p>
        )}
      </Expand>

      <Expand title="20. CI/CD">
        <p style={{ fontSize: 13 }}>Applicable: {String(ci?.applicable ?? false)} · Status: {ci?.status ?? "Not recorded"}</p>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{ci?.detail}</p>
      </Expand>

      <Expand title="21. GitHub / Pull Request">
        <p style={{ fontSize: 13 }}>Branch: {gh?.branch ?? "Not recorded"}</p>
        <p style={{ fontSize: 13 }}>Commit: {gh?.commit?.status ?? "Not recorded"} · Push: {gh?.push?.status ?? "Not recorded"} · PR: {gh?.pull_request?.status ?? "Not recorded"}</p>
        {gh?.note && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{gh.note}</p>}
      </Expand>

      <hr className="divider" />

      <Expand title="24. File-Level Change Summary" defaultOpen>
        <Tbl
          headers={["File", "Action", "Reason", "Evidence", "Validation"]}
          rows={(report.file_change_summary ?? []).map((f) => [f.file, f.action, f.reason, f.evidence, f.validation])}
        />
      </Expand>

      <Expand title="25. Test Evidence">
        <Tbl headers={["Test", "Purpose", "Result", "Evidence"]} rows={(report.test_evidence ?? []).map((t) => [t.test, t.purpose, t.result, t.evidence])} />
      </Expand>

      <Expand title="26. Guardrail Evidence">
        <Tbl headers={["Category", "Check", "Result", "Action", "Evidence"]} rows={(report.guardrail_evidence ?? []).map((g) => [g.category, g.check, g.result, g.action, JSON.stringify(g.evidence)])} />
      </Expand>

      <Expand title="27. Risk & Readiness Summary" defaultOpen>
        <Tbl
          headers={["Risk", "Severity", "Detection", "Mitigation", "Final Status"]}
          rows={(report.risk_readiness_summary ?? []).map((r) => [r.risk, r.severity, r.detection, r.mitigation, r.final_status])}
        />
      </Expand>

      <Expand title="28. Human Approval Audit" defaultOpen>
        <Tbl
          headers={["Checkpoint", "Timestamp", "Decision", "Comment", "Resulting Action"]}
          rows={(report.approvals ?? []).map((a) => [a.checkpoint, a.timestamp, a.decision, a.comment, a.resulting_action])}
        />
      </Expand>

      <hr className="divider" />

      <div className="card-title">29. Final outcome</div>
      {fo && (
        <>
          <p style={{ fontSize: 13 }}>
            Requested change succeeded: <strong>{String(fo.requested_change_succeeded)}</strong> · Final validation: {fo.final_validation} · Final readiness: {fo.final_readiness_decision}
          </p>
          <p style={{ fontSize: 13 }}>Files changed: {fo.files_changed.join(", ") || "none"}</p>
          {fo.remaining_open_risks.length > 0 && (
            <>
              <p style={{ fontSize: 12.5, fontWeight: 700, marginTop: 8 }}>Remaining open risks</p>
              <ul>{fo.remaining_open_risks.map((r, i) => <li key={i} style={{ fontSize: 12.5 }}>[{r.severity}] {r.title}</li>)}</ul>
            </>
          )}
        </>
      )}

      <div className="card-title" style={{ marginTop: 16 }}>30. Limitations</div>
      {(report.limitations ?? []).length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--text-faint)" }}>None observed.</p>
      ) : (
        <ul>
          {(report.limitations ?? []).map((l, i) => (
            <li key={i} style={{ fontSize: 12.5 }}><strong>[{l.category}]</strong> {l.note}</li>
          ))}
        </ul>
      )}

      <hr className="divider" />
      <div className="card-title">Evidence classification</div>
      <table>
        <thead><tr><th>Label</th><th>Item</th><th>Note</th></tr></thead>
        <tbody>
          {report.evidence_classification.map((e, i) => (
            <tr key={i}>
              <td><StatusBadge state={e.classification} /></td>
              <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{e.item}</td>
              <td style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{e.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
