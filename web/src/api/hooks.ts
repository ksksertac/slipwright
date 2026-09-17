// React Query hooks for every endpoint the pages use. Query keys are structured so the
// live event stream (events.ts) can invalidate exactly what changed.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type ActivityItem,
  type AgentSummary,
  type ApiToken,
  type Board,
  type GitHubIdentity,
  type GitHubRepo,
  type GitHubSettings,
  type GitHubSettingsIn,
  type IssuedToken,
  type JiraProject,
  type JiraSettings,
  type JiraSettingsIn,
  type JiraTestResult,
  type Job,
  type NewProject,
  type Overview,
  type Project,
  type ProjectPatch,
  type ProjectProgress,
  type ProviderModels,
  type ProviderSettings,
  type ProviderSettingsIn,
  type TestCaseIn,
  type TestRun,
  type Transition,
  type User,
} from "./client";

export const keys = {
  me: ["me"] as const,
  overview: ["overview"] as const,
  agents: ["agents"] as const,
  activityAll: (role: string) => ["activity", role] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  projectJobs: (id: string) => ["projects", id, "jobs"] as const,
  board: (id: string) => ["projects", id, "board"] as const,
  progress: (id: string) => ["projects", id, "progress"] as const,
  activity: (id: string) => ["projects", id, "activity"] as const,
  testRuns: (id: string) => ["projects", id, "test-runs"] as const,
  job: (id: string) => ["jobs", id] as const,
  transition: (id: string, index: number) => ["jobs", id, "history", index] as const,
  testRun: (id: string) => ["test-runs", id] as const,
  testRunOutput: (id: string) => ["test-runs", id, "output"] as const,
  github: ["settings", "github"] as const,
  githubRepos: ["settings", "github", "repos"] as const,
  jira: ["settings", "jira"] as const,
  jiraProjects: ["settings", "jira", "projects"] as const,
  users: ["users"] as const,
  providers: ["settings", "providers"] as const,
  providerModels: (name: string) => ["settings", "providers", name, "models"] as const,
  tokens: (userId: string) => ["users", userId, "tokens"] as const,
};

// -- dashboard -------------------------------------------------------------------------

export function useOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: () => api.get<Overview>("/api/overview?recent=25"),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: keys.agents,
    queryFn: () => api.get<AgentSummary[]>("/api/agents"),
  });
}

export function useActivity_all(role: string, limit = 100) {
  return useQuery({
    queryKey: keys.activityAll(role),
    queryFn: () => api.get<ActivityItem[]>(`/api/activity?role=${role}&limit=${limit}`),
  });
}

// -- projects --------------------------------------------------------------------------

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: () => api.get<Project[]>("/api/projects") });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: keys.project(id),
    queryFn: () => api.get<Project>(`/api/projects/${id}`),
  });
}

export function useProjectJobs(id: string) {
  return useQuery({
    queryKey: keys.projectJobs(id),
    queryFn: () => api.get<Job[]>(`/api/projects/${id}/jobs`),
  });
}

export function useBoard(id: string) {
  return useQuery({
    queryKey: keys.board(id),
    queryFn: () => api.get<Board>(`/api/projects/${id}/board`),
  });
}

export function useProgress(id: string) {
  return useQuery({
    queryKey: keys.progress(id),
    queryFn: () => api.get<ProjectProgress>(`/api/projects/${id}/progress`),
  });
}

