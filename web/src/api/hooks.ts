// React Query hooks for every endpoint the pages use. Query keys are structured so the
// live event stream (events.ts) can invalidate exactly what changed.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type ActivityItem,
  type AgentRouting,
  type AgentSummary,
  type ApiToken,
  type BatchResult,
  type Board,
  type BriefEdit,
  type BriefView,
  type DeployEdit,
  type DesignReview,
  type GitHubIdentity,
  type GitHubRepo,
  type GitHubSettings,
  type GitHubSettingsIn,
  type IssuedToken,
  type JiraProject,
  type JiraSettings,
  type JiraSettingsIn,
  type JiraSweep,
  type JiraTestResult,
  type LocalRepos,
  type Membership,
  type MyTeam,
  type MailSettings,
  type MailSettingsIn,
  type MailTestResult,
  type OutboxLetter,
  type Job,
  type JobResult,
  type NewProject,
  type SourceIdentity,
  type SupportRequest,
  type SupportRequestIn,
  type SourceRepo,
  type SourceSettings,
  type SourceSettingsIn,
  type Overview,
  type WorkList,
  type Profile,
  type Pipeline,
  type PlanEdit,
  type Project,
  type ProjectCosts,
  type ProjectPatch,
  type StandardsHit,
  type Translations,
  type StepDetail,
  type StandardsRule,
  type StandardsSettingsIn,
  type StandardsStatus,
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
  myTeam: ["me", "team"] as const,
  agentMembers: (role: string) => ["agents", role, "members"] as const,
  overview: ["overview"] as const,
  agents: ["agents"] as const,
  onboarding: ["onboarding"] as const,
  activityAll: (role: string) => ["activity", role] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  projectJobs: (id: string) => ["projects", id, "jobs"] as const,
  board: (id: string) => ["projects", id, "board"] as const,
  progress: (id: string) => ["projects", id, "progress"] as const,
  pipeline: (id: string) => ["projects", id, "pipeline"] as const,
  activity: (id: string) => ["projects", id, "activity"] as const,
  costs: (id: string) => ["projects", id, "costs"] as const,
  translations: (id: string | null, lang: string) => ["translations", id ?? "all", lang] as const,
  testRuns: (id: string) => ["projects", id, "test-runs"] as const,
  brief: (id: string) => ["projects", id, "brief"] as const,
  job: (id: string) => ["jobs", id] as const,
  transition: (id: string, index: number) => ["jobs", id, "history", index] as const,
  step: (id: string, key: string) => ["jobs", id, "steps", key] as const,
  design: (id: string) => ["jobs", id, "design"] as const,
  jobResult: (id: string) => ["jobs", id, "result"] as const,
  workList: (id: string) => ["jobs", id, "worklist"] as const,
  testRun: (id: string) => ["test-runs", id] as const,
  testRunOutput: (id: string) => ["test-runs", id, "output"] as const,
  github: ["settings", "github"] as const,
  sources: ["settings", "sources"] as const,
  sourceRepos: (name: string) => ["settings", "sources", name, "repos"] as const,
  githubRepos: ["settings", "github", "repos"] as const,
  jira: ["settings", "jira"] as const,
  jiraProjects: ["settings", "jira", "projects"] as const,
  users: ["users"] as const,
  mail: ["settings", "mail"] as const,
  mailOutbox: ["settings", "mail", "outbox"] as const,
  support: ["support"] as const,
  supportMine: ["support", "mine"] as const,
  providers: ["settings", "providers"] as const,
  providerModels: (name: string) => ["settings", "providers", name, "models"] as const,
  tokens: (userId: string) => ["users", userId, "tokens"] as const,
  standards: ["standards", "status"] as const,
  standardsRules: (scope: string, domain: string) => ["standards", "rules", scope, domain] as const,
  standardsSearch: (scope: string, domain: string, q: string) =>
    ["standards", "search", scope, domain, q] as const,
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

