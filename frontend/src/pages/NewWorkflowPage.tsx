import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";
import type { Repository, Workflow } from "../types";

type RepoSource = "local" | "github";
type Phase = "form" | "running" | "error";
type ProgressStage = "repo" | "intent" | "indexing" | "planning" | "done";

const GITHUB_URL_RE = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;

const PAYMENT_DEMO_INTENT =
  "Payment provider timeout is causing duplicate charges when the same order is retried. Add idempotency handling and tests.";

const EXAMPLES: { title: string; description: string; intent: string; demo?: boolean }[] = [
  {
    title: "Payment reliability",
    description: "Prevent duplicate charges when a payment provider times out.",
    intent: PAYMENT_DEMO_INTENT,
    demo: true,
  },
  {
    title: "Password reset",
    description: "Add password reset functionality with appropriate tests.",
    intent: "Add password reset functionality with appropriate tests.",
  },
  {
    title: "Intermittent 500s",
    description: "Find why this API is returning intermittent 500 errors and propose a fix.",
    intent: "Find why this API is returning intermittent 500 errors and propose a fix.",
  },
];

function repoLabel(source: RepoSource, value: string): string {
  if (source === "github") {
    const match = value.match(/github\.com\/([^/]+)\/([^/]+?)\/?$/);
    return match ? `${match[1]}/${match[2]}` : value;
  }
  const parts = value.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || value;
}

const PROGRESS_ITEMS: { key: ProgressStage; label: string }[] = [
  { key: "repo", label: "Repository connected" },
  { key: "intent", label: "Intent understood" },
  { key: "indexing", label: "Indexing repository" },
  { key: "planning", label: "Retrieving relevant context" },
  { key: "planning", label: "Analyzing architecture" },
  { key: "planning", label: "Preparing implementation plan" },
];
const STAGE_ORDER: ProgressStage[] = ["repo", "intent", "indexing", "planning", "done"];

