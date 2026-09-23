// The project tree: projects, and under each one its developments with the state they are
// in. What waits for a person is marked, because that is the only row anybody has to act on.
import * as vscode from "vscode";
import { isWaiting, stateLabel, type Job, type Project, type SlipwrightApi } from "./api";

export type Node =
  | { kind: "project"; project: Project; waiting: number }
  | { kind: "job"; job: Job; project: Project }
  | { kind: "message"; text: string; command?: vscode.Command };

export class ProjectsProvider implements vscode.TreeDataProvider<Node> {
  private readonly changed = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  /** How many gates are waiting across every project, for the status bar. */
  waiting = 0;

  constructor(
    private api: SlipwrightApi,
    private signedIn: () => boolean,
  ) {}

  setApi(api: SlipwrightApi): void {
    this.api = api;
  }

  refresh(): void {
    this.changed.fire(undefined);
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === "message") {
      const item = new vscode.TreeItem(node.text, vscode.TreeItemCollapsibleState.None);
      item.command = node.command;
      return item;
    }
    if (node.kind === "project") {
      const item = new vscode.TreeItem(
        node.project.name,
        vscode.TreeItemCollapsibleState.Collapsed,
      );
      item.contextValue = "project";
      item.id = `project:${node.project.id}`;
      item.description =
        node.waiting > 0 ? `${node.waiting} waiting for you` : node.project.description;
      item.iconPath = new vscode.ThemeIcon(node.waiting > 0 ? "bell-dot" : "folder");
      item.tooltip = node.project.repo_path ?? node.project.github_repo ?? undefined;
      return item;
    }
    const waiting = isWaiting(node.job.state);
    const item = new vscode.TreeItem(headline(node.job.request), vscode.TreeItemCollapsibleState.None);
    item.contextValue = "job";
    item.id = `job:${node.job.id}`;
    item.description = stateLabel(node.job.state);
    item.iconPath = new vscode.ThemeIcon(icon(node.job.state));
    item.tooltip = new vscode.MarkdownString(node.job.request);
    if (waiting) item.resourceUri = undefined;
    item.command = {
      command: "slipwright.openInBrowser",
      title: "Open",
      arguments: [node],
    };
    return item;
  }

  async getChildren(node?: Node): Promise<Node[]> {
    if (!this.signedIn()) {
      return [
        {
          kind: "message",
          text: "Sign in to a Slipwright server…",
          command: { command: "slipwright.signIn", title: "Sign in" },
        },
      ];
    }
    try {
      if (!node) return await this.projects();
      if (node.kind === "project") return await this.jobs(node.project);
      return [];
    } catch (err) {
      return [{ kind: "message", text: String((err as Error).message ?? err) }];
    }
  }

  private async projects(): Promise<Node[]> {
    const projects = await this.api.projects();
    if (projects.length === 0) {
      return [{ kind: "message", text: "No projects yet." }];
    }
    let waiting = 0;
    const nodes: Node[] = [];
    for (const project of projects) {
      let pending = 0;
      try {
        pending = (await this.api.progress(project.id)).pending_approvals;
      } catch {
        /* a project whose progress cannot be read still belongs in the tree */
      }
      waiting += pending;
      nodes.push({ kind: "project", project, waiting: pending });
    }
    this.waiting = waiting;
    return nodes;
  }

  private async jobs(project: Project): Promise<Node[]> {
    const jobs = await this.api.jobs(project.id);
    if (jobs.length === 0) {
      return [
        {
          kind: "message",
          text: "No developments yet — start one…",
          command: {
            command: "slipwright.newDevelopment",
            title: "New development",
            arguments: [{ kind: "project", project, waiting: 0 }],
          },
        },
      ];
    }
    return jobs.map((job) => ({ kind: "job", job, project }));
  }
}

/** The first line of a request, short enough to read in a tree row. */
export function headline(request: string, limit = 72): string {
  const first = request.trim().split("\n")[0]!.trim();
  return first.length > limit ? `${first.slice(0, limit - 1)}…` : first;
}

export function icon(state: string): string {
  if (state === "done") return "pass-filled";
  if (state === "failed") return "error";
  if (isWaiting(state)) return "bell-dot";
  return "sync";
}
