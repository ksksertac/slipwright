import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectPage } from "./pages/ProjectPage";
import { JobPage } from "./pages/JobPage";
import { GitHubSettingsPage } from "./pages/settings/GitHubSettingsPage";
import { ModelsSettingsPage } from "./pages/settings/ModelsSettingsPage";
import { JiraSettingsPage } from "./pages/settings/JiraSettingsPage";
import { AgentsSettingsPage } from "./pages/settings/AgentsSettingsPage";
import { UsersSettingsPage } from "./pages/settings/UsersSettingsPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/new" element={<NewProjectPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/projects/:projectId/:tab" element={<ProjectPage />} />
        <Route path="/projects/:projectId/jobs/:jobId" element={<JobPage />} />
        <Route path="/settings" element={<Navigate to="/settings/models" replace />} />
        <Route path="/settings/models" element={<ModelsSettingsPage />} />
        <Route path="/settings/github" element={<GitHubSettingsPage />} />
        <Route path="/settings/jira" element={<JiraSettingsPage />} />
        <Route path="/settings/agents" element={<AgentsSettingsPage />} />
        <Route path="/settings/users" element={<UsersSettingsPage />} />
        <Route path="*" element={<div className="muted">Not found.</div>} />
      </Route>
    </Routes>
  );
}
