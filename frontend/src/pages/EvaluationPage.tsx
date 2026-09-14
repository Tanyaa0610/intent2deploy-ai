import { useEffect, useState } from "react";
import { api } from "../services/api";

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
  results: Array<{ task_id: string; title: string; category: string; completed: boolean; final_status: string }>;
}

export function EvaluationPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api
      .getEvaluationResults()
      .then((r) => {
        setRuns((r.runs as EvalRun[]) || []);
        if ((r as { message?: string }).message) setMessage((r as { message?: string }).message || "");
      })
      .catch((e) => setMessage(String(e)));
  }, []);

  return (
    <div>
      <h1 className="page-title">Evaluation</h1>
      <p className="page-subtitle">
        Results from <code>python scripts/run_evaluation.py</code> against the benchmark tasks in{" "}
        <code>evaluation/tasks/</code>. These numbers are computed from real workflow executions — never fabricated.
      </p>

      {runs.length === 0 && (
        <div className="card">
          <div className="empty-state">{message || "No evaluation runs found yet."}</div>
        </div>
      )}

      {runs.map((run, i) => (
        <div className="card" key={i}>
          <div className="card-title">Run: {new Date(run.timestamp).toLocaleString()}</div>
          <div className="grid grid-4">
            <div className="stat"><span className="stat-value">{(run.task_completion_rate * 100).toFixed(0)}%</span><span className="stat-label">Task completion rate</span></div>
            <div className="stat"><span className="stat-value">{(run.validation_success_rate * 100).toFixed(0)}%</span><span className="stat-label">Validation success rate</span></div>
            <div className="stat"><span className="stat-value">{run.avg_human_interventions.toFixed(1)}</span><span className="stat-label">Avg. human interventions</span></div>
            <div className="stat"><span className="stat-value">{run.avg_repair_attempts.toFixed(2)}</span><span className="stat-label">Avg. repair attempts</span></div>
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
