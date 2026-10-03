// The loop: ask for work, do it, say what happened -- for builds and for calls alike.
//
// It calls out and nothing calls in, so it works behind any router. A network that goes
// away is waited out, never given up on; a 401 is the one thing that ends a pairing.
// Every call that is taken from the server is answered, failed or dropped on a 409 --
// never left hanging, because the server waits on it before it falls back to its own
// model (60 s of silence, docs/machines-protocol.md §1).

import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import type { AgentId, HistoryEntry, LogLine, ModelChoice, TaskView } from "@shared/types";
import { runBuild } from "./build";
import { agentFor } from "./capabilities";
import { Unpaired, WorkerClient, type Build, type Call, type Task } from "./client";
import { callAnthropic, callOpenAI } from "./models/api";
import { callClaude } from "./models/claude";
import { callCodex } from "./models/codex";
import { Cancelled, ModelFailure, type ModelAnswer, type ModelCall } from "./models/types";
import { checkout } from "./source";
import { takeIssue } from "./jira";
import { TransportError } from "./transport";

export const PROGRESS_S = 15;
export const HEARTBEAT_S = 20;
const LOG_LINES = 200;

export interface WorkerHost {
  client(): WorkerClient | null;
  name(): string;
  capabilities(): string[];
  /** Why not to ask for work now: paused, on battery, unpaired. Null to go ahead. */
  holding(): string | null;
  maxConcurrent(): number;
  workDir(): string;
  model(agent: AgentId): ModelChoice | null;
  secret(name: "anthropic" | "openai" | "github" | "bitbucket" | "jira"): string | null;
  bitbucketUser(): string | null;
  jira(): { site: string; email: string; account: string | null };
  rememberJiraAccount(account: string): void;
  toolchainEnv(): Record<string, string>;
  recordHistory(entry: HistoryEntry): void;
  connected(ok: boolean, error?: string): void;
  unpaired(why: string): void;
  done(entry: HistoryEntry): void;
}

interface Running {
  view: TaskView;
  abort: AbortController;
}

/** "yazıyor · 3 dk": what the server's page shows beside the phase while this works. */
export function progressText(startedAt: number, now = Date.now(), stage = "yazıyor"): string {
  const minutes = Math.floor((now - startedAt) / 60_000);
  return minutes < 1 ? `${stage} · <1 dk` : `${stage} · ${minutes} dk`;
}

export class Worker extends EventEmitter {
  private running = new Map<string, Running>();
  private stopped = true;
  private wake: (() => void) | null = null;
  private loop: Promise<void> | null = null;
  private handling = new Set<Promise<void>>();

  constructor(private readonly host: WorkerHost) {
    super();
  }

  tasks(): TaskView[] {
    return [...this.running.values()].map((r) => r.view);
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.loop = this.forever();
  }

  /** Ends the loop and drops every task in hand: a call is then the server's again after
   *  its 60 s, a build is retried elsewhere. */
  async stop(): Promise<void> {
    this.stopped = true;
    this.kick();
    for (const r of this.running.values()) r.abort.abort();
    await this.loop;
    // what was in hand has said so to the server before the process goes
    await Promise.allSettled([...this.handling]);
  }

