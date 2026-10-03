// slipwright-agent: the desktop app without its window, for a server somebody reaches over
// SSH. It does exactly what the app does -- the same worker, the same models, the same
// protocol -- and takes everything the app keeps behind a window and the system keyring
// from settings.json in the folder it is run from (settings.ts).
//
//   slipwright-agent init     write a settings.json to fill in
//   slipwright-agent check    say what it would do: models found, agents, tokens, pairing
//   slipwright-agent          pair if it has to, then work until stopped
//
// settings.json is read again when it changes, so a file uploaded over SFTP takes effect
// within seconds; the pairing lives beside it in slipwright-agent.state.json (state.ts).

import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { hostname } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import type { Detected, HistoryEntry } from "@shared/types";
import { capabilities as deriveCapabilities } from "../main/capabilities";
import { pair, Unpaired, WorkerClient } from "../main/client";
import { CodeError } from "../main/code";
import { publicFromSecret } from "../main/crypto";
import { detect, toolchains } from "../main/detect";
import { History } from "../main/history";
import { myself } from "../main/jira";
import { adoptShellPath } from "../main/proc";
import { DirectTransport, RelayTransport, type Transport } from "../main/transport";
import { Worker } from "../main/worker";
import { type AgentSettingsFile, readSettings, SettingsError, template } from "./settings";
import { forgetState, type PairingState, readState, writeState } from "./state";

declare const __VERSION__: string;
const VERSION = typeof __VERSION__ === "string" ? __VERSION__ : "dev";
const STATE_FILE = "slipwright-agent.state.json";
const HISTORY_FILE = "slipwright-agent.history.json";
const RELOAD_MS = 5_000;

// -- saying things ------------------------------------------------------------------------

function say(text: string): void {
  process.stdout.write(`${new Date().toISOString().slice(0, 19).replace("T", " ")}  ${text}\n`);
}

function fail(text: string): never {
  process.stderr.write(`slipwright-agent: ${text}\n`);
  process.exit(1);
}

const HELP = `slipwright-agent ${VERSION} -- lends this machine to a Slipwright account

  slipwright-agent init     write settings.json here, to fill in
  slipwright-agent check    what it would do: models, agents, tokens, pairing
  slipwright-agent          pair (first time) and take work until stopped

  --settings <file>         another settings.json than ./settings.json
  --version                 the version

The pairing is kept in ${STATE_FILE} beside settings.json. Delete it to pair again.`;

// -- settings.json ------------------------------------------------------------------------

interface Paths {
  settings: string;
  state: string;
  history: string;
  folder: string;
}

function paths(argv: string[]): Paths {
  const at = argv.indexOf("--settings");
  const given = at >= 0 ? argv[at + 1] : process.env.SLIPWRIGHT_AGENT_SETTINGS;
  const settings = resolve(given || "settings.json");
  const folder = dirname(settings);
  return { settings, state: join(folder, STATE_FILE), history: join(folder, HISTORY_FILE), folder };
}

function load(p: Paths): { settings: AgentSettingsFile; warnings: string[] } {
  if (!existsSync(p.settings)) fail(`no ${p.settings}; run "slipwright-agent init" here first`);
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(p.settings, "utf8"));
  } catch (error) {
    fail(`${p.settings} is not valid JSON: ${(error as Error).message}`);
  }
  try {
    const read = readSettings(raw, { defaultWorkDir: "./work" });
    // a relative work_dir is the settings file's, not wherever the program was started
    if (!isAbsolute(read.settings.workDir)) read.settings.workDir = resolve(p.folder, read.settings.workDir);
    return { settings: read.settings, warnings: [...read.warnings, ...exposure(p.settings)] };
  } catch (error) {
    if (error instanceof SettingsError) fail(`${p.settings}: ${error.message}`);
    throw error;
  }
}

/** A key in a file anybody on the server can read is a key anybody can spend. */
function exposure(file: string): string[] {
  if (process.platform === "win32") return [];
  const mode = statSync(file).mode & 0o077;
  return mode ? [`${file} can be read by other users of this server; chmod 600 it`] : [];
}

// -- the commands -------------------------------------------------------------------------

function init(p: Paths): void {
  if (existsSync(p.settings)) fail(`${p.settings} is already there; edit it instead`);
  mkdirSync(p.folder, { recursive: true });
  writeFileSync(p.settings, `${JSON.stringify(template(hostname()), null, 2)}\n`, { mode: 0o600 });
  say(`wrote ${p.settings}`);
  say("next: put the connection code in \"code\", choose each agent's model, then: slipwright-agent check");
}