export function useActivity(id: string, limit = 200) {
  return useQuery({
    queryKey: keys.activity(id),
    queryFn: () => api.get<ActivityItem[]>(`/api/projects/${id}/activity?limit=${limit}`),
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewProject) => api.post<Project>("/api/projects", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function usePatchProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectPatch) => api.patch<Project>(`/api/projects/${id}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.project(id) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/projects/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useStartJob(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: string) => api.post<Job>(`/api/projects/${projectId}/jobs`, { request }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.project(projectId) }),
  });
}

// -- jobs ------------------------------------------------------------------------------

export function useJob(id: string, refetchInterval?: number) {
  return useQuery({
    queryKey: keys.job(id),
    queryFn: () => api.get<Job>(`/api/jobs/${id}`),
    refetchInterval,
  });
}

export function useTransition(jobId: string, index: number | null) {
  return useQuery({
    queryKey: keys.transition(jobId, index ?? -1),
    queryFn: () => api.get<Transition>(`/api/jobs/${jobId}/history/${index}`),
    enabled: index !== null,
  });
}

function useJobAction(jobId: string) {
  const qc = useQueryClient();
  return (fn: () => Promise<Job>) => ({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useApprove(jobId: string) {
  const wrap = useJobAction(jobId);
  return useMutation(wrap(() => api.post<Job>(`/api/jobs/${jobId}/approve`)));
}

export function useReject(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string) => api.post<Job>(`/api/jobs/${jobId}/reject`, { feedback }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

export function useSendMessage(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.post<Job>(`/api/jobs/${jobId}/message`, { text }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/jobs/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useSetTestCases(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (test_cases: TestCaseIn[]) =>
      api.put<Job>(`/api/jobs/${jobId}/tests`, { test_cases }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

// -- test runs -------------------------------------------------------------------------

export function useTestRuns(projectId: string) {
  return useQuery({
    queryKey: keys.testRuns(projectId),
    queryFn: () => api.get<TestRun[]>(`/api/projects/${projectId}/test-runs`),
  });
}

export function useTestRun(id: string | null) {
  return useQuery({
    queryKey: keys.testRun(id ?? ""),
    queryFn: () => api.get<TestRun>(`/api/test-runs/${id}`),
    enabled: id !== null,
  });
}

export function useTestRunOutput(id: string | null, running: boolean) {
  return useQuery({
    queryKey: keys.testRunOutput(id ?? ""),
    queryFn: () => api.text(`/api/test-runs/${id}/output`),
    enabled: id !== null,
    refetchInterval: running ? 2000 : false,
  });
}

export function useStartTestRun(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string | null) =>
      api.post<TestRun>(`/api/projects/${projectId}/test-runs`, { job_id: jobId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.testRuns(projectId) }),
  });
}

// -- settings --------------------------------------------------------------------------

export function useGitHubSettings() {
  return useQuery({
    queryKey: keys.github,
    queryFn: () => api.get<GitHubSettings>("/api/settings/github"),
  });
}

export function useSaveGitHubSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GitHubSettingsIn) => api.put<GitHubSettings>("/api/settings/github", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.github });
      void qc.invalidateQueries({ queryKey: keys.githubRepos });
    },
  });
}

export function useTestGitHub() {
  return useMutation({ mutationFn: () => api.post<GitHubIdentity>("/api/settings/github/test") });
}

export function useGitHubRepos(enabled: boolean) {
  return useQuery({
    queryKey: keys.githubRepos,
    queryFn: () => api.get<GitHubRepo[]>("/api/settings/github/repos"),
    enabled,
    retry: false,
  });
}

export function useJiraSettings() {
  return useQuery({
    queryKey: keys.jira,
    queryFn: () => api.get<JiraSettings>("/api/settings/jira"),
  });
}

export function useSaveJiraSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: JiraSettingsIn) => api.put<JiraSettings>("/api/settings/jira", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jira });
      void qc.invalidateQueries({ queryKey: keys.jiraProjects });
    },
  });
}

export function useTestJira() {
  return useMutation({ mutationFn: () => api.post<JiraTestResult>("/api/settings/jira/test") });
}

export function useJiraProjects(enabled: boolean) {
  return useQuery({
    queryKey: keys.jiraProjects,
    queryFn: () => api.get<JiraProject[]>("/api/settings/jira/projects"),
    enabled,
    retry: false,
  });
}

// -- users -----------------------------------------------------------------------------

export function useUsers() {
  return useQuery({ queryKey: keys.users, queryFn: () => api.get<User[]>("/api/users") });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string; is_admin: boolean }) =>
      api.post<User>("/api/users", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useSetPassword() {
  return useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.put<void>(`/api/users/${id}/password`, { password }),
  });
}

export function useTokens(userId: string | null) {
  return useQuery({
    queryKey: keys.tokens(userId ?? ""),
    queryFn: () => api.get<ApiToken[]>(`/api/users/${userId}/tokens`),
    enabled: userId !== null,
  });
}

export function useIssueToken(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<IssuedToken>(`/api/users/${userId}/tokens`, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.tokens(userId) }),
  });
}

export function useRevokeToken(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: string) => api.delete<ApiToken>(`/api/tokens/${tokenId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.tokens(userId) }),
  });
}

// -- model providers ---------------------------------------------------------------------

export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => api.get<ProviderSettings[]>("/api/settings/providers"),
  });
}

export function useSaveProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, ...body }: ProviderSettingsIn & { name: string }) =>
      api.put<ProviderSettings[]>(`/api/settings/providers/${name}`, body),
    onSuccess: (data) => {
      qc.setQueryData(keys.providers, data);
      void qc.invalidateQueries({ queryKey: ["settings", "providers"] });
    },
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (name: string) => api.post<ProviderModels>(`/api/settings/providers/${name}/test`),
  });
}

/** Models a configured provider offers, for the model pickers; silent when no key is set. */
export function useProviderModels(name: string | null) {
  return useQuery({
    queryKey: keys.providerModels(name ?? ""),
    queryFn: () => api.get<ProviderModels>(`/api/settings/providers/${name}/models`),
    enabled: name !== null,
    retry: false,
    staleTime: 5 * 60_000,
  });
}
