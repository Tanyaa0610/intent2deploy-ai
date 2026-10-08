import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { ComparisonMetricRow, EvaluationCategoryKey, EvaluationCategoryResult, ExperimentComparison, MetricStatusEntry, Workflow, WorkflowEvaluation } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { Tbl, Expand } from "../components/DataDisplay";

const METRIC_STATUS_LABELS: Record<MetricStatusEntry["status"], string> = {
  measured: "Measured",
  "evidence-based": "Evidence-based",
  ground_truth_dependent: "Ground-truth dependent",
  unavailable: "Unavailable",
};

interface EvalRun {
  timestamp: string;
  tasks_total: number;
  tasks_completed: number;
  task_completion_rate: number;
  validation_success_rate: number;
  avg_human_interventions: number;
  avg_execution_time_ms: number;
  avg_repair_attempts: number;
  regression_rate: number;
  avg_guardrail_warnings?: number;
  avg_guardrail_blocked?: number;
  results: Array<{ task_id: string; title: string; category: string; completed: boolean; final_status: string }>;
}

interface BaselineRun {
  timestamp: string;
  tasks_total: number;
  tasks_completed: number;
  task_completion_rate: number;
  validation_success_rate: number;
  avg_execution_time_ms: number;
  regression_rate: number;
  results: Array<{ task_id: string; title: string; category: string; completed: boolean; final_status: string }>;
}

const BAR_METRICS: { field: string; label: string; normalize: number }[] = [
  { field: "task_completion_rate", label: "Task completion", normalize: 1 },
  { field: "code_correctness_rate", label: "Code correctness (proxy)", normalize: 1 },
  { field: "avg_unnecessary_modification_ratio_proxy", label: "Unnecessary modifications (proxy)", normalize: 1 },
  { field: "avg_human_interventions", label: "Human intervention points", normalize: 5 },
];

function fmtVal(row: ComparisonMetricRow, v: number | null): string {
  if (v === null) return "n/a";
  if (row.unit.startsWith("fraction")) return `${(v * 100).toFixed(0)}%`;
  if (row.unit.startsWith("milliseconds")) return `${v.toFixed(0)}ms`;
  return String(v);
}

function BarCompare({ row, normalize }: { row: ComparisonMetricRow; normalize: number }) {
  const b = row.baseline ?? 0;
  const s = row.intent2deploy ?? 0;
  const bw = Math.max(0, Math.min(100, (b / normalize) * 100));
  const sw = Math.max(0, Math.min(100, (s / normalize) * 100));
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 4 }}>{row.metric}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 10.5, color: "var(--text-faint)", width: 72, flex: "0 0 auto" }}>Baseline</span>
        <div style={{ flex: 1, height: 8, borderRadius: 2, background: "var(--bg-subtle)" }}>
          <div style={{ width: `${bw}%`, height: "100%", borderRadius: 2, background: "var(--text-faint)" }} />
        </div>
        <span style={{ fontSize: 11, color: "var(--text-muted)", width: 48, textAlign: "right" }}>{fmtVal(row, row.baseline)}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 10.5, color: "var(--text-faint)", width: 72, flex: "0 0 auto" }}>Intent2Deploy</span>
        <div style={{ flex: 1, height: 8, borderRadius: 2, background: "var(--bg-subtle)" }}>
          <div style={{ width: `${sw}%`, height: "100%", borderRadius: 2, background: "var(--accent)" }} />
        </div>
        <span style={{ fontSize: 11, color: "var(--text-muted)", width: 48, textAlign: "right" }}>{fmtVal(row, row.intent2deploy)}</span>
      </div>
    </div>
  );
}

// =============================================================================
// A. WORKFLOW EVALUATION — faculty-defined 7-category framework, scored from
// ONE selected workflow's persisted evidence. Primary evaluation experience.
// =============================================================================

const CATEGORY_ORDER: EvaluationCategoryKey[] = [
  "explanation",
  "code_retrieval",
  "dependency_understanding",
  "bug_analysis",
  "code_generation",
  "refactoring",
  "rag_based_question",
];