async function check(p: Paths): Promise<void> {
  const { settings, warnings } = load(p);
  for (const w of warnings) say(`warning: ${w}`);
  await adoptShellPath();
  const found = await detect();
  say(`claude: ${found.claude.installed ? `${found.claude.version}${found.claude.signedIn === false ? " (not signed in)" : ""}` : "not installed"}`);
  say(`codex: ${found.codex.installed ? `${found.codex.version}${found.codex.signedIn === false ? " (not signed in)" : ""}` : "not installed"}`);
  say(`ios: ${found.ios.ok ? (found.ios.detail ?? "yes") : "no"} · android: ${found.android.ok ? (found.android.detail ?? "yes") : "no"}`);
  for (const [agent, own] of Object.entries(settings.agents)) {
    const model = own.model ? `${own.model.provider}${own.model.model ? `:${own.model.model}` : ""}` : "no model";
    say(`agent ${agent}: ${own.enabled ? model : "off"}`);
  }
  const caps = capabilitiesOf(settings, found);
  say(`it would ask for: ${caps.length ? caps.join(", ") : "nothing -- no agent has a model this machine can run"}`);
  if (settings.secrets.github) {
    try {
      const r = await fetch("https://api.github.com/user", {
        headers: { authorization: `Bearer ${settings.secrets.github}`, accept: "application/vnd.github+json", "user-agent": "slipwright-agent" },
        signal: AbortSignal.timeout(15_000),
      });
      say(r.ok ? `github: ${((await r.json()) as { login?: string }).login}` : `github: the token was refused (${r.status})`);
    } catch (error) {
      say(`github: ${(error as Error).message}`);
    }
  }
  if (settings.jira.site && settings.secrets.jira) {
    try {
      const me = await myself({ site: settings.jira.site, email: settings.jira.email, token: settings.secrets.jira });
      say(`jira: ${me.displayName}`);
    } catch (error) {
      say(`jira: ${(error as Error).message}`);
    }
  }
  const state = readState(p.state);
  if (state) say(`paired as "${state.pairing.name}" with ${state.pairing.relay ? `the relay (${state.pairing.relay.host})` : state.pairing.address}`);
  else say(settings.code ? "not paired yet; the code will be used on start" : 'not paired, and "code" is empty');
}

function capabilitiesOf(settings: AgentSettingsFile, found: Detected): string[] {
  return deriveCapabilities(
    {
      paused: settings.paused,
      startAtLogin: false,
      notOnBattery: false,
      runBuilds: settings.runBuilds,
      notifyDone: false,
      maxConcurrent: settings.maxConcurrent,
      workDir: settings.workDir,
      theme: "system",
      agents: settings.agents,
      github: { user: null },
      bitbucket: { user: settings.bitbucketUser },
      jira: { ...settings.jira, account: null },
    },
    found,
    { anthropic: !!settings.secrets.anthropic, openai: !!settings.secrets.openai },
  );
}

function transportFor(state: PairingState): Transport {
  const p = state.pairing;
  if (p.relay) {
    if (!state.relayClientSk || !state.serverPk) fail(`${STATE_FILE} is missing its relay keys; delete it and pair again`);
    const secret = Buffer.from(state.relayClientSk, "base64");
    return new RelayTransport(p.relay.host, p.relay.room, {
      client: { secret, public: publicFromSecret(secret) },
      server: Buffer.from(state.serverPk, "base64"),
    });
  }
  if (!p.address) fail(`${STATE_FILE} has neither an address nor a relay; delete it and pair again`);
  return new DirectTransport(p.address);
}

async function pairWith(code: string, name: string, caps: string[], p: Paths): Promise<PairingState> {
  say(`pairing as "${name}"…`);
  try {
    const paired = await pair(code, { name, capabilities: caps });
    const state: PairingState = {
      pairing: { workerId: paired.workerId, name, address: paired.address, relay: paired.relay, pairedAt: new Date().toISOString() },
      token: paired.token,
      relayClientSk: paired.clientSk ? paired.clientSk.toString("base64") : null,
      serverPk: paired.serverPk ? paired.serverPk.toString("base64") : null,
    };
    writeState(p.state, state);
    say(`paired with ${paired.relay ? `the relay (${paired.relay.host})` : paired.address}; kept in ${p.state}`);
    return state;
  } catch (error) {
    if (error instanceof CodeError || error instanceof Unpaired) fail(`pairing failed: ${error.message}`);
    throw error;
  }
}

