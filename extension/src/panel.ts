// A development, in a tab: what the agents will do, grouped by agent, and the two buttons
// that matter — start it, or have it written again. The webview holds no token and makes no
// request; it asks the extension host and the host answers.
import * as vscode from "vscode";
import type { SlipwrightApi } from "./api";

type Incoming =
  | { kind: "ready" }
  | { kind: "approve" }
  | { kind: "reject"; feedback: string }
  | { kind: "open" };

export class DevelopmentPanel {
  private static open = new Map<string, DevelopmentPanel>();

  static show(
    context: vscode.ExtensionContext,
    api: SlipwrightApi,
    jobId: string,
    projectId: string,
    title: string,
  ): DevelopmentPanel {
    const existing = DevelopmentPanel.open.get(jobId);
    if (existing) {
      existing.panel.reveal();
      void existing.refresh();
      return existing;
    }
    const panel = vscode.window.createWebviewPanel(
      "slipwright.development",
      title,
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    const made = new DevelopmentPanel(panel, api, jobId, projectId);
    DevelopmentPanel.open.set(jobId, made);
    context.subscriptions.push(panel);
    return made;
  }

  /** The panel showing this job, if one is open — used when an event says it moved. */
  static forJob(jobId: string): DevelopmentPanel | undefined {
    return DevelopmentPanel.open.get(jobId);
  }

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private api: SlipwrightApi,
    private readonly jobId: string,
    private readonly projectId: string,
  ) {
    panel.webview.html = html(panel.webview.cspSource);
    panel.onDidDispose(() => DevelopmentPanel.open.delete(jobId));
    panel.webview.onDidReceiveMessage((message: Incoming) => void this.handle(message));
  }

  setApi(api: SlipwrightApi): void {
    this.api = api;
  }

  async refresh(): Promise<void> {
    try {
      const [job, list] = await Promise.all([
        this.api.job(this.jobId),
        this.api.workList(this.jobId),
      ]);
      await this.panel.webview.postMessage({ kind: "list", job, list });
    } catch (err) {
      await this.panel.webview.postMessage({
        kind: "error",
        message: (err as Error).message ?? String(err),
      });
    }
  }

  private async handle(message: Incoming): Promise<void> {
    if (message.kind === "ready") return void this.refresh();
    if (message.kind === "open") {
      await vscode.env.openExternal(
        vscode.Uri.parse(this.api.urlFor("job", this.jobId, this.projectId)),
      );
      return;
    }
    try {
      if (message.kind === "approve") await this.api.approve(this.jobId);
      else await this.api.reject(this.jobId, message.feedback);
      await this.refresh();
      await vscode.commands.executeCommand("slipwright.refresh");
    } catch (err) {
      await this.panel.webview.postMessage({
        kind: "error",
        message: (err as Error).message ?? String(err),
      });
    }
  }
}

/** The view: VS Code's own colours, no framework, no network. */
function html(csp: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${csp} 'unsafe-inline'; script-src ${csp} 'unsafe-inline';" />
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground);
         padding: 14px 18px; font-size: 13px; }
  h2 { font-size: 15px; margin: 0 0 2px; }
  .muted { color: var(--vscode-descriptionForeground); }
  .group { border: 1px solid var(--vscode-panel-border); border-radius: 6px;
           padding: 10px 12px; margin: 12px 0; }
  .group h3 { margin: 0; font-size: 13px; display: flex; gap: 8px; align-items: baseline; }
  .n { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%;
       background: var(--vscode-badge-background); color: var(--vscode-badge-foreground);
       font-size: 11px; }
  ul { list-style: none; margin: 8px 0 0; padding: 0; }
  li { padding: 3px 0; border-bottom: 1px solid var(--vscode-panel-border); }
  li:last-child { border-bottom: 0; }
  .detail { display: block; color: var(--vscode-descriptionForeground); font-size: 12px; }
  .chip { font-size: 11px; color: var(--vscode-descriptionForeground);
          border: 1px solid var(--vscode-panel-border); border-radius: 4px; padding: 0 5px; }
  .row { display: flex; gap: 8px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
  button { font-family: inherit; font-size: 12px; padding: 5px 12px; border: 0; border-radius: 3px;
           background: var(--vscode-button-background); color: var(--vscode-button-foreground);
           cursor: pointer; }
  button.secondary { background: var(--vscode-button-secondaryBackground);
                     color: var(--vscode-button-secondaryForeground); }
  button:disabled { opacity: .5; cursor: default; }
  textarea { width: 100%; min-height: 60px; margin-top: 8px; font-family: inherit;
             background: var(--vscode-input-background); color: var(--vscode-input-foreground);
             border: 1px solid var(--vscode-input-border, var(--vscode-panel-border)); }
  .error { color: var(--vscode-errorForeground); margin-top: 10px; }
</style>
</head>
<body>
<div id="app" class="muted">Loading…</div>
<script>
  const vscode = acquireVsCodeApi();
  const app = document.getElementById("app");
  let rejecting = false;

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.kind === "error") { app.innerHTML = '<div class="error"></div>';
      app.firstChild.textContent = message.message; return; }
    if (message.kind !== "list") return;
    render(message.job, message.list);
  });

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function render(job, list) {
    app.textContent = "";
    app.className = "";
    const head = el("div");
    head.appendChild(el("h2", null, job.request.split("\\n")[0]));
    head.appendChild(el("div", "muted", list.editable
      ? list.tasks + " task(s) in " + list.phases + " phase(s) — nothing is built yet"
      : "state: " + job.state));
    app.appendChild(head);
    if (list.plan_summary) app.appendChild(el("p", "muted", list.plan_summary));

    list.groups.forEach((group, i) => {
      const box = el("div", "group");
      const title = el("h3");
      title.appendChild(el("span", "n", String(i + 1)));
      title.appendChild(el("span", null, group.label));
      title.appendChild(el("span", "muted", group.summary));
      box.appendChild(title);
      const ul = el("ul");
      group.items.forEach((item) => {
        const li = el("li");
        const line = el("div");
        if (item.phase && item.kind === "phase") line.appendChild(el("span", "chip", "phase " + item.phase));
        line.appendChild(el("span", null, " " + item.title));
        if (item.domain) line.appendChild(el("span", "chip", " " + item.domain));
        li.appendChild(line);
        if (item.detail) li.appendChild(el("span", "detail", item.detail));
        ul.appendChild(li);
      });
      box.appendChild(ul);
      app.appendChild(box);
    });

    const row = el("div", "row");
    if (list.editable) {
      const start = el("button", null, "Everything is fine — start");
      start.onclick = () => { start.disabled = true; vscode.postMessage({ kind: "approve" }); };
      row.appendChild(start);
      const again = el("button", "secondary", "Have it written again…");
      again.onclick = () => { rejecting = !rejecting; render(job, list); };
      row.appendChild(again);
    }
    const open = el("button", "secondary", "Open in browser");
    open.onclick = () => vscode.postMessage({ kind: "open" });
    row.appendChild(open);
    app.appendChild(row);

    if (rejecting) {
      const box = el("textarea");
      box.placeholder = "What should change?";
      app.appendChild(box);
      const send = el("button", null, "Send");
      send.onclick = () => {
        if (!box.value.trim()) return;
        send.disabled = true;
        vscode.postMessage({ kind: "reject", feedback: box.value.trim() });
        rejecting = false;
      };
      app.appendChild(send);
    }
  }

  vscode.postMessage({ kind: "ready" });
</script>
</body>
</html>`;
}
