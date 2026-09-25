import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import {
  ForgotPasswordPage,
  InvitationPage,
  ResetPasswordPage,
  SignupPage,
  VerifyEmailPage,
} from "./pages/AccountPages";
import { DashboardPage } from "./pages/DashboardPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectPage } from "./pages/ProjectPage";
import { JobPage } from "./pages/JobPage";
import { SourcesSettingsPage } from "./pages/settings/SourcesSettingsPage";
import { ModelsSettingsPage } from "./pages/settings/ModelsSettingsPage";
import { JiraSettingsPage } from "./pages/settings/JiraSettingsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { AgentDetailPage } from "./pages/AgentDetailPage";
import { UsersSettingsPage } from "./pages/settings/UsersSettingsPage";
import { EmailSettingsPage } from "./pages/settings/EmailSettingsPage";
import { SupportPage } from "./pages/SupportPage";
import { useT } from "./i18n";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* reached before there is a session, or from a link in a letter */}
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/verify" element={<VerifyEmailPage />} />
      <Route path="/invitation" element={<InvitationPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset" element={<ResetPasswordPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/new" element={<NewProjectPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/projects/:projectId/:tab" element={<ProjectPage />} />
        <Route path="/projects/:projectId/jobs/:jobId" element={<JobPage />} />
        <Route path="/settings" element={<Navigate to="/settings/models" replace />} />
        <Route path="/settings/models" element={<ModelsSettingsPage />} />
        <Route path="/settings/sources" element={<SourcesSettingsPage />} />
        {/* the sources page used to be the GitHub page: old links keep working */}
        <Route path="/settings/github" element={<Navigate to="/settings/sources" replace />} />
        <Route path="/settings/jira" element={<JiraSettingsPage />} />
        <Route path="/settings/jira/:tab" element={<JiraSettingsPage />} />
        <Route path="/settings/agents" element={<Navigate to="/agents" replace />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/:role" element={<AgentDetailPage />} />
        <Route path="/agents/:role/:tab" element={<AgentDetailPage />} />
        <Route path="/settings/users" element={<UsersSettingsPage />} />
        <Route path="/settings/email" element={<EmailSettingsPage />} />
        <Route path="/settings/email/:tab" element={<EmailSettingsPage />} />
        <Route path="/support" element={<SupportPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  const tx = useT();
  return <div className="muted">{tx("Not found.")}</div>;
}
