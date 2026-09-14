import { NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { NewWorkflowPage } from "./pages/NewWorkflowPage";
import { WorkflowDetailPage } from "./pages/WorkflowDetailPage";
import { EvaluationPage } from "./pages/EvaluationPage";

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
          <NavLink to="/new" className={({ isActive }) => (isActive ? "active" : "")}>
            New Workflow
          </NavLink>
          <NavLink to="/evaluation" className={({ isActive }) => (isActive ? "active" : "")}>
            Evaluation
          </NavLink>
        </nav>
      </aside>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/new" element={<NewWorkflowPage />} />
          <Route path="/workflows/:id" element={<WorkflowDetailPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
