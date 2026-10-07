import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { ComparisonMetricRow, ExperimentComparison } from "../types";

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

export function EvaluationPage() {
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
      <h1 className="page-title">Evaluation</h1>
      <p className="page-subtitle">
        A controlled comparison between a non-orchestrated baseline and the full Intent2Deploy workflow, run
        against the same benchmark tasks and the same demo repository. Every number below is read from
        <code> evaluation/results/</code> — nothing is fabricated or estimated.
      </p>

      {/* ---------------------------------------------------------------- */}
      {/* Experiment overview                                              */}
      {/* ---------------------------------------------------------------- */}
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
            {comparison?.message || "Comparison not yet generated. Run both evaluation arms, then `python scripts/compare_evaluation_runs.py`."}
          </div>
        </div>
      )}

      {comparison?.available && (
        <>
          {/* ---------------------------------------------------------------- */}
          {/* Baseline vs Intent2Deploy — results table                        */}
          {/* ---------------------------------------------------------------- */}
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

          {/* ---------------------------------------------------------------- */}
          {/* Key metrics — definitions                                        */}
          {/* ---------------------------------------------------------------- */}
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

          {/* ---------------------------------------------------------------- */}
          {/* Visual comparison                                                */}
          {/* ---------------------------------------------------------------- */}
          <div className="card-title">Comparison charts</div>
          <div className="card">
            {BAR_METRICS.map((m) => {
              const row = comparison.comparison_table?.find((r) => r.field === m.field);
              return row ? <BarCompare key={m.field} row={row} normalize={m.normalize} /> : null;
            })}
          </div>

          {/* ---------------------------------------------------------------- */}
          {/* Interpretation                                                   */}
          {/* ---------------------------------------------------------------- */}
          <div className="card-title">Interpretation</div>
          <div className="card">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {comparison.interpretation?.map((line, i) => (
                <li key={i} style={{ fontSize: 13, marginBottom: 8 }}>{line}</li>
              ))}
            </ul>
            <p style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 10, marginBottom: 0 }}>{comparison.statistical_note}</p>
          </div>

          {/* ---------------------------------------------------------------- */}
          {/* Research question alignment                                      */}
          {/* ---------------------------------------------------------------- */}
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

          {/* ---------------------------------------------------------------- */}
          {/* Failure analysis                                                 */}
          {/* ---------------------------------------------------------------- */}
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

      {/* ---------------------------------------------------------------- */}
      {/* Run history (raw, per-arm)                                       */}
      {/* ---------------------------------------------------------------- */}
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
