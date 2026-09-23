// Slipwright in the editor (M1): sign in, see the projects and their developments, start a
// development, open one in the browser. The token lives in VS Code's secret storage and
// every request is made here, in the extension host — never in a view.
import * as vscode from "vscode";
import { ApiError, SlipwrightApi } from "./api";
import { ProjectsProvider, type Node } from "./tree";

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
