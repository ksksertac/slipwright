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
export type Board = Schemas["Board"];
export type EpicView = Schemas["EpicView"];
export type StoryView = Schemas["StoryView"];
export type TaskView = Schemas["TaskView"];
export type TaskStatus = TaskView["status"];
export type ProjectProgress = Schemas["ProjectProgress"];
export type JobProgress = Schemas["JobProgress"];
export type ActivityItem = Schemas["ActivityItem"];
export type TestRun = Schemas["TestRun"];
export type User = Schemas["User"];
export type ApiToken = Schemas["ApiToken"];
export type IssuedToken = Schemas["IssuedToken"];
export type GitHubSettings = Schemas["GitHubSettings"];
export type GitHubSettingsIn = Schemas["GitHubSettingsIn"];
export type GitHubIdentity = Schemas["GitHubIdentity"];
export type GitHubRepo = Schemas["GitHubRepo"];
export type JiraSettings = Schemas["JiraSettings"];
export type JiraSettingsIn = Schemas["JiraSettingsIn"];
export type JiraTestResult = Schemas["JiraTestResult"];
export type JiraProject = Schemas["JiraProject"];
export type Profile = Schemas["Profile"];
export type RoleConfig = Schemas["RoleConfig"];
export type Permission = Schemas["Permission"];
export type TestCaseIn = Schemas["TestCaseIn"];
export type ProviderSettings = Schemas["ProviderSettings"];
export type ProviderSettingsIn = Schemas["ProviderSettingsIn"];
export type ProviderModels = Schemas["ProviderModels"];

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
