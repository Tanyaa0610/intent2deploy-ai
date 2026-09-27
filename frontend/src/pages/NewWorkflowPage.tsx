import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";
import type { Repository, Workflow } from "../types";

type RepoSource = "local" | "github";
type Phase = "form" | "running" | "error";
type ProgressStage = "repo" | "intent" | "indexing" | "planning" | "done";

const GITHUB_URL_RE = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/;

const EXAMPLE_PROMPTS = [
  "Payment provider timeout is causing duplicate charges when the same order is retried. Add idempotency handling and tests.",
  "Add password reset functionality with appropriate tests.",
  "Find why this API is returning intermittent 500 errors and propose a fix.",
];

const PAYMENT_DEMO_INTENT = EXAMPLE_PROMPTS[0];

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
      <div className="entry-page">
        <div className="entry-hero">
          <h1>Intent2Deploy AI</h1>
          <p className="tagline">From intent to validated software</p>
        </div>
        <div className="entry-box">
          <div className="entry-prompt-label">{phase === "error" ? "Workflow could not be started" : "Analyzing your request…"}</div>
          <div className="entry-progress">
            {PROGRESS_ITEMS.map((item, i) => {
              const itemIndex = STAGE_ORDER.indexOf(item.key);
              const currentIndex = STAGE_ORDER.indexOf(stage);
              const isError = erroredStage === item.key;
              const isDone = !isError && itemIndex < currentIndex;
              const isActive = !isError && phase === "running" && itemIndex === currentIndex;
              const cls = isError ? "error" : isDone ? "done" : isActive ? "active" : "";
              return (
                <div key={i} className={`entry-progress-item ${cls}`}>
                  <span className="icon">{isError ? "✗" : isDone ? "✓" : isActive ? "" : "○"}</span>
                  <span>{item.label}</span>
                </div>
              );
            })}
          </div>
          {phase === "error" && (
            <>
              <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)", marginTop: 14 }} role="alert">
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
    <div className="entry-page">
      <div className="entry-hero">
        <h1>Intent2Deploy AI</h1>
        <p className="tagline">From intent to validated software</p>
        <p className="instruction">Describe the problem, feature, or change you want Intent2Deploy to handle.</p>
      </div>

      <div className="entry-box">
        <label className="entry-prompt-label" htmlFor="intent-textarea">
          What do you want to build or fix?
        </label>
        <textarea
          id="intent-textarea"
          className="entry-textarea"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="Describe what you want to build, fix, refactor, or improve..."
          rows={5}
        />

        <div className="entry-repo-row">
          {repoSource && !pickerOpen ? (
            <div className="entry-repo-chip">
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
              <button type="button" onClick={openPicker}>
                Change Repository
              </button>
            </div>
          ) : !pickerOpen ? (
            <button type="button" className="entry-add-repo-btn" onClick={openPicker}>
              + Add Repository
            </button>
          ) : (
            <span />
          )}

          {!pickerOpen && (
            <button type="button" className="entry-cta" disabled={!canStart} onClick={() => startWorkflow()}>
              Start Workflow →
            </button>
          )}
        </div>

        {pickerOpen && (
          <div className="entry-picker">
            <div className="entry-picker-title">Repository Source</div>
            <div className="entry-picker-choice" role="radiogroup" aria-label="Repository source">
              <label>
                <input type="radio" name="repo-source-mode" checked={pickerMode === "local"} onChange={() => setPickerMode("local")} />
                Local Repository
              </label>
              <label>
                <input type="radio" name="repo-source-mode" checked={pickerMode === "github"} onChange={() => setPickerMode("github")} />
                GitHub Repository
              </label>
            </div>

            {pickerMode === "local" ? (
              <>
                <label htmlFor="repo-local-input">Local path</label>
                <input
                  id="repo-local-input"
                  value={pickerInput}
                  onChange={(e) => setPickerInput(e.target.value)}
                  placeholder="/path/to/repository"
                  autoFocus
                />
              </>
            ) : (
              <>
                <label htmlFor="repo-github-input">GitHub repository URL</label>
                <input
                  id="repo-github-input"
                  value={pickerInput}
                  onChange={(e) => setPickerInput(e.target.value)}
                  placeholder="https://github.com/owner/repository"
                  autoFocus
                />
              </>
            )}
            {pickerError && (
              <div className="entry-picker-error" role="alert">
                {pickerError}
              </div>
            )}
            <div className="btn-row">
              <button type="button" className="btn" onClick={() => setPickerOpen(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={confirmPicker}>
                Add Repository
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="entry-examples">
        <div className="label">Try an example:</div>
        <div className="entry-example-row">
          {EXAMPLE_PROMPTS.map((p, i) => (
            <button key={i} type="button" className="entry-example" onClick={() => setIntent(p)}>
              {p.length > 52 ? `${p.slice(0, 52)}…` : p}
            </button>
          ))}
        </div>
      </div>

      <div className="entry-demo">
        <button
          type="button"
          className="entry-demo-link"
          onClick={() => startWorkflow(PAYMENT_DEMO_INTENT, "local", "../demo-repository")}
        >
          Try the Payment Reliability Demo →
        </button>
      </div>
    </div>
  );
}
