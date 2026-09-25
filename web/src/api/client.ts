// Thin fetch wrapper over the JSON API. Types come from the generated schema so a
// renamed field on the Python side fails `tsc` here instead of a page at runtime.
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Project = Schemas["Project"];
export type ProjectPatch = Schemas["ProjectPatch"];
export type NewProject = Schemas["NewProject"];
export type Job = Schemas["Job"];
export type JobState = Job["state"];
export type Transition = Schemas["Transition"];
export type JobResult = Schemas["JobResult"];
export type WorkList = Schemas["WorkList"];
export type WorkGroup = Schemas["WorkGroup"];
export type WorkItem = Schemas["WorkItem"];
export type Version = Schemas["Version"];
export type Board = Schemas["Board"];
export type ProjectCosts = Schemas["ProjectCosts"];
export type JobCost = Schemas["JobCost"];
export type Spend = Schemas["Spend"];
export type EpicView = Schemas["EpicView"];
export type StoryView = Schemas["StoryView"];
export type TaskView = Schemas["TaskView"];
export type TaskStatus = TaskView["status"];
export type ProjectProgress = Schemas["ProjectProgress"];
export type JobProgress = Schemas["JobProgress"];
export type ActivityItem = Schemas["ActivityItem"];
export type DayActivity = Schemas["DayActivity"];
export type RoleWork = Schemas["RoleWork"];
export type TestRun = Schemas["TestRun"];
export type User = Schemas["User"];
export type Membership = Schemas["Membership"];
export type MemberStatus = Membership["status"];
export type MyTeam = Schemas["MyTeam"];
export type InvitationView = Schemas["InvitationView"];
export type RoleName = Schemas["RoleName"];
export type ApiToken = Schemas["ApiToken"];
export type IssuedToken = Schemas["IssuedToken"];
export type GitHubSettings = Schemas["GitHubSettings"];
export type SourceSettings = Schemas["SourceSettings"];
export type SourceSettingsIn = Schemas["SourceSettingsIn"];
export type SourceIdentity = Schemas["Identity"];
export type SourceRepo = Schemas["Repo"];
export type GitHubSettingsIn = Schemas["GitHubSettingsIn"];
export type GitHubIdentity = Schemas["GitHubIdentity"];
export type GitHubRepo = Schemas["GitHubRepo"];
export type JiraSettings = Schemas["JiraSettings"];
export type JiraSettingsIn = Schemas["JiraSettingsIn"];
export type JiraTestResult = Schemas["JiraTestResult"];
export type JiraSweep = Schemas["JiraSweep"];
export type JiraProject = Schemas["JiraProject"];
export type Profile = Schemas["Profile"];
export type RoleConfig = Schemas["RoleConfig"];
export type Permission = Schemas["Permission"];
export type TestCaseIn = Schemas["TestCaseIn"];
export type ProviderSettings = Schemas["ProviderSettings"];
export type Overview = Schemas["Overview"];
export type AgentSummary = Schemas["AgentSummary"];
export type AgentRouting = Schemas["AgentRouting"];
export type ProviderSettingsIn = Schemas["ProviderSettingsIn"];
export type ProviderModels = Schemas["ProviderModels"];
export type Pipeline = Schemas["Pipeline"];
export type Translations = Schemas["Translations"];
export type Onboarding = Schemas["Onboarding"];
export type LocalRepos = Schemas["LocalRepos"];
export type Lane = Schemas["Lane"];
export type StepCard = Schemas["StepCard"];
export type StepStatus = StepCard["status"];
export type StepDetail = Schemas["StepDetail"];
export type StepGroup = Schemas["StepGroup"];
export type StepItem = Schemas["StepItem"];
export type StepItemStatus = StepItem["status"];
export type StepBadge = Schemas["Badge"];
export type DesignReview = Schemas["DesignReview"];
export type DesignScreen = Schemas["DesignScreen"];
export type BatchResult = Schemas["BatchResult"];
export type BatchOutcome = Schemas["BatchOutcome"];
export type PlanEdit = Schemas["PlanEdit"];
export type BriefView = Schemas["BriefView"];
export type ProjectBrief = Schemas["ProjectBrief"];
export type BriefItem = Schemas["BriefItem"];
export type BriefCategory = NonNullable<BriefItem["category"]>;
export type BriefEdit = Schemas["BriefEdit"];
export type Intake = Schemas["Intake"];
export type IntakeQuestion = Schemas["IntakeQuestion"];
export type DeployEdit = Schemas["DeployEdit"];
export type DeployScriptIn = Schemas["DeployScriptIn"];

