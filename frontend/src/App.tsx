import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { NewWorkflowPage } from "./pages/NewWorkflowPage";
import { WorkflowHistoryPage } from "./pages/WorkflowHistoryPage";
import { WorkflowDetailPage } from "./pages/WorkflowDetailPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { GuardrailsPage } from "./pages/GuardrailsPage";
import { RepositoriesPage } from "./pages/RepositoriesPage";
import { RepositoryWorkspacePage } from "./pages/RepositoryWorkspacePage";
import { SettingsPage } from "./pages/SettingsPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { api } from "./services/api";
import type { AlertCounts } from "./types";

const navCls = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

// Show "Workflow Runs" as active when on a workflow detail sub-page too
function WorkflowNavLink() {
  const loc = useLocation();
  const isActive = loc.pathname.startsWith("/workflows");
  return (
    <NavLink to="/workflows" className={isActive ? "active" : ""}>
      Workflow Runs
    </NavLink>
  );
}

// Sidebar link with a live count of open alerts (critical ones in red).
function AlertsNavLink() {
  const [open, setOpen] = useState<AlertCounts | null>(null);
  useEffect(() => {
    const load = () => api.listAlerts(true).then((r) => setOpen(r.open)).catch(() => {});
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);
  const count = open ? open.CRITICAL + open.WARNING : 0;
  return (
    <NavLink to="/monitoring" className={navCls}>
      Monitoring &amp; Alerts
      {count > 0 && (
        <span className={`nav-badge${open && open.CRITICAL > 0 ? " critical" : ""}`} title={`${count} open alert(s)`}>
          {count}
        </span>
      )}
    </NavLink>
  );
}

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand-row">
          <span className="sidebar-brand-mark" />
          <span className="sidebar-brand">Intent2Deploy</span>
        </div>
        <p className="sidebar-subtitle">AI DevOps platform</p>

        <nav>
          <div className="nav-group">
            <div className="nav-group-label">Overview</div>
            <div className="sidebar-nav">
              <NavLink to="/" end className={navCls}>Dashboard</NavLink>
            </div>
          </div>

          <div className="nav-group">
            <div className="nav-group-label">Workflows</div>
            <div className="sidebar-nav">
              <NavLink to="/new-workflow" className={navCls}>New Workflow</NavLink>
              <WorkflowNavLink />
            </div>
          </div>

          <div className="nav-group">
            <div className="nav-group-label">Intelligence</div>
            <div className="sidebar-nav">
              <NavLink to="/repositories" className={navCls}>Repositories</NavLink>
              <NavLink to="/evaluation" className={navCls}>Evaluation</NavLink>
            </div>
          </div>

          <div className="nav-group">
            <div className="nav-group-label">Control</div>
            <div className="sidebar-nav">
              <AlertsNavLink />
              <NavLink to="/guardrails" className={navCls}>Guardrails &amp; Safety</NavLink>
              <NavLink to="/settings" className={navCls}>Settings</NavLink>
            </div>
          </div>
        </nav>
      </aside>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/new-workflow" element={<NewWorkflowPage />} />
          <Route path="/new" element={<Navigate to="/new-workflow" replace />} />
          <Route path="/workflows" element={<WorkflowHistoryPage />} />
          <Route path="/workflows/:id" element={<WorkflowDetailPage />} />
          <Route path="/repositories" element={<RepositoriesPage />} />
          <Route path="/repositories/:id" element={<RepositoryWorkspacePage />} />
          <Route path="/repository" element={<Navigate to="/repositories" replace />} />
          <Route path="/guardrails" element={<GuardrailsPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/monitoring" element={<MonitoringPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