const CATEGORY_LABELS: Record<EvaluationCategoryKey, string> = {
  explanation: "Explanation",
  code_retrieval: "Code Retrieval",
  dependency_understanding: "Dependency Understanding",
  bug_analysis: "Bug Analysis",
  code_generation: "Code Generation",
  refactoring: "Refactoring",
  rag_based_question: "RAG-based Question",
};

function categoryStatusDisplay(cat: EvaluationCategoryResult): { icon: string; label: string; cls: string } {
  if (cat.status === "not_applicable") return { icon: "—", label: "Not applicable", cls: "" };
  if (cat.status === "not_evaluated") return { icon: "—", label: "Not evaluated", cls: "" };
  if (cat.is_partial) return { icon: "◐", label: "Partially evaluated", cls: "warn" };
  return { icon: "✓", label: "Evidence-based", cls: "success" };
}

function metricLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\bk\b/gi, "K").replace(/^./, (c) => c.toUpperCase());
}

function CategoryCard({ label, cat }: { label: string; cat?: EvaluationCategoryResult }) {
  if (!cat) {
    return (
      <div className="card" style={{ marginBottom: 10 }}>
        <div className="card-title" style={{ marginBottom: 4 }}>{label}</div>
        <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Not evaluated in this workflow.</p>
      </div>
    );
  }
  const statusDisplay = categoryStatusDisplay(cat);
  const metricEntries = Object.entries(cat.metrics);
  const independentEntries = Object.entries(cat.independent_checks);
  const evidenceEntries = Object.entries(cat.evidence);

  if (cat.status !== "evaluated") {
    return (
      <div className="card" style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
          <div className="card-title" style={{ marginBottom: 0 }}>{label}</div>
          <span className="tag">{statusDisplay.icon} {statusDisplay.label}</span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-faint)", marginTop: 10, marginBottom: 0 }}>{cat.note}</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title" style={{ marginBottom: 0 }}>{label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className={`status ${statusDisplay.cls}`}><span className="dot" />{statusDisplay.icon} {statusDisplay.label}</span>
          <span className="tag accent">{cat.score} / 100</span>
        </div>
      </div>

      {cat.criteria.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12.5 }}>
          {cat.criteria.map((c) => (
            <div key={c.label} style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
              <span style={{ color: "var(--text-muted)" }}>{c.label} <span style={{ color: "var(--text-faint)", fontSize: 11 }}>({c.weight}pt)</span>:</span>
              <span style={{ fontWeight: c.result === "met" ? 600 : 400 }}>{c.result}</span>
            </div>
          ))}
        </div>
      )}

      {metricEntries.length > 0 && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)", fontSize: 12.5 }}>
          {metricEntries.map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
              <span style={{ color: "var(--text-muted)", minWidth: 190, flex: "0 0 auto" }}>{metricLabel(k)}:</span>
              <span>{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {independentEntries.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--text-faint)" }}>
          {independentEntries.map(([k, v]) => (
            <div key={k}>{metricLabel(k)}: {v}</div>
          ))}
        </div>
      )}

      <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 10, marginBottom: 0 }}>{cat.note}</p>

      {evidenceEntries.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 700 }}>Evidence</summary>
          <pre className="mono-block" style={{ marginTop: 8, fontSize: 11 }}>{JSON.stringify(cat.evidence, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

function WorkflowEvaluationSection() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [evalResult, setEvalResult] = useState<WorkflowEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listWorkflows()
      .then((wfs) => {
        // The workflow history can contain many runs with the identical
        // (or near-identical) developer intent from repeated testing —
        // dedupe by exact intent text, keeping the most recently updated
        // run per unique intent, so each distinct workflow appears once.
        const sorted = wfs.slice().sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
        const seen = new Set<string>();
        const deduped: Workflow[] = [];
        for (const w of sorted) {
          if (seen.has(w.intent)) continue;
          seen.add(w.intent);
          deduped.push(w);
        }
        setWorkflows(deduped);
        if (deduped.length > 0) setSelectedId(deduped[0].id);
      })
      .catch((e) => setListError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    setError("");
    setEvalResult(null);
    setWorkflow(null);
    Promise.all([api.getWorkflow(selectedId), api.getWorkflowEvaluation(selectedId)])
      .then(([wf, ev]) => {
        setWorkflow(wf);
        setEvalResult(ev);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [selectedId]);

  return (
    <>
      <div className="card-title">Evaluate a workflow</div>
      <div className="card">
        <label style={{ fontSize: 12.5, color: "var(--text-muted)", display: "block", marginBottom: 6 }}>Select workflow</label>
        {workflows.length === 0 ? (
          <div className="empty-state">{listError || "No workflows found yet."}</div>
        ) : (
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="btn"
            style={{ width: "100%", textAlign: "left", fontWeight: 400 }}
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.intent.length > 70 ? `${w.intent.slice(0, 70)}…` : w.intent} — {w.state} — {new Date(w.updated_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
              </option>
            ))}
          </select>
        )}

        {workflow && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)", fontSize: 12.5, color: "var(--text-muted)" }}>
            <StatusBadge state={workflow.state} />
            <div style={{ marginTop: 8 }}>Workflow ID: <code>{workflow.id}</code></div>
            <div>Intent: {workflow.intent}</div>
            <div>Execution time: {workflow.total_ms != null ? `${workflow.total_ms}ms` : "—"}</div>
            <div>Validation: {workflow.validation_ms != null ? `ran (${workflow.validation_ms}ms)` : "not yet run"}</div>
          </div>
        )}
      </div>

      {error && <div className="callout callout-danger">{error}</div>}
      {loading && (
        <div className="card">
          <div className="empty-state">Evaluating…</div>
        </div>
      )}

      {!loading && workflows.length === 0 && (
        <div className="card">
          <div className="empty-state">Select a completed workflow to evaluate its performance.</div>
        </div>
      )}

      {!loading && evalResult && !evalResult.available && (
        <div className="card">
          <div className="empty-state">
            {evalResult.message || "Evaluation is not available yet. Complete the workflow and required validation stages first."}
          </div>
        </div>
      )}

      {!loading && evalResult && evalResult.available && (
        <>
          <div className="card-title" style={{ marginTop: 20 }}>Overall result</div>
          <div className="card">
            <div style={{ display: "flex", gap: 36, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 30, fontWeight: 700 }}>
                  {evalResult.overall_score !== null ? `${evalResult.overall_score} / 100` : "—"}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Overall evidence score</div>
                {evalResult.overall_score === null && (
                  <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 4, maxWidth: 260 }}>
                    {evalResult.overall_score_message || "Overall evidence score unavailable — insufficient measurable evidence."}
                  </div>
                )}
              </div>
              <div>
                <div style={{ fontSize: 30, fontWeight: 700 }}>
                  {evalResult.evaluated_categories} / {evalResult.total_categories ?? 7}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Evaluated categories</div>
              </div>
              <div>
                <div style={{ fontSize: 30, fontWeight: 700 }}>
                  {evalResult.metrics_summary.unavailable_count}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Unavailable metrics</div>
              </div>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 14, marginBottom: 0 }}>
              Computed only from categories with a valid evidence-based score. Not-applicable and not-evaluated
              categories are excluded — they never count against the workflow. The unavailable count is built
              dynamically from the Metric Status table below, never fixed.
            </p>
          </div>

          <div className="card-title" style={{ marginTop: 20 }}>Category results</div>
          {CATEGORY_ORDER.map((key) => (
            <CategoryCard key={key} label={CATEGORY_LABELS[key]} cat={evalResult.categories[key]} />
          ))}

          <div className="card-title" style={{ marginTop: 20 }}>Measured in this workflow ({evalResult.metrics_summary.measured_count})</div>
          <div className="card">
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px" }}>
              {evalResult.metrics_summary.measured.map((m) => (
                <span key={m} className="tag success">✓ {m}</span>
              ))}
            </div>
          </div>

          <div className="card-title" style={{ marginTop: 20 }}>Ground-truth dependent ({evalResult.metrics_summary.ground_truth_dependent_count})</div>
          <div className="card">
            <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 0 }}>
              These have a well-defined formula but require an independently-labelled reference this workflow
              does not have — see the Metric Status table for exactly why each one.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px" }}>
              {evalResult.metrics_summary.ground_truth_dependent.map((m) => (
                <span key={m} className="tag warn">• {m}</span>
              ))}
            </div>
          </div>

          <Expand title={`Metric status table (${evalResult.metric_status.length} metrics)`} defaultOpen>
            <Tbl
              headers={["Metric", "Status", "Value", "Evidence"]}
              rows={evalResult.metric_status.map((m) => [m.metric, METRIC_STATUS_LABELS[m.status], m.value, m.evidence])}
            />
          </Expand>

          {Object.keys(evalResult.guardrail_metrics).length > 0 && evalResult.guardrail_metrics.total > 0 && (
            <Expand title={`Guardrail metrics (${evalResult.guardrail_metrics.total} checks)`}>
              <p style={{ fontSize: 12.5 }}>
                Passed: {evalResult.guardrail_metrics.passed} · Warnings: {evalResult.guardrail_metrics.warnings} · Blocked: {evalResult.guardrail_metrics.blocked} ·
                Failed: {evalResult.guardrail_metrics.failed} · Not applicable: {evalResult.guardrail_metrics.not_applicable} · Approval required: {evalResult.guardrail_metrics.approval_required}
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px" }}>
                {Object.entries(evalResult.guardrail_metrics.by_category).map(([cat, n]) => (
                  <span key={cat} className="tag">{cat}: {n}</span>
                ))}
              </div>
            </Expand>
          )}

          {evalResult.measurement_limitations.length > 0 && (
            <>
              <div className="card-title" style={{ marginTop: 20 }}>Measurement limitations</div>
              <div className="card">
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {evalResult.measurement_limitations.map((l, i) => (
                    <li key={i} style={{ fontSize: 12.5, marginBottom: 8 }}>{l}</li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}

// =============================================================================
// B. BENCHMARK / RESEARCH EVALUATION — multi-task baseline-vs-Intent2Deploy
// comparison (unchanged infrastructure: scripts/run_evaluation.py,
// scripts/run_baseline_evaluation.py, scripts/compare_evaluation_runs.py).
// Secondary tab — no longer the default landing view.
// =============================================================================

function BenchmarkEvaluationSection() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [baselineRuns, setBaselineRuns] = useState<BaselineRun[]>([]);
  const [comparison, setComparison] = useState<ExperimentComparison | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api
      .getEvaluationResults()
      .then((r) => {
        setRuns((r.runs as EvalRun[]) || []);
        if ((r as { message?: string }).message) setMessage((r as { message?: string }).message || "");
      })
      .catch((e) => setMessage(String(e)));
    api.getBaselineResults().then((r) => setBaselineRuns((r.runs as BaselineRun[]) || [])).catch(() => {});
    api.getEvaluationComparison().then(setComparison).catch(() => {});
  }, []);

  return (
    <div>
      <p className="page-subtitle" style={{ marginTop: 0 }}>
        A controlled comparison between a non-orchestrated baseline and the full Intent2Deploy workflow, run
        against the same 21-task benchmark and the same demo repository. Every number below is read from
        <code> evaluation/results/</code> — nothing is fabricated or estimated.
      </p>

      <div className="card-title">Experiment overview</div>
      {comparison?.available ? (
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8, marginBottom: 16 }}>
          <p style={{ margin: "0 0 6px" }}>
            <strong style={{ color: "var(--text)" }}>Research question:</strong> {comparison.research_question}
          </p>
          <p style={{ margin: "0 0 2px" }}>
            Benchmark: {comparison.tasks_total_intent2deploy} tasks (<code>evaluation/tasks/</code>) against{" "}
            <code>demo-repository</code>
          </p>
          <p style={{ margin: "0 0 2px" }}>
            Baseline: single-shot LLM code generation from a naive keyword-matched file selection — no retrieval
            pipeline, no planning stage, no approval checkpoints, no guardrails, single validation run
          </p>
          <p style={{ margin: 0 }}>
            System under test: the full Intent2Deploy workflow (indexing → ChromaDB retrieval → planning → human
            approval → code generation → test generation → validation → guardrails → readiness)
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="empty-state">
            {comparison?.message || "No comparison found. Run both evaluation arms, then `python scripts/compare_evaluation_runs.py`."}
          </div>
        </div>
      )}

      {comparison?.available && (
        <>
          <div className="card-title">Baseline vs. Intent2Deploy</div>
          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Baseline</th>
                  <th>Intent2Deploy</th>
                  <th>Abs. diff</th>
                  <th>% change</th>
                </tr>
              </thead>
              <tbody>
                {comparison.comparison_table?.map((row) => (
                  <tr key={row.field}>
                    <td>{row.metric}</td>
                    <td>{fmtVal(row, row.baseline)}</td>
                    <td>{fmtVal(row, row.intent2deploy)}</td>
                    <td>{row.absolute_difference ?? "n/a"}</td>
                    <td>{row.percent_improvement !== null ? `${row.percent_improvement}%` : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card-title">Key metrics</div>
          <div className="card">
            {comparison.comparison_table?.map((row, i) => (
              <div key={row.field} style={{ padding: "8px 0", borderBottom: i < (comparison.comparison_table?.length ?? 0) - 1 ? "1px solid var(--border)" : "none" }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                  {row.metric} <span style={{ fontWeight: 400, color: "var(--text-faint)" }}>({row.unit})</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                  <code style={{ fontSize: 11 }}>{row.formula}</code>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 2 }}>{row.interpretation_note}</div>
              </div>
            ))}
          </div>

          <div className="card-title">Comparison charts</div>
          <div className="card">
            {BAR_METRICS.map((m) => {
              const row = comparison.comparison_table?.find((r) => r.field === m.field);
              return row ? <BarCompare key={m.field} row={row} normalize={m.normalize} /> : null;
            })}
          </div>

          <div className="card-title">Interpretation</div>
          <div className="card">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {comparison.interpretation?.map((line, i) => (
                <li key={i} style={{ fontSize: 13, marginBottom: 8 }}>{line}</li>
              ))}
            </ul>
            <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 10, marginBottom: 0 }}>{comparison.statistical_note}</p>
          </div>

          <div className="card-title">Research question alignment</div>
          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>Concept</th>
                  <th>Hypothesis</th>
                  <th>Measured result</th>
                </tr>
              </thead>
              <tbody>
                {comparison.research_question_alignment?.map((row) => (
                  <tr key={row.concept}>
                    <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{row.concept}</td>
                    <td style={{ fontSize: 12.5 }}>{row.hypothesis}</td>
                    <td style={{ fontSize: 12.5 }}>{row.result}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card-title">Failure analysis</div>
          <div className="card">
            {(comparison.failure_analysis?.length ?? 0) === 0 ? (
              <div className="empty-state">No failure cases — every task completed in both arms.</div>
            ) : (
              comparison.failure_analysis?.map((c) => (
                <div key={c.task_id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    <code>{c.task_id}</code> {c.title} <span style={{ fontWeight: 400, color: "var(--text-faint)" }}>({c.category})</span>
                  </div>
                  <div style={{ fontSize: 12.5, marginTop: 4 }}>
                    <span className={`status ${c.baseline_completed ? "success" : "danger"}`}>
                      <span className="dot" /> baseline {c.baseline_completed ? "completed" : "failed"}
                    </span>
                    {c.baseline_failure_reason && <span style={{ color: "var(--text-muted)" }}> — {c.baseline_failure_reason}</span>}
                  </div>
                  <div style={{ fontSize: 12.5, marginTop: 2 }}>
                    <span className={`status ${c.intent2deploy_completed ? "success" : "danger"}`}>
                      <span className="dot" /> Intent2Deploy {c.intent2deploy_completed ? "completed" : "failed"}
                    </span>
                    {c.intent2deploy_failure_reason && <span style={{ color: "var(--text-muted)" }}> — {c.intent2deploy_failure_reason}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        </>
      )}

      <div className="card-title">Run history — Intent2Deploy</div>
      {runs.length === 0 && (
        <div className="card">
          <div className="empty-state">{message || "No evaluation runs found yet. Run `python scripts/run_evaluation.py`."}</div>
        </div>
      )}
      {runs.map((run, i) => (
        <div className="card" key={i}>
          <div className="card-title">Run: {new Date(run.timestamp).toLocaleString()}</div>
          <div className="metrics-strip" style={{ margin: 0 }}>
            <div className="metric"><span className="stat-value">{(run.task_completion_rate * 100).toFixed(0)}%</span><span className="stat-label">Task completion rate</span></div>
            <div className="metric"><span className="stat-value">{(run.validation_success_rate * 100).toFixed(0)}%</span><span className="stat-label">Validation success rate</span></div>
            <div className="metric"><span className="stat-value">{run.avg_human_interventions.toFixed(1)}</span><span className="stat-label">Avg. human interventions</span></div>
            <div className="metric"><span className="stat-value">{run.avg_repair_attempts.toFixed(2)}</span><span className="stat-label">Avg. repair attempts</span></div>
          </div>
          <table style={{ marginTop: 16 }}>
            <thead><tr><th>Task</th><th>Category</th><th>Completed</th><th>Final status</th></tr></thead>
            <tbody>
              {run.results.map((r) => (
                <tr key={r.task_id}>
                  <td>{r.title}</td>
                  <td>{r.category}</td>
                  <td>{r.completed ? "yes" : "no"}</td>
                  <td>{r.final_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div className="card-title">Run history — baseline</div>
      {baselineRuns.length === 0 && (
        <div className="card">
          <div className="empty-state">No baseline runs found yet. Run `python scripts/run_baseline_evaluation.py`.</div>
        </div>
      )}
      {baselineRuns.map((run, i) => (
        <div className="card" key={i}>
          <div className="card-title">Run: {new Date(run.timestamp).toLocaleString()}</div>
          <div className="metrics-strip" style={{ margin: 0 }}>
            <div className="metric"><span className="stat-value">{(run.task_completion_rate * 100).toFixed(0)}%</span><span className="stat-label">Task completion rate</span></div>
            <div className="metric"><span className="stat-value">{(run.validation_success_rate * 100).toFixed(0)}%</span><span className="stat-label">Validation success rate</span></div>
            <div className="metric"><span className="stat-value">{(run.avg_execution_time_ms / 1000).toFixed(2)}s</span><span className="stat-label">Avg. execution time</span></div>
            <div className="metric"><span className="stat-value">{(run.regression_rate * 100).toFixed(0)}%</span><span className="stat-label">Regression rate</span></div>
          </div>
          <table style={{ marginTop: 16 }}>
            <thead><tr><th>Task</th><th>Category</th><th>Completed</th><th>Final status</th></tr></thead>
            <tbody>
              {run.results.map((r) => (
                <tr key={r.task_id}>
                  <td>{r.title}</td>
                  <td>{r.category}</td>
                  <td>{r.completed ? "yes" : "no"}</td>
                  <td>{r.final_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

// =============================================================================
// Page — A (default) + B (secondary tab)
// =============================================================================

type EvalTabKey = "workflow" | "benchmark";

export function EvaluationPage() {
  const [tab, setTab] = useState<EvalTabKey>("workflow");

  return (
    <div>
      <h1 className="page-title">Evaluation</h1>
      <p className="page-subtitle">
        Evaluate one workflow against the seven faculty-defined categories, using only that workflow's actual
        persisted evidence. A separate multi-task research benchmark remains available below.
      </p>

      <div className="tabs">
        <button className={`tab ${tab === "workflow" ? "active" : ""}`} onClick={() => setTab("workflow")}>
          Workflow Evaluation
        </button>
        <button className={`tab ${tab === "benchmark" ? "active" : ""}`} onClick={() => setTab("benchmark")}>
          Benchmark / Research Evaluation
        </button>
      </div>

      {tab === "workflow" ? <WorkflowEvaluationSection /> : <BenchmarkEvaluationSection />}
    </div>
  );
}