/** One part of the product and what it is written in. It travels inside the plan, which
 * the API types as a free-form object, so the shape is spelled out here. */
export type StackChoice = {
  domain: "backend" | "web" | "mobile" | "infra";
  language: string;
  framework?: string;
  why?: string;
};

/** The deployment proposal as it sits on a job (`job.data.deploy`). */
export type DeployPlan = {
  summary?: string;
  target: "aws" | "azure" | "none";
  services?: string[];
  scripts?: { path: string; purpose: string }[];
  notes?: string[];
};
export type MailSettings = Schemas["MailSettingsView"];
export type MailSettingsIn = Schemas["MailSettingsIn"];
export type MailTestResult = Schemas["MailTestResult"];
export type OutboxLetter = Schemas["OutboxLetter"];
export type SupportRequest = Schemas["SupportRequestView"];
export type SupportRequestIn = Schemas["SupportRequestIn"];
export type SupportCategory = SupportRequestIn["category"];
export type StandardsRule = Schemas["StandardsRule"];
export type StandardsStatus = Schemas["StandardsStatus"];
export type StandardsSettingsIn = Schemas["StandardsSettingsIn"];
export type StandardsHit = Schemas["StandardsHit"];

export type ApiPaths = keyof paths;

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

export const UNAUTHORIZED_EVENT = "slipwright:unauthorized";

/** Why the server last refused a session, when it was worth saying: the header the API
 * answers with (`removed`, `invited`). It is kept for the login page, which is where the
 * browser is about to land, and read once. */
const SIGNED_OUT_HEADER = "x-slipwright-signed-out";
const SIGNED_OUT_KEY = "slipwright:signed-out";

export function takeSignedOutReason(): string | null {
  try {
    const reason = sessionStorage.getItem(SIGNED_OUT_KEY);
    if (reason) sessionStorage.removeItem(SIGNED_OUT_KEY);
    return reason;
  } catch {
    return null; // a browser with storage turned off simply shows the plain login page
  }
}

function rememberSignedOut(resp: Response): void {
  const reason = resp.headers.get(SIGNED_OUT_HEADER);
  if (!reason) return;
  try {
    sessionStorage.setItem(SIGNED_OUT_KEY, reason);
  } catch {
    /* nothing to do: the message is a courtesy, not the mechanism */
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const resp = await fetch(path, init);
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  const contentType = resp.headers.get("content-type") ?? "";
  let data: unknown = text;
  if (contentType.includes("application/json") && text) {
    data = JSON.parse(text);
  }
  if (!resp.ok) {
    rememberSignedOut(resp);
    if (resp.status === 401 && !path.startsWith("/api/auth/login")) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? formatDetail((data as { detail: unknown }).detail)
        : text || resp.statusText;
    throw new ApiError(resp.status, detail);
  }
  return data as T;
}

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // pydantic validation errors
    return detail
      .map((d) => {
        const loc = Array.isArray(d.loc)
          ? d.loc.filter((p: unknown) => p !== "body").join(".")
          : "";
        return loc ? `${loc}: ${d.msg}` : String(d.msg ?? d);
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
  text: async (path: string): Promise<string> => {
    const resp = await fetch(path, { credentials: "same-origin" });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return resp.text();
  },
};

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error) return error.message;
  return String(error);
}