export function NewWorkflowPage() {
  const navigate = useNavigate();

  const [intent, setIntent] = useState("");
  const [repoSource, setRepoSource] = useState<RepoSource | null>(null);
  const [repoValue, setRepoValue] = useState("");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<RepoSource>("local");
  const [pickerInput, setPickerInput] = useState("");
  const [pickerError, setPickerError] = useState("");

  const [phase, setPhase] = useState<Phase>("form");
  const [stage, setStage] = useState<ProgressStage>("repo");
  const [erroredStage, setErroredStage] = useState<ProgressStage | null>(null);
  const [runError, setRunError] = useState("");

  function openPicker() {
    setPickerMode(repoSource || "local");
    setPickerInput(repoValue);
    setPickerError("");
    setPickerOpen(true);
  }

  function confirmPicker() {
    const value = pickerInput.trim();
    if (!value) {
      setPickerError(pickerMode === "local" ? "Enter a local repository path." : "Enter a GitHub repository URL.");
      return;
    }
    if (pickerMode === "github" && !GITHUB_URL_RE.test(value)) {
      setPickerError("Expected the form https://github.com/<owner>/<repository>.");
      return;
    }
    setRepoSource(pickerMode);
    setRepoValue(value);
    setPickerOpen(false);
  }

  async function startWorkflow(overrideIntent?: string, overrideSource?: RepoSource, overrideValue?: string) {
    const finalIntent = (overrideIntent ?? intent).trim();
    const finalSource = overrideSource ?? repoSource;
    const finalValue = overrideValue ?? repoValue;
    if (!finalIntent || !finalSource || !finalValue) return;

    setPhase("running");
    setRunError("");
    setErroredStage(null);

    try {
      setStage("repo");
      const project = await api.createProject(`Intent2Deploy — ${new Date().toLocaleString()}`);
      let repo: Repository;
      try {
        repo = finalSource === "github" ? await api.cloneRepository(project.id, finalValue) : await api.indexRepository(project.id, finalValue);
      } catch (e) {
        setErroredStage("repo");
        throw e;
      }

      setStage("intent");
      let workflow: Workflow;
      try {
        workflow = await api.createWorkflow({ project_id: project.id, repository_id: repo.id, intent: finalIntent });
      } catch (e) {
        setErroredStage("intent");
        throw e;
      }

      setStage("indexing");
      try {
        await api.runIndexing(workflow.id);
      } catch (e) {
        setErroredStage("indexing");
        throw e;
      }

      setStage("planning");
      try {
        await api.runPlanning(workflow.id);
      } catch (e) {
        setErroredStage("planning");
        throw e;
      }

      setStage("done");
      navigate(`/workflows/${workflow.id}`);
    } catch (e) {
      setPhase("error");
      setRunError(humanizeError(e));
    }
  }

  function humanizeError(e: unknown): string {
    const msg = String(e instanceof Error ? e.message : e);
    if (/repository path does not exist/i.test(msg)) {
      return "Repository could not be found. Check that the local path exists and is accessible.";
    }
    if (/not a valid github repository url/i.test(msg)) {
      return "That doesn't look like a GitHub repository URL. Expected https://github.com/<owner>/<repository>.";
    }
    if (/could not clone/i.test(msg)) {
      return "Repository could not be cloned. Check the URL, that the repository is public, and your network connection.";
    }
    if (/blocked|unsafe/i.test(msg)) {
      return msg; // guardrail messages are already human-readable and specific
    }
    if (/failed to fetch|networkerror/i.test(msg)) {
      return "Could not reach the Intent2Deploy backend. Is it running on port 8000?";
    }
    return msg || "Something went wrong while starting the workflow.";
  }

  function reset() {
    setPhase("form");
    setRunError("");
    setErroredStage(null);
  }

  const canStart = intent.trim().length > 0 && !!repoSource && !!repoValue;

  if (phase !== "form") {
    return (
      <div>
        <h1 className="page-title">New Workflow</h1>
        <p className="page-subtitle">{phase === "error" ? "Workflow could not be started" : "Starting workflow…"}</p>

        <div className="card" style={{ maxWidth: 520 }}>
          <div className="card-title">Progress</div>
          <div className="step-list">
            {PROGRESS_ITEMS.map((item, i) => {
              const itemIndex = STAGE_ORDER.indexOf(item.key);
              const currentIndex = STAGE_ORDER.indexOf(stage);
              const isError = erroredStage === item.key;
              const isDone = !isError && itemIndex < currentIndex;
              const isActive = !isError && phase === "running" && itemIndex === currentIndex;
              const cls = isError ? "error" : isDone ? "done" : isActive ? "active" : "";
              return (
                <div key={i} className={`step-item ${cls}`}>
                  <span className="dot" />
                  <span>{item.label}</span>
                </div>
              );
            })}
          </div>
          {phase === "error" && (
            <>
              <div className="callout callout-danger" style={{ marginTop: 14 }} role="alert">
                {runError}
              </div>
              <div className="btn-row">
                <button className="btn btn-primary" onClick={reset}>
                  Try Again
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="page-title">New Workflow</h1>
      <p className="page-subtitle">Describe the engineering task you want to accomplish.</p>

      <div className="card" style={{ maxWidth: 640 }}>
        <label htmlFor="intent-textarea">What do you want to build or fix?</label>
        <textarea
          id="intent-textarea"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="Describe what you want to build, fix, refactor, or improve..."
          rows={5}
        />

        <hr className="divider" style={{ margin: "18px 0 14px" }} />
        <div className="card-title">Repository</div>

        {repoSource && !pickerOpen ? (
          <div className="repo-summary">
            <div className="col">
              <div className="k">Repository</div>
              <div className="v">{repoLabel(repoSource, repoValue)}</div>
            </div>
            <div className="col">
              <div className="k">Source</div>
              <div className="v">{repoSource === "github" ? "GitHub" : "Local"}</div>
            </div>
            <div className="col">
              <div className="k">Status</div>
              <div className="v">Ready to index</div>
            </div>
            <button type="button" className="btn" onClick={openPicker}>
              Change
            </button>
          </div>
        ) : !pickerOpen ? (
          <div className="repo-field-row">
            <p style={{ fontSize: 12.5, color: "var(--text-faint)", margin: 0 }}>No repository configured yet.</p>
            <button type="button" className="btn" onClick={openPicker}>
              Configure Repository
            </button>
          </div>
        ) : null}

        {pickerOpen && (
          <div style={{ marginTop: repoSource ? 0 : 8 }}>
            <div className="repo-field-row">
              <div className="field field-source">
                <label htmlFor="repo-source-select">Repository source</label>
                <select id="repo-source-select" value={pickerMode} onChange={(e) => setPickerMode(e.target.value as RepoSource)}>
                  <option value="local">Local Repository</option>
                  <option value="github">GitHub</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="repo-value-input">{pickerMode === "local" ? "Local path" : "GitHub repository URL"}</label>
                <input
                  id="repo-value-input"
                  value={pickerInput}
                  onChange={(e) => setPickerInput(e.target.value)}
                  placeholder={pickerMode === "local" ? "/path/to/repository" : "https://github.com/owner/repository"}
                  autoFocus
                />
              </div>
            </div>
            <div className="btn-row">
              <button type="button" className="btn btn-primary" onClick={confirmPicker}>
                Set Repository
              </button>
              <button type="button" className="btn" onClick={() => setPickerOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {pickerError && (
          <div className="entry-picker-error" role="alert" style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>
            {pickerError}
          </div>
        )}

        {!pickerOpen && (
          <div className="btn-row">
            <button type="button" className="btn btn-primary" disabled={!canStart} onClick={() => startWorkflow()}>
              Start Workflow
            </button>
          </div>
        )}
      </div>

      <div style={{ maxWidth: 640, marginTop: 28 }}>
        <div className="card-title">Examples</div>
        <div className="example-list">
          {EXAMPLES.map((ex, i) => (
            <button
              key={i}
              type="button"
              className="example-row"
              onClick={() =>
                ex.demo ? startWorkflow(ex.intent, "local", "../demo-repository") : setIntent(ex.intent)
              }
            >
              <span>
                <span className="ex-title">{ex.title}</span>
                <div className="ex-desc">{ex.description}</div>
              </span>
              <span className="ex-tag">{ex.demo ? "Uses bundled demo repository" : "Fill prompt"}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