/** Pin an agent to a provider and model for every project (admin); both empty clears it. */
export function useAssignAgent(role: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AgentRouting) => api.put<AgentSummary>(`/api/agents/${role}/routing`, body),
    onSuccess: (card) => {
      qc.setQueryData<AgentSummary[]>(keys.agents, (old) =>
        old ? old.map((a) => (a.role === card.role ? card : a)) : old,
      );
      void qc.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

/** The agents this person holds. An owner holds none and may do everything. */
export function useMyTeam() {
  return useQuery({
    queryKey: keys.myTeam,
    queryFn: () => api.get<MyTeam>("/api/me/team"),
    staleTime: 60_000,
  });
}

/** Who is on one agent, invitations included. */
export function useAgentMembers(role: string, enabled = true) {
  return useQuery({
    queryKey: keys.agentMembers(role),
    queryFn: () => api.get<Membership[]>(`/api/agents/${role}/members`),
    enabled,
  });
}

/** Put an address on an agent; the letter goes out from the server. */
export function useInviteToAgent(role: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name?: string; lang?: string }) =>
      api.post<Membership>(`/api/agents/${role}/members`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.agentMembers(role) });
      void qc.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

/** Put one person on several agents at once: one invitation, one letter. */
export function useInviteToTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name?: string; lang?: string; roles: string[] }) =>
      api.post<Membership[]>("/api/team/members", body),
    onSuccess: (_data, body) => {
      for (const role of body.roles) {
        void qc.invalidateQueries({ queryKey: keys.agentMembers(role) });
      }
      void qc.invalidateQueries({ queryKey: keys.agents });
      void qc.invalidateQueries({ queryKey: keys.myTeam });
    },
  });
}

