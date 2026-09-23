// The Slipwright server, as the extension host talks to it. Everything goes through here:
// the webview never holds the token and never makes a request of its own.
//
// Signing in is three calls with what the server offers today — log in for a session
// cookie, ask who that is, then issue a bearer token for this editor — after which the
// cookie is dropped and only the token is kept (in VS Code's secret storage).

export type Project = {
  id: string;
  name: string;
  description: string;
  repo_path?: string | null;
  github_repo?: string | null;
  jira_project_key?: string | null;
};

export type Job = {
  id: string;
  project_id?: string | null;
  request: string;
  state: string;
  created_at: string;
};

export type JobProgress = {
  job_id: string;
  state: string;
  pending_approval?: string | null;
};

export type Progress = {
  tasks_done: number;
  tasks_total: number;
  jobs_running: number;
  pending_approvals: number;
  jobs: JobProgress[];
};

export type WorkItem = {
  id: string;
  title: string;
  detail: string;
  kind: string;
  editable: boolean;
  domain?: string | null;
  phase?: number | null;
};

export type WorkGroup = { role: string; label: string; summary: string; items: WorkItem[] };

export type WorkList = {
  job_id: string;
  state: string;
  editable: boolean;
  plan_summary: string;
  groups: WorkGroup[];
  tasks: number;
  phases: number;
  cases: number;
};

export type Source = {
  name: string;
  label: string;
  owner?: string | null;
  token_set: boolean;
  is_default: boolean;
};

export type Repo = { full_name: string; private: boolean; description?: string | null };

export type Me = { id: string; username: string; is_admin: boolean };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type Fetch = typeof fetch;

export class SlipwrightApi {
  constructor(
    private endpoint: string,
    private token: string | null = null,
    private readonly http: Fetch = fetch,
  ) {}

  get base(): string {
    return this.endpoint.replace(/\/+$/, "");
  }

  withToken(token: string | null): SlipwrightApi {
    return new SlipwrightApi(this.endpoint, token, this.http);
  }

  /** The three-step sign-in; returns the token secret to store. */
  async signIn(username: string, password: string): Promise<{ secret: string; me: Me }> {
    const login = await this.request<Me>("POST", "/api/auth/login", { username, password });
    const cookie = login.cookie ?? "";
    const me = login.body;
    const issued = await this.request<{ secret: string }>(
      "POST",
      `/api/users/${me.id}/tokens`,
      { name: "vs code" },
      cookie,
    );
    return { secret: issued.body.secret, me };
  }

  async me(): Promise<Me> {
    return (await this.request<Me>("GET", "/api/auth/me")).body;
  }

  async version(): Promise<string> {
    return (await this.request<{ build: string }>("GET", "/api/version")).body.build;
  }

  async projects(): Promise<Project[]> {
    return (await this.request<Project[]>("GET", "/api/projects")).body;
  }

  async jobs(projectId: string): Promise<Job[]> {
    return (await this.request<Job[]>("GET", `/api/projects/${projectId}/jobs`)).body;
  }

  async progress(projectId: string): Promise<Progress> {
    return (await this.request<Progress>("GET", `/api/projects/${projectId}/progress`)).body;
  }

  async startDevelopment(projectId: string, request: string): Promise<Job> {
    return (
      await this.request<Job>("POST", `/api/projects/${projectId}/jobs`, { request })
    ).body;
  }

  async job(jobId: string): Promise<Job> {
    return (await this.request<Job>("GET", `/api/jobs/${jobId}`)).body;
  }

  async workList(jobId: string): Promise<WorkList> {
    return (await this.request<WorkList>("GET", `/api/jobs/${jobId}/worklist`)).body;
  }

  async approve(jobId: string): Promise<Job> {
    return (await this.request<Job>("POST", `/api/jobs/${jobId}/approve`)).body;
  }

  async reject(jobId: string, feedback: string): Promise<Job> {
    return (await this.request<Job>("POST", `/api/jobs/${jobId}/reject`, { feedback })).body;
  }

  async sources(): Promise<Source[]> {
    return (await this.request<Source[]>("GET", "/api/settings/sources")).body;
  }

  async repos(source: string): Promise<Repo[]> {
    return (await this.request<Repo[]>("GET", `/api/settings/sources/${source}/repos`)).body;
  }

  async openRepo(source: string, name: string, isPrivate = true): Promise<Repo> {
    return (
      await this.request<Repo>("POST", `/api/settings/sources/${source}/repos`, {
        name,
        private: isPrivate,
      })
    ).body;
  }

  async createProject(body: Record<string, unknown>): Promise<Project> {
    return (await this.request<Project>("POST", "/api/projects", body)).body;
  }

  /** The page a person opens for one of these, in a browser. */
  urlFor(kind: "project" | "job", id: string, projectId?: string): string {
    return kind === "project"
      ? `${this.base}/projects/${id}`
      : `${this.base}/projects/${projectId}/jobs/${id}`;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    cookie?: string,
  ): Promise<{ body: T; cookie?: string }> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) headers["Authorization"] = `Bearer ${this.token}`;
    if (cookie) headers["Cookie"] = cookie;
    let resp: Response;
    try {
      resp = await this.http(`${this.base}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new ApiError(`${this.base} could not be reached: ${String(err)}`, 0);
    }
    if (resp.status === 401) throw new ApiError("the server did not accept the sign-in", 401);
    if (!resp.ok) {
      let detail = "";
      try {
        const payload = (await resp.json()) as { detail?: unknown };
        detail = typeof payload.detail === "string" ? payload.detail : "";
      } catch {
        /* a body that is not JSON: the status says enough */
      }
      throw new ApiError(detail || `${method} ${path} failed (${resp.status})`, resp.status);
    }
    const text = await resp.text();
    return {
      body: (text ? JSON.parse(text) : null) as T,
      cookie: resp.headers.get("set-cookie") ?? undefined,
    };
  }
}

/** Every state a development can be in, in the words the tree shows. */
export function stateLabel(state: string): string {
  const words: Record<string, string> = {
    created: "created",
    backlog: "backlog",
    awaiting_backlog_approval: "waiting: backlog",
    architecture: "architecture",
    awaiting_architecture_approval: "waiting: the work list",
    developing: "building",
    build_gate: "build gate",
    review: "review",
    awaiting_review_approval: "waiting: review",
    qa: "QA",
    awaiting_test_approval: "waiting: tests",
    devops: "DevOps",
    awaiting_deploy_approval: "waiting: deployment",
    awaiting_decision: "waiting: your decision",
    done: "done",
    failed: "failed",
  };
  return words[state] ?? state;
}

export function isWaiting(state: string): boolean {
  return state.startsWith("awaiting_");
}