  /** Something changed (a setting, a task finished): look again now, not after a sleep. */
  kick(): void {
    this.wake?.();
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(done, ms);
      function done() {
        clearTimeout(timer);
        resolve();
      }
      this.wake = done;
    });
  }

  private async forever(): Promise<void> {
    let pause = 1000;
    while (!this.stopped) {
      const client = this.host.client();
      const capabilities = this.host.capabilities();
      if (!client || this.host.holding() || !capabilities.length || this.running.size >= this.host.maxConcurrent()) {
        await this.sleep(client ? 3000 : 5000);
        continue;
      }
      try {
        const task = await client.poll(capabilities, this.host.name());
        this.host.connected(true);
        pause = 1000;
        if (task) {
          const handled = this.handle(client, task).catch(() => undefined);
          this.handling.add(handled);
          void handled.finally(() => this.handling.delete(handled));
        }
      } catch (error) {
        if (error instanceof Unpaired) {
          this.host.unpaired(error.message);
          continue;
        }
        this.host.connected(false, (error as Error).message);
        await this.sleep(pause);
        pause = Math.min(pause * 2, 60_000);
      }
    }
  }

  private async handle(client: WorkerClient, task: Task): Promise<void> {
    const agent: AgentId = task.kind === "build" ? "mobile" : agentFor(task.domain);
    const view: TaskView = {
      id: task.id,
      kind: task.kind,
      agent,
      project: task.kind === "write" ? (task.project ?? "") : "",
      goal: task.kind === "write" ? (task.goal ?? "") : `${task.platform} build`,
      phase: task.kind === "write" ? (task.phase ?? null) : null,
      phases: task.kind === "write" ? (task.phases ?? null) : null,
      jiraKey: task.kind === "write" ? (task.jira_key ?? null) : null,
      platform: task.kind === "build" ? task.platform : null,
      model: "",
      startedAt: Date.now(),
      timeoutS: task.timeout_s ?? 1800,
      status: task.kind === "write" ? "starting" : "building",
      log: [],
    };
    const running: Running = { view, abort: new AbortController() };
    this.running.set(task.id, running);
    this.changed();
    const beat = setInterval(() => client.heartbeat().catch(() => undefined), HEARTBEAT_S * 1000);
    let entry: HistoryEntry;
    try {
      entry = task.kind === "build" ? await this.build(client, task, running) : await this.write(client, task, running);
    } catch (error) {
      if (error instanceof Unpaired) this.host.unpaired(error.message);
      entry = this.entry(view, "failed", (error as Error).message);
    } finally {
      clearInterval(beat);
      this.running.delete(task.id);
    }
    this.host.recordHistory(entry);
    this.host.done(entry);
    this.changed();
    this.kick();
  }

  private log(running: Running, text: string, tone?: LogLine["tone"]): void {
    const line: LogLine = { at: new Date().toISOString(), text, tone };
    running.view.log = [...running.view.log, line].slice(-LOG_LINES);
    this.changed();
  }

  private changed(): void {
    this.emit("change");
  }

  private entry(view: TaskView, outcome: HistoryEntry["outcome"], detail: string | null): HistoryEntry {
    return {
      id: view.id,
      kind: view.kind,
      agent: view.agent,
      project: view.project,
      goal: view.goal,
      phase: view.phase,
      phases: view.phases,
      jiraKey: view.jiraKey,
      seconds: Math.round((Date.now() - view.startedAt) / 1000),
      outcome,
      detail,
      at: new Date().toISOString(),
    };
  }

  // -- a build -----------------------------------------------------------------------

  private async build(client: WorkerClient, task: Build, running: Running): Promise<HistoryEntry> {
    this.log(running, `snapshot ${task.id.slice(0, 8)}`, "dim");
    const snapshot = await client.snapshot(task.id);
    const workDir = join(this.host.workDir(), "builds");
    mkdirSync(workDir, { recursive: true });
    const result = await runBuild(task, snapshot, {
      workDir,
      toolchainEnv: this.host.toolchainEnv(),
      signal: running.abort.signal,
      log: (text, tone) => this.log(running, text, tone),
    });
    if (running.abort.signal.aborted) return this.entry(running.view, "taken-back", "stopped");
    const status = await client.result(task.id, result);
    if (status === 409) return this.entry(running.view, "taken-back", "409");
    return this.entry(running.view, result.exit_code === 0 ? "built" : "build-failed", `exit ${result.exit_code}`);
  }

  // -- a call ------------------------------------------------------------------------

  private async write(client: WorkerClient, task: Call, running: Running): Promise<HistoryEntry> {
    const { view, abort } = running;
    const choice = this.host.model(view.agent);
    view.model = choice ? `${choice.provider}${choice.model ? ` · ${choice.model}` : ""}` : "";
    const say = (text: string, tone?: LogLine["tone"]) => this.log(running, text, tone);
    say(`${task.project ?? ""} · faz ${task.phase ?? "?"}/${task.phases ?? "?"} · ${task.goal ?? ""}`, "dim");

    let stage = "hazırlanıyor";
    // the server takes a call back after 60 s of silence; every 15 s keeps two spare
    const tell = async () => {
      try {
        const status = await client.progress(task.id, progressText(view.startedAt, Date.now(), stage));
        if (status === 409) {
          say("the server took this call back; dropping it", "bad");
          abort.abort();
        }
      } catch (error) {
        if (error instanceof Unpaired) abort.abort();
        // a missed progress is not fatal: the next one may get through
      }
    };
    void tell();
    const ticker = setInterval(() => void tell(), PROGRESS_S * 1000);

    const jira = this.host.jira();
    const jiraToken = this.host.secret("jira");
    if (task.jira_key && jira.site && jira.email && jiraToken) {
      void takeIssue({ site: jira.site, email: jira.email, token: jiraToken }, task.jira_key, jira.account, (t) => say(t, "dim"))
        .then((account) => account && account !== jira.account && this.host.rememberJiraAccount(account))
        .catch(() => undefined);
    }

    const root = join(this.host.workDir(), "calls");
    mkdirSync(root, { recursive: true });
    const scratch = mkdtempSync(join(root, "call-"));
    try {
      let checkoutDir: string | null = null;
      const github = this.host.secret("github");
      const bitbucket = this.host.secret("bitbucket");
      if (task.repo && (github || bitbucket)) {
        stage = "kodu çekiyor";
        view.status = "checkout";
        try {
          const into = join(scratch, "repo");
          await checkout(
            task.repo,
            { github, bitbucket, bitbucketUser: this.host.bitbucketUser() },
            join(this.host.workDir(), "repos"),
            into,
            abort.signal,
            (t) => say(t, "dim"),
          );
          checkoutDir = into;
          say(`checked out ${task.repo.commit.slice(0, 7)}`, "ok");
        } catch (error) {
          if (abort.signal.aborted) throw new Cancelled("taken back");
          say(`no checkout (${(error as Error).message}); answering from the prompt`, "bad");
        }
      }
      stage = "yazıyor";
      view.status = "writing";
      this.changed();
      if (!choice) throw new ModelFailure("no model is chosen for this agent on this machine", "error");
      const call: ModelCall = {
        system: task.system,
        prompt: task.prompt,
        images: task.images ?? [],
        thinkingDepth: task.thinking_depth ?? null,
        model: choice.model,
        checkout: checkoutDir,
        scratch,
        timeoutMs: (task.timeout_s ?? 1800) * 1000,
        signal: abort.signal,
        log: (t) => say(t),
      };
      const answer = await this.ask(choice, call);
      clearInterval(ticker);
      if (abort.signal.aborted) throw new Cancelled("taken back");
      const seconds = (Date.now() - view.startedAt) / 1000;
      const status = await client.answer(task.id, {
        text: answer.text,
        ...(answer.model ? { model: answer.model } : {}),
        ...(answer.inputTokens != null ? { input_tokens: answer.inputTokens } : {}),
        ...(answer.outputTokens != null ? { output_tokens: answer.outputTokens } : {}),
        seconds,
      });
      if (status === 409) {
        say("answered too late: the call was already taken back", "bad");
        return this.entry(view, "taken-back", "409");
      }
      say(`answer sent · ${answer.outputTokens ?? "?"} tokens`, "ok");
      return this.entry(view, "answered", answer.model);
    } catch (error) {
      clearInterval(ticker);
      if (error instanceof Cancelled || abort.signal.aborted) {
        // stopped by its owner, not taken back by the server: say so, so the server writes
        // the phase now rather than after a minute of waiting on a machine that is gone
        if (this.stopped) {
          await client.fail(task.id, { message: "the machine was stopped", kind: "error" }).catch(() => undefined);
        }
        return this.entry(view, "taken-back", this.stopped ? "stopped" : null);
      }
      if (error instanceof Unpaired) throw error;
      const failure = error instanceof ModelFailure ? error : new ModelFailure((error as Error).message, "error");
      say(failure.message, "bad");
      try {
        await client.fail(task.id, { message: failure.message.slice(0, 2000), kind: failure.kind });
      } catch (sent) {
        if (sent instanceof Unpaired) throw sent;
        if (!(sent instanceof TransportError)) throw sent;
        // unreachable now: the server falls back by itself after 60 s of silence
      }
      return this.entry(view, failure.kind === "timeout" ? "timeout" : failure.kind === "rejected" ? "rejected" : "failed", failure.message);
    } finally {
      clearInterval(ticker);
      rmSync(scratch, { recursive: true, force: true, maxRetries: 3 });
    }
  }

  private ask(choice: ModelChoice, call: ModelCall): Promise<ModelAnswer> {
    switch (choice.provider) {
      case "claude-code":
        return callClaude(call);
      case "codex":
        return callCodex(call);
      case "anthropic": {
        const key = this.host.secret("anthropic");
        if (!key) throw new ModelFailure("no Anthropic API key on this machine", "rejected");
        return callAnthropic(call, key);
      }
      case "openai": {
        const key = this.host.secret("openai");
        if (!key) throw new ModelFailure("no OpenAI API key on this machine", "rejected");
        return callOpenAI(call, key);
      }
    }
  }
}
