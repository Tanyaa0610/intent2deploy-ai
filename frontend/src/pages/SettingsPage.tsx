import { useEffect, useState } from "react";
import { api } from "../services/api";

interface HealthData {
  status: string;
  llm_provider: string;
  llm_mode: string;
  is_mock: boolean;
}

export function SettingsPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">Provider status and runtime configuration.</p>

      {error && <div className="callout callout-danger">{error}</div>}

      {health?.is_mock && (
        <div className="callout callout-mock" style={{ marginBottom: 18 }}>
          <strong>Mock mode active.</strong> LLM calls are deterministic stand-ins — no API billing.
          Set <code>LLM_MODE=live</code> in your <code>.env</code> file with a valid API key to enable live generation.
        </div>
      )}

      {/* Provider status */}
      <div className="card settings-section">
        <div className="card-title">LLM Provider</div>
        {health ? (
          <div>
            <div className="settings-row">
              <span className="settings-key">Provider</span>
              <code className="settings-val">{health.llm_provider}</code>
            </div>
            <div className="settings-row">
              <span className="settings-key">Mode</span>
              <code className="settings-val" style={{ color: health.is_mock ? "var(--warn)" : "var(--success)" }}>
                {health.llm_mode}
              </code>
            </div>
            <div className="settings-row">
              <span className="settings-key">API calls</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {health.is_mock ? "Not applicable (mock mode)" : "Live — billed against your API key"}
              </span>
            </div>
          </div>
        ) : (
          <div className="empty-state">Loading…</div>
        )}
      </div>

      {/* Configuration reference */}
      <div className="card settings-section">
        <div className="card-title">Environment Variables</div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
          Set these in <code>.env</code> at the project root. Restart the backend after changes.
        </p>
        {[
          { key: "LLM_PROVIDER",    desc: "anthropic | openai | local",     example: "anthropic" },
          { key: "LLM_MODE",        desc: "mock | live",                     example: "mock" },
          { key: "MODEL_NAME",      desc: "Model identifier for the provider", example: "claude-sonnet-5" },
          { key: "ANTHROPIC_API_KEY", desc: "Required when LLM_PROVIDER=anthropic and LLM_MODE=live", example: "sk-ant-…" },
          { key: "OPENAI_API_KEY",  desc: "Required when LLM_PROVIDER=openai and LLM_MODE=live",     example: "sk-…" },
          { key: "GITHUB_TOKEN",    desc: "Personal access token for push/PR (optional)",            example: "ghp_…" },
          { key: "GITHUB_OWNER",    desc: "Repository owner (org or user)",  example: "my-org" },
          { key: "GITHUB_REPO",     desc: "Repository name",                 example: "my-repo" },
          { key: "MAX_FILES_CHANGED", desc: "Guardrail: max files in one change set", example: "15" },
          { key: "MAX_PATCH_LINES", desc: "Guardrail: max patch lines in one change set", example: "1000" },
          { key: "MAX_REPAIR_ATTEMPTS", desc: "Max bounded repair cycles",    example: "2" },
        ].map(({ key, desc, example }) => (
          <div key={key} className="settings-row">
            <span className="settings-key"><code style={{ fontSize: 12 }}>{key}</code></span>
            <span style={{ flex: 1, fontSize: 12.5, color: "var(--text-muted)" }}>{desc}</span>
            <code className="settings-val">{example}</code>
          </div>
        ))}
      </div>

      {/* Safety limits reference */}
      <div className="card settings-section">
        <div className="card-title">Safety &amp; Guardrails</div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
          These safety controls are enforced on the backend and cannot be bypassed through the UI.
        </p>
        {[
          { label: "Sandboxed execution",         note: "All commands run in an isolated workspace; never in the source repository." },
          { label: "Command allowlist",            note: "Only pytest, ruff, npm, python, node, mypy, coverage, pip are permitted." },
          { label: "Path-traversal protection",   note: "File access is restricted to the workspace root." },
          { label: "Max repair attempts",         note: "Bounded repair loop — at most 2 attempts before requiring manual intervention." },
          { label: "Mandatory human approvals",   note: "Plan, code-diff, and commit each require explicit approval before proceeding." },
          { label: "No auto-push",                note: "Branch push and PR creation require explicit approval." },
          { label: "Production block",            note: "environment=production is rejected at workflow creation." },
          { label: "Secret detection",            note: "Generated patches are scanned for API keys, tokens, PEM keys before application." },
        ].map(({ label, note }) => (
          <div key={label} className="settings-row">
            <span className="settings-key">{label}</span>
            <span style={{ fontSize: 12.5, color: "var(--text-muted)", flex: 1 }}>{note}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
