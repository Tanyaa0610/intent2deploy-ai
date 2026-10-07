import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { NewWorkflowPage } from "./pages/NewWorkflowPage";
import { WorkflowHistoryPage } from "./pages/WorkflowHistoryPage";
import { WorkflowDetailPage } from "./pages/WorkflowDetailPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { GuardrailsPage } from "./pages/GuardrailsPage";
import { RepositoryIntelligencePage } from "./pages/RepositoryIntelligencePage";

const navLinkClass = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand-row">
          <span className="sidebar-brand-mark" />
          <span className="sidebar-brand">Intent2Deploy</span>
        </div>
        <p className="sidebar-subtitle">Engineering workspace</p>

        <nav>
          <div className="nav-group">
            <div className="nav-group-label">Workflows</div>
            <div className="sidebar-nav">
              <NavLink to="/" end className={navLinkClass}>
                Dashboard
              </NavLink>
              <NavLink to="/new-workflow" className={navLinkClass}>
                New Workflow
              </NavLink>
              <NavLink to="/workflows" className={navLinkClass}>
                Workflow History
              </NavLink>
            </div>
          </div>

          <div className="nav-group">
            <div className="nav-group-label">Intelligence</div>
            <div className="sidebar-nav">
              <NavLink to="/repository" className={navLinkClass}>
                Repository Intelligence
              </NavLink>
              <NavLink to="/evaluation" className={navLinkClass}>
                Evaluation
              </NavLink>
            </div>
          </div>

          <div className="nav-group">
            <div className="nav-group-label">Control</div>
            <div className="sidebar-nav">
              <NavLink to="/guardrails" className={navLinkClass}>
                Guardrails &amp; Safety
              </NavLink>
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
          <Route path="/repository" element={<RepositoryIntelligencePage />} />
          <Route path="/guardrails" element={<GuardrailsPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