/** Take somebody off an agent -- or, asked by that person, step off it. */
export function useEndMembership(role: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) =>
      api.delete<Membership>(`/api/agents/${role}/members/${memberId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.agentMembers(role) });
      void qc.invalidateQueries({ queryKey: keys.agents });
      void qc.invalidateQueries({ queryKey: keys.myTeam });
    },
  });
}

export function useActivity_all(role: string, limit = 100) {
  return useQuery({
    queryKey: keys.activityAll(role),
    queryFn: () => api.get<ActivityItem[]>(`/api/activity?role=${role}&limit=${limit}`),
  });
}

// -- the project brief: what the agents are told the project is (T11.1-T11.3) ----------

/** The brief plus whether this project is read (analysis) or asked about (intake). */
export function useBrief(projectId: string, poll = false) {
  return useQuery({
    queryKey: keys.brief(projectId),
    queryFn: () => api.get<BriefView>(`/api/projects/${projectId}/brief`),
    // while an agent is working there is nothing to push an update: ask again
    refetchInterval: poll ? 2000 : false,
  });
}

/** Read the checkout and propose the brief. The answer arrives on the brief itself. */
export function useAnalyseProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<BriefView>(`/api/projects/${projectId}/brief/analysis`),
    onSuccess: (view) => qc.setQueryData(keys.brief(projectId), view),
  });
}

/** Answer the questions on the table (if any) and ask for the next round. */
export function useIntake(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (answers: Record<string, string>) =>
      api.post<BriefView>(`/api/projects/${projectId}/brief/intake`, { answers }),
    onSuccess: (view) => qc.setQueryData(keys.brief(projectId), view),
  });
}

/** Save the person's edits; approving is what lets an agent read any of it. */
export function useSaveBrief(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BriefEdit) => api.put<BriefView>(`/api/projects/${projectId}/brief`, body),
    onSuccess: (view) => qc.setQueryData(keys.brief(projectId), view),
  });
}

// -- projects --------------------------------------------------------------------------

export function useLocalRepos(enabled: boolean) {
  return useQuery({
    queryKey: ["local-repos"],
    queryFn: () => api.get<LocalRepos>("/api/local-repos"),
    enabled,
    staleTime: 30_000,
  });
}

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

export function usePipeline(id: string) {
  return useQuery({
    queryKey: keys.pipeline(id),
    queryFn: () => api.get<Pipeline>(`/api/projects/${id}/pipeline`),
  });
}

export function useActivity(id: string, limit = 200) {
  return useQuery({
    queryKey: keys.activity(id),
    queryFn: () => api.get<ActivityItem[]>(`/api/projects/${id}/activity?limit=${limit}`),
  });
}

/** What the agents wrote, in the language the platform is set to.
 *
 * The agents write in the project's language and the page is read in the platform's; when
 * they differ this is the bridge, keyed by the source string. It is deliberately not tied
 * to the live event stream: a translation of a sentence never changes, and a project
 * opened in the other language fills in over a few polls as the server works through it.
 * ``projectId: null`` asks across every project, for the dashboard's feed. */
export function useTranslations(projectId: string | null, lang: string) {
  const path = projectId
    ? `/api/projects/${projectId}/translations?lang=${lang}`
    : `/api/translations?lang=${lang}`;
  return useQuery({
    queryKey: keys.translations(projectId, lang),
    queryFn: () => api.get<Translations>(path),
    // the server translates a capped number of new strings per call and serves the rest
    // from its cache, so a large project fills in over a few polls rather than hanging
    refetchInterval: 20_000,
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

/** What each agent is about to do, for the list shown before a development starts. */
export function useWorkList(id: string) {
  return useQuery({
    queryKey: keys.workList(id),
    queryFn: () => api.get<WorkList>(`/api/jobs/${id}/worklist`),
  });
}

export function useJobResult(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.jobResult(id),
    queryFn: () => api.get<JobResult>(`/api/jobs/${id}/result`),
    enabled,
  });
}

export function useTransition(jobId: string, index: number | null) {
  return useQuery({
    queryKey: keys.transition(jobId, index ?? -1),
    queryFn: () => api.get<Transition>(`/api/jobs/${jobId}/history/${index}`),
    enabled: index !== null,
  });
}

/** Everything one pipeline step produced: the lists the side panel lays out. */
export function useStepDetail(jobId: string, stepKey: string | null) {
  return useQuery({
    queryKey: keys.step(jobId, stepKey ?? ""),
    queryFn: () =>
      api.get<StepDetail>(`/api/jobs/${jobId}/steps/${encodeURIComponent(stepKey ?? "")}`),
    enabled: stepKey !== null,
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

/** The screens of a development and where each one stands, for the design gate. */
export function useDesignReview(jobId: string, enabled = true) {
  return useQuery({
    queryKey: keys.design(jobId),
    queryFn: () => api.get<DesignReview>(`/api/jobs/${jobId}/design`),
    enabled,
  });
}

/** Sign off one screen, or send it back with what should be different. */
export function useReviewScreen(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ok, feedback }: { id: string; ok: boolean; feedback?: string }) =>
      api.post<Job>(`/api/jobs/${jobId}/design/${encodeURIComponent(id)}`, {
        ok,
        feedback: feedback ?? "",
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.design(jobId) });
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      // the lane, the board and the dashboard all read where this development is
      void qc.invalidateQueries({ queryKey: keys.projects });
      void qc.invalidateQueries({ queryKey: keys.overview });
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

export function useUndoAutoApproval(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string) => api.post<Job>(`/api/jobs/${jobId}/undo`, { feedback }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

export function useSendMessage(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.post<Job>(`/api/jobs/${jobId}/message`, { text }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

/** Run one finished step again: the tests, or the DevOps push and pull request. */
export function useRerunStep(jobId: string, projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (step: "test_cases" | "tests" | "devops") =>
      api.post<Job>(`/api/jobs/${jobId}/rerun`, { step }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      void qc.invalidateQueries({ queryKey: keys.pipeline(projectId) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

/** Plan a failed development a different way: back to the Product Owner and the Architect
 * with what should be tried instead, rather than back to the step that failed. */
export function useReplanJob(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (note: string) => api.post<Job>(`/api/jobs/${jobId}/replan`, { note }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      void qc.invalidateQueries({ queryKey: keys.projects });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

export function useRetryJob(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string | null) =>
      api.post<Job>(`/api/jobs/${jobId}/retry`, feedback ? { feedback } : {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.job(jobId) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/jobs/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useSetPlan(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (plan: PlanEdit) => api.put<Job>(`/api/jobs/${jobId}/plan`, plan),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

/** Edit the deployment proposal while the job waits at the deployment gate (T11.6). */
export function useSetDeploy(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (plan: DeployEdit) => api.put<Job>(`/api/jobs/${jobId}/deploy`, plan),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

export function useSetBacklog(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (breakdown: Record<string, unknown>) =>
      api.put<Job>(`/api/jobs/${jobId}/backlog`, { breakdown }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

export function useSetProfile(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profile: Profile) => api.put<Job>(`/api/jobs/${jobId}/profile`, profile),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.job(jobId) }),
  });
}

/** Approve several gates at once; every job's queries are refreshed afterwards. */
export function useBatchApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (job_ids: string[]) => api.post<BatchResult>("/api/jobs/approve", { job_ids }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.projects });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

export function useBatchReject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { job_ids: string[]; feedback: string }) =>
      api.post<BatchResult>("/api/jobs/reject", args),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.projects });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
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

/** Who the stored token belongs to; re-checked whenever the token changes. */
export function useGitHubIdentity(enabled: boolean, tokenHint: string | null) {
  return useQuery({
    queryKey: [...keys.github, "identity", tokenHint] as const,
    queryFn: () => api.post<GitHubIdentity>("/api/settings/github/test"),
    enabled,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useGitHubRepos(enabled: boolean) {
  return useQuery({
    queryKey: keys.githubRepos,
    queryFn: () => api.get<GitHubRepo[]>("/api/settings/github/repos"),
    enabled,
    retry: false,
  });
}

/** What this project's developments cost, what they were expected to, and the gap. */
export function useCosts(projectId: string) {
  return useQuery({
    queryKey: keys.costs(projectId),
    queryFn: () => api.get<ProjectCosts>(`/api/projects/${projectId}/costs`),
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

export function useJiraSweep() {
  return useQuery({
    queryKey: ["settings", "jira", "sweep"],
    queryFn: () => api.get<JiraSweep | null>("/api/settings/jira/sweep"),
  });
}

export function useRunJiraSweep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<JiraSweep>("/api/settings/jira/sweep"),
    onSuccess: (data) => qc.setQueryData(["settings", "jira", "sweep"], data),
  });
}

export function useTestJira() {
  return useMutation({ mutationFn: () => api.post<JiraTestResult>("/api/settings/jira/test") });
}

/** Open a Scrum project on the connected Jira, then show it in the picker straight away. */
export function useCreateJiraProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { key: string; name: string }) =>
      api.post<JiraProject>("/api/settings/jira/projects", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.jiraProjects }),
  });
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

export function useSources() {
  return useQuery({
    queryKey: keys.sources,
    queryFn: () => api.get<SourceSettings[]>("/api/settings/sources"),
  });
}

export function useSaveSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, ...body }: SourceSettingsIn & { name: string }) =>
      api.put<SourceSettings[]>(`/api/settings/sources/${name}`, body),
    onSuccess: (data) => {
      qc.setQueryData(keys.sources, data);
      void qc.invalidateQueries({ queryKey: keys.github });
    },
  });
}

export function useTestSource() {
  return useMutation({
    mutationFn: (name: string) => api.post<SourceIdentity>(`/api/settings/sources/${name}/test`),
  });
}

/** The repositories a connected source can see, for the new-project picker. */
export function useSourceRepos(name: string | null) {
  return useQuery({
    queryKey: keys.sourceRepos(name ?? ""),
    queryFn: () => api.get<SourceRepo[]>(`/api/settings/sources/${name}/repos`),
    enabled: name !== null,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useCreateSourceRepo(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; private?: boolean; description?: string }) =>
      api.post<SourceRepo>(`/api/settings/sources/${name}/repos`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sourceRepos(name) }),
  });
}

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

// -- standards (T9.6) ------------------------------------------------------------------

function scopeParam(projectId: string | null): string {
  return projectId ? `project_id=${encodeURIComponent(projectId)}` : "";
}

export function useStandardsStatus() {
  return useQuery({
    queryKey: keys.standards,
    queryFn: () => api.get<StandardsStatus>("/api/settings/standards"),
  });
}

export function useSaveStandardsSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StandardsSettingsIn) => api.put("/api/settings/standards", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.standards }),
  });
}

export function useReindexStandards() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string | null) =>
      api.post<StandardsStatus>(`/api/settings/standards/reindex?${scopeParam(projectId)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["standards"] }),
  });
}

