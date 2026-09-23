// Slipwright in the editor: sign in, watch the projects and their developments, read the
// work list of one and approve it, start a development, open a new project. The token lives
// in VS Code's secret storage and every request is made here, in the extension host — never
// in a view, which only ever receives what the host sends it.
import * as vscode from "vscode";
import { ApiError, SlipwrightApi, isWaiting, type Project } from "./api";
import { DevelopmentPanel } from "./panel";
import { EventStream, type ServerEvent } from "./stream";
import { ProjectsProvider, headline, type Node } from "./tree";

const TOKEN_KEY = "slipwright.token";

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  let token = (await context.secrets.get(TOKEN_KEY)) ?? null;
  let api = new SlipwrightApi(endpoint(), token);

  const tree = new ProjectsProvider(api, () => token !== null);
  const view = vscode.window.createTreeView("slipwright.projects", { treeDataProvider: tree });
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = "slipwright.projects.focus";
  context.subscriptions.push(view, status, tree as unknown as vscode.Disposable);

  const useToken = async (next: string | null): Promise<void> => {
    token = next;
    api = new SlipwrightApi(endpoint(), token);
    tree.setApi(api);
    DevelopmentPanel.forJob("*")?.setApi(api);
    if (next === null) await context.secrets.delete(TOKEN_KEY);
    else await context.secrets.store(TOKEN_KEY, next);
    await vscode.commands.executeCommand("setContext", "slipwright.signedIn", next !== null);
    refresh();
  };

  const refresh = (): void => {
    tree.refresh();
    // the count is what the tree last read; the status bar is a glance, not a poll
    setTimeout(() => {
      status.text = tree.waiting > 0 ? `$(bell-dot) ${tree.waiting}` : "$(check) Slipwright";
      status.tooltip =
        tree.waiting > 0
          ? `${tree.waiting} gate(s) waiting for you`
          : "Slipwright: nothing waits for you";
      status.show();
    }, 400);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("slipwright.signIn", async () => {
      const where = await vscode.window.showInputBox({
        prompt: "Slipwright server",
        value: endpoint(),
        ignoreFocusOut: true,
      });
      if (!where) return;
      const username = await vscode.window.showInputBox({
        prompt: "Username",
        ignoreFocusOut: true,
      });
      if (!username) return;
      const password = await vscode.window.showInputBox({
        prompt: "Password",
        password: true,
        ignoreFocusOut: true,
      });
      if (password === undefined) return;
      await vscode.workspace
        .getConfiguration("slipwright")
        .update("endpoint", where, vscode.ConfigurationTarget.Global);
      try {
        const fresh = new SlipwrightApi(where);
        const { secret, me } = await fresh.signIn(username, password);
        await useToken(secret);
        vscode.window.showInformationMessage(`Slipwright: signed in as ${me.username}.`);
      } catch (err) {
        vscode.window.showErrorMessage(`Slipwright: ${message(err)}`);
      }
    }),

    vscode.commands.registerCommand("slipwright.signOut", async () => {
      await useToken(null);
      vscode.window.showInformationMessage("Slipwright: signed out.");
    }),

    vscode.commands.registerCommand("slipwright.refresh", refresh),

    vscode.commands.registerCommand("slipwright.newDevelopment", async (node?: Node) => {
      const project = await pickProject(api, node);
      if (!project) return;
      const request = await vscode.window.showInputBox({
        prompt: `What should the agents build in ${project.name}?`,
        placeHolder: "e.g. add a /health endpoint that reports the database status",
        ignoreFocusOut: true,
      });
      if (!request?.trim()) return;
      try {
        const job = await api.startDevelopment(project.id, request.trim());
        refresh();
        const open = "Open in browser";
        const choice = await vscode.window.showInformationMessage(
          `Slipwright: planning “${request.trim().slice(0, 40)}…”.`,
          open,
        );
        if (choice === open) {
          await vscode.env.openExternal(
            vscode.Uri.parse(api.urlFor("job", job.id, project.id)),
          );
        }
      } catch (err) {
        vscode.window.showErrorMessage(`Slipwright: ${message(err)}`);
      }
    }),

    vscode.commands.registerCommand(
      "slipwright.openDevelopment",
      async (nodeOrId?: Node | string) => {
        let jobId: string | undefined;
        let projectId: string | undefined;
        let title = "Development";
        if (typeof nodeOrId === "string") {
          jobId = nodeOrId;
          try {
            const job = await api.job(jobId);
            projectId = job.project_id ?? undefined;
            title = headline(job.request, 40);
          } catch {
            /* the tree will say what is wrong; the panel can still open */
          }
        } else if (nodeOrId && nodeOrId.kind === "job") {
          jobId = nodeOrId.job.id;
          projectId = nodeOrId.project.id;
          title = headline(nodeOrId.job.request, 40);
        }
        if (!jobId || !projectId) return;
        DevelopmentPanel.show(context, api, jobId, projectId, title);
      },
    ),

    vscode.commands.registerCommand("slipwright.newProject", async () => {
      try {
        await newProject(api);
        refresh();
      } catch (err) {
        vscode.window.showErrorMessage(`Slipwright: ${message(err)}`);
      }
    }),

    vscode.commands.registerCommand("slipwright.openInBrowser", async (node?: Node) => {
      if (!node || node.kind === "message") return;
      const url =
        node.kind === "project"
          ? api.urlFor("project", node.project.id)
          : api.urlFor("job", node.job.id, node.project.id);
      await vscode.env.openExternal(vscode.Uri.parse(url));
    }),

    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("slipwright.endpoint")) void useToken(token);
    }),
  );

  const announced = new Set<string>();
  const stream = new EventStream(
    endpoint,
    () => token,
    (event: ServerEvent) => void onServerEvent(event),
  );
  stream.start();
  context.subscriptions.push({ dispose: () => stream.stop() });

  async function onServerEvent(event: ServerEvent): Promise<void> {
    if (event.job_id) void DevelopmentPanel.forJob(event.job_id)?.refresh();
    refresh();
    const state = String((event.payload as { state?: string } | undefined)?.state ?? "");
    if (!event.job_id || !isWaiting(state)) return;
    const key = `${event.job_id}:${state}`;
    if (announced.has(key)) return;
    announced.add(key);
    const open = "Open";
    const choice = await vscode.window.showInformationMessage(
      "Slipwright: a step is waiting for you.",
      open,
    );
    if (choice === open) {
      await vscode.commands.executeCommand("slipwright.openDevelopment", event.job_id);
    }
  }

  await vscode.commands.executeCommand("setContext", "slipwright.signedIn", token !== null);
  refresh();
  const every = Math.max(5, config<number>("refreshSeconds", 20)) * 1000;
  const timer = setInterval(refresh, every);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

