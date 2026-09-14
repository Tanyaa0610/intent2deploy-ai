import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";

const DEMO_INTENT =
  "Add a password reset feature. Create appropriate tests and make sure existing authentication functionality is not affected.";

export function NewWorkflowPage() {
  const navigate = useNavigate();
  const [projectName, setProjectName] = useState("Demo Project");
  const [repoPath, setRepoPath] = useState("");
  const [intent, setIntent] = useState("");
  const [baseBranch, setBaseBranch] = useState("main");
  const [testCommand, setTestCommand] = useState("");
  const [buildCommand, setBuildCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState("");

  async function run(withDemo: boolean) {
    setBusy(true);
    setError("");
    try {
      const finalRepoPath = withDemo ? "../demo-repository" : repoPath;
      const finalIntent = withDemo ? DEMO_INTENT : intent;

      setStep("Creating project…");
      const project = await api.createProject(projectName || "Demo Project");

      setStep("Loading + indexing repository…");
      const repo = await api.indexRepository(project.id, finalRepoPath);

      setStep("Creating workflow…");
      const workflow = await api.createWorkflow({
        project_id: project.id,
        repository_id: repo.id,
        intent: finalIntent,
        base_branch: baseBranch,
        test_command: testCommand,
        build_command: buildCommand,
      });

      navigate(`/workflows/${workflow.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setStep("");
    }
  }

  return (
    <div>
      <h1 className="page-title">New Workflow</h1>
      <p className="page-subtitle">Describe the developer intent and point at a repository. Nothing is written until you approve each stage.</p>

      <div className="card" style={{ maxWidth: 640 }}>
        <div className="card-title">Repository</div>
        <label>Project name</label>
        <input value={projectName} onChange={(e) => setProjectName(e.target.value)} />
        <label>Repository path (local)</label>
        <input
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          placeholder="/absolute/path/to/repository"
        />
        <label>Base branch</label>
        <input value={baseBranch} onChange={(e) => setBaseBranch(e.target.value)} />

        <div className="card-title" style={{ marginTop: 20 }}>
          Developer Intent
        </div>
        <label>What should change?</label>
        <textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder='e.g. "Fix the null-reference bug in the order service."'
        />

        <label>Test command (optional — defaults to `python3 -m pytest -q`)</label>
        <input value={testCommand} onChange={(e) => setTestCommand(e.target.value)} placeholder="python3 -m pytest -q" />
        <label>Build command (optional)</label>
        <input value={buildCommand} onChange={(e) => setBuildCommand(e.target.value)} />

        {error && (
          <div className="callout" style={{ background: "var(--danger-soft)", color: "var(--danger)", marginTop: 12 }}>
            {error}
          </div>
        )}

        <div className="btn-row">
          <button className="btn btn-primary" disabled={busy || !repoPath || !intent} onClick={() => run(false)}>
            {busy ? step || "Working…" : "Start Analysis"}
          </button>
          <button className="btn" disabled={busy} onClick={() => run(true)}>
            {busy ? step || "Working…" : "Run Demo (password reset on demo-repository)"}
          </button>
        </div>
      </div>
    </div>
  );
}