// One rule = one "##" section; the id ("<path>:<n>") is what the server hands back.
export function useStandardsRules(projectId: string | null, domain: string) {
  return useQuery({
    queryKey: keys.standardsRules(projectId ?? "global", domain),
    queryFn: () =>
      api.get<StandardsRule[]>(
        `/api/standards/rules?domain=${encodeURIComponent(domain)}&${scopeParam(projectId)}`,
      ),
  });
}

export function useCreateStandardsRule(projectId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { domain: string; heading: string; text: string }) =>
      api.post<StandardsRule>("/api/standards/rules", { ...args, project_id: projectId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["standards"] }),
  });
}

export function useSaveStandardsRule(projectId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: string; heading: string; text: string }) =>
      api.put<StandardsRule>(`/api/standards/rules/${args.id}`, {
        heading: args.heading,
        text: args.text,
        project_id: projectId,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["standards"] }),
  });
}

export function useDeleteStandardsRule(projectId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/api/standards/rules/${id}?${scopeParam(projectId)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["standards"] }),
  });
}

export function useStandardsSearch(projectId: string | null, domain: string, q: string) {
  return useQuery({
    queryKey: keys.standardsSearch(projectId ?? "global", domain, q),
    queryFn: () =>
      api.get<StandardsHit[]>(
        `/api/settings/standards/search?q=${encodeURIComponent(q)}&domain=${encodeURIComponent(
          domain,
        )}&k=6&${scopeParam(projectId)}`,
      ),
    enabled: q.trim().length > 0,
  });
}