async function run(p: Paths): Promise<void> {
  const loaded = load(p);
  let settings = loaded.settings;
  for (const w of loaded.warnings) say(`warning: ${w}`);
  await adoptShellPath();
  let found: Detected = await detect();
  const name = () => settings.name ?? hostname();
  let state = readState(p.state);
  if (!state) {
    if (!settings.code) fail(`not paired, and "code" in ${p.settings} is empty: make a code under Settings -> Machines`);
    state = await pairWith(settings.code, name(), capabilitiesOf(settings, found), p);
  }
  let client: WorkerClient | null = new WorkerClient(transportFor(state), state.token);
  mkdirSync(settings.workDir, { recursive: true });
  const history = new History(p.history);
  let online: boolean | null = null;
  let jiraAccount: string | null = null;

  const worker = new Worker({
    client: () => client,
    name,
    capabilities: () => capabilitiesOf(settings, found),
    holding: () => (settings.paused ? "paused" : null),
    maxConcurrent: () => settings.maxConcurrent,
    workDir: () => settings.workDir,
    model: (agent) => settings.agents[agent].model,
    secret: (which) => settings.secrets[which],
    bitbucketUser: () => settings.bitbucketUser,
    jira: () => ({ ...settings.jira, account: jiraAccount }),
    rememberJiraAccount: (account) => {
      jiraAccount = account;
    },
    toolchainEnv: () => toolchains.env,
    recordHistory: (entry) => history.add(entry),
    connected: (ok, error) => {
      if (ok !== online) say(ok ? "connected" : `cannot reach the server (${error ?? "?"}); waiting`);
      online = ok;
    },
    unpaired: (why) => {
      say(`the server no longer knows this machine: ${why}`);
      forgetState(p.state);
      client = null;
      say(`removed ${STATE_FILE}; put a new code in settings.json and start again`);
      void worker.stop().then(() => process.exit(2));
    },
    done: (entry: HistoryEntry) => {
      const what = entry.phase ? `phase ${entry.phase}${entry.phases ? `/${entry.phases}` : ""}` : entry.kind;
      say(`${entry.agent} ${what}: ${entry.outcome}${entry.detail ? ` -- ${entry.detail}` : ""}`);
    },
  });

  // each task's own log, as it grows, with which task it is
  const printed = new Map<string, number>();
  worker.on("change", () => {
    for (const task of worker.tasks()) {
      const from = printed.get(task.id) ?? 0;
      const tag = task.kind === "write" ? `${task.agent} phase ${task.phase ?? "?"}` : `${task.platform ?? "build"}`;
      for (const line of task.log.slice(from)) say(`[${tag}] ${line.text}`);
      printed.set(task.id, task.log.length);
    }
  });

  // settings.json uploaded again: read it, keep the old one if the new one is wrong
  let seen = statSync(p.settings).mtimeMs;
  setInterval(() => {
    try {
      const now = statSync(p.settings).mtimeMs;
      if (now === seen) return;
      seen = now;
      const next = readSettings(JSON.parse(readFileSync(p.settings, "utf8")), { defaultWorkDir: "./work" });
      if (!isAbsolute(next.settings.workDir)) next.settings.workDir = resolve(p.folder, next.settings.workDir);
      settings = next.settings;
      for (const w of next.warnings) say(`warning: ${w}`);
      say(`read ${p.settings} again; asking for: ${capabilitiesOf(settings, found).join(", ") || "nothing"}`);
      worker.kick();
    } catch (error) {
      say(`${p.settings} changed but cannot be read (${(error as Error).message}); keeping the last good one`);
    }
  }, RELOAD_MS).unref();
  setInterval(() => void detect().then((d) => (found = d)), 10 * 60_000).unref();

  // stopping hands back what is in hand: the server takes it back and writes it itself
  let stopping = false;
  const stop = (signal: string) => {
    if (stopping) process.exit(130);
    stopping = true;
    say(`${signal}: stopping; anything in hand goes back to the server`);
    void worker.stop().then(() => process.exit(0));
  };
  process.on("SIGINT", () => stop("SIGINT"));
  process.on("SIGTERM", () => stop("SIGTERM"));

  const caps = capabilitiesOf(settings, found);
  say(`slipwright-agent ${VERSION} as "${name()}"; asking for: ${caps.length ? caps.join(", ") : "nothing yet"}`);
  if (!caps.length) say("warning: no agent has a model this machine can run -- run: slipwright-agent check");
  worker.start();
}

// -- the door ---------------------------------------------------------------------------

async function main(argv: string[]): Promise<void> {
  if (argv.includes("--version")) {
    process.stdout.write(`${VERSION}\n`);
    return;
  }
  if (argv.includes("--help") || argv.includes("-h") || argv[0] === "help") {
    process.stdout.write(`${HELP}\n`);
    return;
  }
  const p = paths(argv);
  const command = argv.find((a, i) => !a.startsWith("-") && argv[i - 1] !== "--settings") ?? "run";
  if (command === "init") return init(p);
  if (command === "check") return check(p);
  if (command === "run") return run(p);
  fail(`no command "${command}"\n\n${HELP}`);
}

void main(process.argv.slice(2)).catch((error: unknown) => fail((error as Error).stack ?? String(error)));