export function deactivate(): void {
  /* the tree and the status bar are disposed with the context */
}

async function pickProject(
  api: SlipwrightApi,
  node?: Node,
): Promise<{ id: string; name: string } | undefined> {
  if (node && node.kind !== "message") return node.project;
  const projects = await api.projects();
  if (projects.length === 0) {
    vscode.window.showWarningMessage("Slipwright: there are no projects yet.");
    return undefined;
  }
  if (projects.length === 1) return projects[0];
  const pick = await vscode.window.showQuickPick(
    projects.map((p) => ({ label: p.name, description: p.description, id: p.id })),
    { title: "Which project?" },
  );
  return pick ? { id: pick.id, name: pick.label } : undefined;
}

/** New project: the source, the repository (an existing one or one opened now), the
 * language the agents write in, and optionally the first thing to build. */
async function newProject(api: SlipwrightApi): Promise<Project | undefined> {
  const name = await vscode.window.showInputBox({ prompt: "Project name", ignoreFocusOut: true });
  if (!name?.trim()) return undefined;
  const sources = (await api.sources()).filter((s) => s.token_set);
  const choices = [
    ...sources.map((s) => ({ label: s.label, id: s.name })),
    { label: "Local checkout on the server", id: "local" },
  ];
  const source = await vscode.window.showQuickPick(choices, { title: "Where does the code live?" });
  if (!source) return undefined;

  const body: Record<string, unknown> = { name: name.trim(), description: "" };
  if (source.id === "local") {
    const path = await vscode.window.showInputBox({
      prompt: "Path on the server (as the server sees it)",
      placeHolder: "/repos/my-service",
      ignoreFocusOut: true,
    });
    if (!path?.trim()) return undefined;
    body.repo_path = path.trim();
  } else {
    body.source = source.id;
    const mode = await vscode.window.showQuickPick(
      [
        { label: "An existing repository", id: "existing" },
        { label: "Open a new repository", id: "new" },
      ],
      { title: `On ${source.label}` },
    );
    if (!mode) return undefined;
    if (mode.id === "new") {
      const repoName = await vscode.window.showInputBox({
        prompt: "Name of the new repository",
        value: name.trim(),
        ignoreFocusOut: true,
      });
      if (!repoName?.trim()) return undefined;
      const made = await api.openRepo(source.id, repoName.trim());
      body.github_repo = made.full_name;
    } else {
      const repos = await api.repos(source.id);
      const pick = await vscode.window.showQuickPick(
        repos.map((r) => ({ label: r.full_name, description: r.private ? "private" : "" })),
        { title: "Which repository?" },
      );
      if (!pick) return undefined;
      body.github_repo = pick.label;
    }
  }

  const language = await vscode.window.showQuickPick(
    [
      { label: "Türkçe", id: "tr" },
      { label: "English", id: "en" },
    ],
    { title: "Which language do the agents write in?" },
  );
  body.language = language?.id ?? "tr";

  const project = await api.createProject(body);
  const first = await vscode.window.showInputBox({
    prompt: "What should the agents build first? (optional)",
    ignoreFocusOut: true,
  });
  if (first?.trim()) await api.startDevelopment(project.id, first.trim());
  vscode.window.showInformationMessage(`Slipwright: ${project.name} is ready.`);
  return project;
}

function endpoint(): string {
  return config<string>("endpoint", "http://localhost:8500");
}

function config<T>(key: string, fallback: T): T {
  return vscode.workspace.getConfiguration("slipwright").get<T>(key) ?? fallback;
}

export function message(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : String(err);
}
