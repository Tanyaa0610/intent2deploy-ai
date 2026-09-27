import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { NewWorkflowPage } from "./pages/NewWorkflowPage";
import { WorkflowDetailPage } from "./pages/WorkflowDetailPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { GuardrailsPage } from "./pages/GuardrailsPage";
import { RepositoryIntelligencePage } from "./pages/RepositoryIntelligencePage";

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">Intent2Deploy AI</div>
        <div className="sidebar-subtitle">From developer intent to executable, validated DevOps workflow</div>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Dashboard
          </NavLink>
          <NavLink to="/new-workflow" className={({ isActive }) => (isActive ? "active" : "")}>
            New Workflow
          </NavLink>
          <NavLink to="/repository" className={({ isActive }) => (isActive ? "active" : "")}>
            Repository Intelligence
          </NavLink>
          <NavLink to="/guardrails" className={({ isActive }) => (isActive ? "active" : "")}>
            Guardrails & Safety
          </NavLink>
          <NavLink to="/evaluation" className={({ isActive }) => (isActive ? "active" : "")}>
            Evaluation
          </NavLink>
        </nav>
      </aside>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/new-workflow" element={<NewWorkflowPage />} />
          <Route path="/new" element={<Navigate to="/new-workflow" replace />} />
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