// -- email and support -------------------------------------------------------------------

/** How mail leaves this installation. Admin-only on the server, so the hook is only
 *  mounted from the email page. */
export function useMailSettings(enabled = true) {
  return useQuery({
    queryKey: keys.mail,
    queryFn: () => api.get<MailSettings>("/api/settings/mail"),
    enabled,
    retry: false,
  });
}

export function useSaveMailSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: MailSettingsIn) => api.put<MailSettings>("/api/settings/mail", body),
    onSuccess: (data) => {
      qc.setQueryData(keys.mail, data);
      void qc.invalidateQueries({ queryKey: keys.mailOutbox });
    },
  });
}

/** Post one message with the settings as they stand, so a mistake surfaces here rather
 *  than to somebody who never got their verification link. */
export function useTestMailSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { to: string; lang: "tr" | "en" }) =>
      api.post<MailTestResult>("/api/settings/mail/test", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.mailOutbox }),
  });
}

/** Letters held back because no SMTP is configured. */
export function useMailOutbox(enabled = true) {
  return useQuery({
    queryKey: keys.mailOutbox,
    queryFn: () => api.get<OutboxLetter[]>("/api/settings/mail/outbox?limit=20"),
    enabled,
    retry: false,
  });
}

export function useSendSupportRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SupportRequestIn) => api.post<SupportRequest>("/api/support", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.supportMine });
      void qc.invalidateQueries({ queryKey: keys.support });
    },
  });
}

export function useMySupportRequests() {
  return useQuery({
    queryKey: keys.supportMine,
    queryFn: () => api.get<SupportRequest[]>("/api/support/mine"),
  });
}

/** Everything anybody wrote. Admin-only; mounted from the email settings page. */
export function useAllSupportRequests(enabled = true) {
  return useQuery({
    queryKey: keys.support,
    queryFn: () => api.get<SupportRequest[]>("/api/support"),
    enabled,
    retry: false,
  });
}

export function useSetSupportStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "open" | "closed" }) =>
      api.put<SupportRequest>(`/api/support/${id}/status`, { status }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.support });
      void qc.invalidateQueries({ queryKey: keys.supportMine });
    },
  });
}
