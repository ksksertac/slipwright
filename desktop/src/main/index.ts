// The main process: the one place that holds the pairing, the keys, the network and the
// child processes. The window is only a view of it -- closing the window hides it to the
// tray and the work goes on, because a machine that stops lending itself whenever its
// window is closed would be no use to anybody.

import { execFile } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  nativeTheme,
  Notification,
  powerMonitor,
  safeStorage,
  shell,
  Tray,
} from "electron";
import type { AgentId, AgentSettings, AppState, Connection, Detected, HistoryEntry, Result, Secrets, Settings } from "@shared/types";
import { AGENTS } from "@shared/types";
import { fromApp } from "../cli/settings";
import { capabilities as deriveCapabilities } from "./capabilities";
import { pair, Unpaired, WorkerClient } from "./client";
import { CodeError } from "./code";
import { publicFromSecret } from "./crypto";
import { detect, NOTHING, toolchains } from "./detect";
import { History } from "./history";
import { myself } from "./jira";
import { adoptShellPath } from "./proc";
import { hint, Store, type SecretName } from "./store";
import { DirectTransport, RelayTransport, type Transport } from "./transport";
import { Worker } from "./worker";

const argv = process.argv.slice(1);
const flag = (name: string): string | null => {
  const at = argv.indexOf(name);
  return at >= 0 ? (argv[at + 1] ?? "") : null;
};
// `--screenshot <png>`: render once, save the window, quit. How the UI is checked
// headlessly (and in CI) without a person clicking through it.
const SCREENSHOT = flag("--screenshot");
const SCREENSHOT_THEME = flag("--theme");
const SCREENSHOT_PAGE = flag("--page");
// `--demo`: a made-up pairing and two running phases, for screenshots of a busy machine.
// It never talks to a server.
const DEMO = argv.includes("--demo");
const HIDDEN = argv.includes("--hidden");

if (SCREENSHOT) app.setPath("userData", join(app.getPath("temp"), "slipwright-agent-screenshot"));

let store: Store;
let history: History;
let detected: Detected = NOTHING;
let connection: Connection = "unpaired";
let connectionError: string | null = null;
let transport: Transport | null = null;
let client: WorkerClient | null = null;
let worker: Worker;
let window: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;
let machineName = hostname();
let detecting: Promise<unknown> = Promise.resolve();

if (!SCREENSHOT && !app.requestSingleInstanceLock()) app.quit();

// -- state ----------------------------------------------------------------------------

function keys() {
  return { anthropic: !!store.secret("anthropic"), openai: !!store.secret("openai") };
}

function capabilities(): string[] {
  return deriveCapabilities(store.settings, detected, keys());
}

function holding(): "battery" | null {
  return store.settings.notOnBattery && powerMonitor.isOnBatteryPower() ? "battery" : null;
}

function secretsView(): Secrets {
  const names: (keyof Secrets)[] = ["anthropic", "openai", "github", "bitbucket", "jira"];
  return Object.fromEntries(names.map((n) => [n, hint(store.secret(n))])) as unknown as Secrets;
}

function state(): AppState {
  const base: AppState = {
    version: app.getVersion(),
    machineName,
    pairing: store.pairing,
    connection: store.pairing ? connection : "unpaired",
    connectionError,
    holding: holding(),
    settings: store.settings,
    secrets: secretsView(),
    detected,
    capabilities: capabilities(),
    tasks: worker?.tasks() ?? [],
  };
  return DEMO ? demoState(base) : base;
}

let pushTimer: NodeJS.Timeout | null = null;
function push(): void {
  // a live log can change many times a second; the page needs it a few times a second
  if (pushTimer) return;
  pushTimer = setTimeout(() => {
    pushTimer = null;
    const now = state();
    window?.webContents.send("state", now);
    updateTray(now);
  }, 150);
}

// -- the connection -------------------------------------------------------------------

function connect(): void {
  transport?.close();
  transport = null;
  client = null;
  const p = store.pairing;
  const token = store.secret("token");
  if (!p || !token) {
    connection = "unpaired";
    push();
    return;
  }
  if (p.relay) {
    const sk = store.secret("relayClientSk");
    const pk = store.secret("serverPk");
    if (!sk || !pk) {
      connection = "unpaired";
      push();
      return;
    }
    const secret = Buffer.from(sk, "base64");
    transport = new RelayTransport(p.relay.host, p.relay.room, {
      client: { secret, public: publicFromSecret(secret) },
      server: Buffer.from(pk, "base64"),
    });
  } else if (p.address) {
    transport = new DirectTransport(p.address);
  }
  client = transport ? new WorkerClient(transport, token) : null;
  connection = "connecting";
  connectionError = null;
  push();
  worker.kick();
}

function forgetPairing(why: string | null): void {
  for (const name of ["token", "relayClientSk", "serverPk"] as SecretName[]) store.setSecret(name, null);
  store.pairing = null;
  store.save();
  connectionError = why;
  connect();
}

async function doPair(code: string): Promise<Result> {
  try {
    const paired = await pair(code, { name: machineName, capabilities: capabilities() });
    store.setSecret("token", paired.token);
    store.setSecret("relayClientSk", paired.clientSk ? paired.clientSk.toString("base64") : null);
    store.setSecret("serverPk", paired.serverPk ? paired.serverPk.toString("base64") : null);
    store.pairing = {
      workerId: paired.workerId,
      name: machineName,
      address: paired.address,
      relay: paired.relay,
      pairedAt: new Date().toISOString(),
    };
    store.save();
    connect();
    return { ok: true, message: paired.relay ? paired.relay.host : (paired.address ?? "") };
  } catch (error) {
    if (error instanceof CodeError || error instanceof Unpaired) return { ok: false, message: error.message };
    return { ok: false, message: (error as Error).message };
  }
}

// -- detection ------------------------------------------------------------------------

async function redetect(): Promise<Detected> {
  detected = await detect();
  // the first time a CLI is found, the agents that have no model yet are given it: a
  // person who already uses Claude Code should not have to choose it four times
  const preferred = detected.claude.installed ? "claude-code" : detected.codex.installed ? "codex" : null;
  let changed = false;
  if (preferred) {
    for (const agent of AGENTS) {
      if (!store.settings.agents[agent].model) {
        store.settings.agents[agent].model = { provider: preferred, model: "" };
        changed = true;
      }
    }
  }
  if (changed) store.save();
  push();
  worker.kick();
  return detected;
}

function computerName(): Promise<string> {
  if (process.platform !== "darwin") return Promise.resolve(hostname());
  // "Ayşe's MacBook Pro", as System Settings shows it: hostname() is often an IP on a Mac
  return new Promise((resolve) =>
    execFile("scutil", ["--get", "ComputerName"], { timeout: 5000 }, (error, out) => resolve(!error && out.trim() ? out.trim() : hostname())),
  );
}

// -- settings -------------------------------------------------------------------------

function applySettings(): void {
  nativeTheme.themeSource = SCREENSHOT_THEME === "dark" || SCREENSHOT_THEME === "light" ? SCREENSHOT_THEME : store.settings.theme;
  if (!SCREENSHOT && app.isPackaged) {
    // only a packaged app registers itself: a dev build would register electron.exe
    app.setLoginItemSettings({ openAtLogin: store.settings.startAtLogin, args: ["--hidden"] });
  }
}

async function verifySource(github: string | null, bitbucketUser: string | null, bitbucket: string | null): Promise<Result> {
  const said: string[] = [];
  let ok = true;
  if (github !== null) store.setSecret("github", github || null);
  if (bitbucket !== null) store.setSecret("bitbucket", bitbucket || null);
  if (bitbucketUser !== null) store.settings.bitbucket.user = bitbucketUser || null;
  const gh = store.secret("github");
  if (gh) {
    try {
      const r = await fetch("https://api.github.com/user", {
        headers: { authorization: `Bearer ${gh}`, accept: "application/vnd.github+json", "user-agent": "slipwright-agent" },
        signal: AbortSignal.timeout(15_000),
      });
      if (!r.ok) throw new Error(`GitHub ${r.status}`);
      const user = (await r.json()) as { login?: string };
      store.settings.github.user = user.login ?? null;
      said.push(`GitHub: ${user.login}`);
    } catch (error) {
      ok = false;
      store.settings.github.user = null;
      said.push((error as Error).message);
    }
  } else store.settings.github.user = null;
  const bb = store.secret("bitbucket");
  if (bb && store.settings.bitbucket.user) {
    try {
      const r = await fetch("https://api.bitbucket.org/2.0/user", {
        headers: { authorization: `Basic ${Buffer.from(`${store.settings.bitbucket.user}:${bb}`).toString("base64")}` },
        signal: AbortSignal.timeout(15_000),
      });
      if (!r.ok) throw new Error(`Bitbucket ${r.status}`);
      said.push(`Bitbucket: ${store.settings.bitbucket.user}`);
    } catch (error) {
      ok = false;
      said.push((error as Error).message);
    }
  }
  store.save();
  push();
  return { ok, message: said.join(" · ") };
}

async function verifyJira(site: string, email: string, token: string | null): Promise<Result> {
  store.settings.jira = { site: site.trim(), email: email.trim(), account: null };
  if (token !== null) store.setSecret("jira", token || null);
  const secret = store.secret("jira");
  store.save();
  push();
  if (!site.trim() || !email.trim() || !secret) return { ok: true, message: "" };
  try {
    const me = await myself({ site, email, token: secret });
    store.settings.jira.account = me.accountId;
    store.save();
    push();
    return { ok: true, message: me.displayName };
  } catch (error) {
    return { ok: false, message: (error as Error).message };
  }
}

// -- window and tray ------------------------------------------------------------------

function icon(size?: number) {
  const image = nativeImage.createFromPath(join(app.getAppPath(), "resources", "logo.png"));
  return size ? image.resize({ width: size, height: size }) : image;
}

function createWindow(): void {
  window = new BrowserWindow({
    width: 1120,
    height: 800,
    minWidth: 900,
    minHeight: 640,
    show: false,
    title: "Slipwright Agent",
    icon: icon(),
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#0b0d11" : "#f4f5f7",
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.setMenuBarVisibility(false);
  // links leave for the browser; the app never navigates anywhere itself
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.on("close", (event) => {
    if (!quitting && !SCREENSHOT) {
      event.preventDefault();
      window?.hide();
    }
  });
  // started at login: to the tray, not in the person's face. Windows and Linux are told
  // so by an argument; macOS ignores arguments for login items and says so itself
  const atLogin = HIDDEN || (process.platform === "darwin" && app.getLoginItemSettings().wasOpenedAtLogin);
  window.once("ready-to-show", () => {
    if (!atLogin && !SCREENSHOT) window?.show();
  });
  const page = SCREENSHOT_PAGE ? `#${SCREENSHOT_PAGE}` : "";
  if (process.env.ELECTRON_RENDERER_URL) void window.loadURL(process.env.ELECTRON_RENDERER_URL + page);
  else void window.loadFile(join(__dirname, "../renderer/index.html"), { hash: SCREENSHOT_PAGE ?? undefined });
  if (SCREENSHOT) {
    window.webContents.once("did-finish-load", async () => {
      await detecting; // what was found on this machine is part of the picture
      // fonts and the state push settle well within this
      setTimeout(async () => {
        const image = await window!.webContents.capturePage();
        const { writeFileSync } = await import("node:fs");
        writeFileSync(SCREENSHOT, image.toPNG());
        quitting = true;
        app.quit();
      }, 1500);
    });
  }
}

function showWindow(): void {
  if (!window) createWindow();
  window?.show();
  window?.focus();
}

function updateTray(now: AppState): void {
  if (!tray) return;
  const running = now.tasks.length;
  const status = !now.pairing
    ? "Bağlı değil"
    : now.settings.paused
      ? "Duraklatıldı"
      : running
        ? `${running} iş sürüyor`
        : now.connection === "connected"
          ? "Bağlı · boşta"
          : "Bağlanıyor…";
  tray.setToolTip(`Slipwright Agent · ${status}`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: status, enabled: false },
      { type: "separator" },
      { label: "Aç", click: showWindow },
      {
        label: now.settings.paused ? "İş almaya devam et" : "İş almayı duraklat",
        click: () => {
          store.settings.paused = !store.settings.paused;
          store.save();
          push();
          worker.kick();
        },
      },
      { type: "separator" },
      {
        label: "Çık",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
}

// -- IPC ------------------------------------------------------------------------------

function ipc(): void {
  ipcMain.handle("state", () => state());
  ipcMain.handle("history", (): HistoryEntry[] => (DEMO ? demoHistory() : history.list()));
  ipcMain.handle("pair", (_e, code: string) => doPair(String(code)));
  ipcMain.handle("forget", (): Result => {
    forgetPairing(null);
    return { ok: true, message: "" };
  });
  ipcMain.handle("saveSettings", (_e, patch: Partial<Settings>) => {
    const allowed: (keyof Settings)[] = ["paused", "startAtLogin", "notOnBattery", "runBuilds", "notifyDone", "maxConcurrent", "workDir", "theme"];
    for (const key of allowed) if (key in patch) (store.settings as unknown as Record<string, unknown>)[key] = patch[key];
    store.settings.maxConcurrent = Math.max(1, Math.min(8, Math.round(Number(store.settings.maxConcurrent) || 1)));
    store.save();
    applySettings();
    push();
    worker.kick();
  });
  ipcMain.handle("saveAgent", (_e, agent: AgentId, patch: Partial<AgentSettings>) => {
    if (!AGENTS.includes(agent)) return;
    store.settings.agents[agent] = { ...store.settings.agents[agent], ...patch };
    store.save();
    push();
    worker.kick();
  });
  ipcMain.handle("saveSecret", (_e, name: keyof Secrets, value: string | null) => {
    if (!["anthropic", "openai", "github", "bitbucket", "jira"].includes(name)) return;
    store.setSecret(name, value ? String(value).trim() : null);
    push();
    worker.kick();
  });
  ipcMain.handle("saveSource", (_e, github: string | null, user: string | null, bitbucket: string | null) => verifySource(github, user, bitbucket));
  ipcMain.handle("saveJira", (_e, site: string, email: string, token: string | null) => verifyJira(site, email, token));
  ipcMain.handle("detect", () => redetect());
  ipcMain.handle("exportServerSettings", async (_e, withSecrets: boolean): Promise<Result> => {
    const picked = await dialog.showSaveDialog(window!, {
      defaultPath: "settings.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    if (picked.canceled || !picked.filePath) return { ok: false, message: "" };
    const file = fromApp(
      {
        agents: store.settings.agents,
        maxConcurrent: store.settings.maxConcurrent,
        runBuilds: store.settings.runBuilds,
        bitbucketUser: store.settings.bitbucket.user,
        jira: store.settings.jira,
      },
      {
        anthropic: store.secret("anthropic"),
        openai: store.secret("openai"),
        github: store.secret("github"),
        bitbucket: store.secret("bitbucket"),
        jira: store.secret("jira"),
      },
      "",
      withSecrets === true,
    );
    writeFileSync(picked.filePath, `${JSON.stringify(file, null, 2)}\n`, { mode: 0o600 });
    return { ok: true, message: picked.filePath };
  });
  ipcMain.handle("chooseWorkDir", async () => {
    const picked = await dialog.showOpenDialog(window!, { properties: ["openDirectory", "createDirectory"], defaultPath: store.settings.workDir });
    if (picked.canceled || !picked.filePaths[0]) return null;
    store.settings.workDir = picked.filePaths[0];
    store.save();
    push();
    return store.settings.workDir;
  });
}

// -- start ----------------------------------------------------------------------------

app.on("second-instance", showWindow);
app.on("activate", showWindow);
app.on("before-quit", () => {
  quitting = true;
});
app.on("window-all-closed", () => {
  // stays in the tray; quitting is the tray's "Çık"
  if (SCREENSHOT) app.quit();
});

void app.whenReady().then(async () => {
  if (process.platform === "win32") app.setAppUserModelId("app.slipwright.agent");
  await adoptShellPath();
  store = new Store(app.getPath("userData"), {
    available: () => safeStorage.isEncryptionAvailable(),
    seal: (text) => safeStorage.encryptString(text),
    unseal: (data) => safeStorage.decryptString(data),
  });
  history = new History(join(app.getPath("userData"), "history.json"));
  mkdirSync(store.settings.workDir, { recursive: true });
  worker = new Worker({
    client: () => (DEMO || SCREENSHOT ? null : client),
    name: () => machineName,
    capabilities,
    holding: () => (store.settings.paused ? "paused" : holding()),
    maxConcurrent: () => store.settings.maxConcurrent,
    workDir: () => store.settings.workDir,
    model: (agent) => store.settings.agents[agent].model,
    secret: (name) => store.secret(name),
    bitbucketUser: () => store.settings.bitbucket.user,
    jira: () => store.settings.jira,
    rememberJiraAccount: (account) => {
      store.settings.jira.account = account;
      store.save();
    },
    toolchainEnv: () => toolchains.env,
    recordHistory: (entry) => history.add(entry),
    connected: (ok, error) => {
      const next: Connection = ok ? "connected" : "offline";
      if (next !== connection || (error ?? null) !== connectionError) {
        connection = next;
        connectionError = ok ? null : (error ?? null);
        push();
      }
    },
    unpaired: (why) => forgetPairing(why),
    done: (entry) => {
      if (store.settings.notifyDone && Notification.isSupported()) {
        new Notification({ title: entry.goal || "Slipwright", body: entry.outcome }).show();
      }
    },
  });
  worker.on("change", push);
  ipc();
  applySettings();
  powerMonitor.on("on-battery", () => push());
  powerMonitor.on("on-ac", () => {
    push();
    worker.kick();
  });
  machineName = await computerName();
  connect();
  detecting = redetect();
  createWindow();
  if (!SCREENSHOT) {
    tray = new Tray(icon(process.platform === "darwin" ? 18 : 16));
    tray.on("click", showWindow);
    updateTray(state());
    worker.start();
    setInterval(() => void redetect(), 10 * 60_000);
  }
});

// -- the demo -------------------------------------------------------------------------

function demoState(base: AppState): AppState {
  const at = (s: number) => new Date(Date.now() - s * 1000).toISOString();
  const agents = { ...base.settings.agents };
  agents.backend = { enabled: true, model: { provider: "claude-code", model: "sonnet" } };
  agents.web = { enabled: true, model: { provider: "codex", model: "gpt-5" } };
  agents.mobile = { enabled: true, model: { provider: "claude-code", model: "opus" } };
  agents.devops = { enabled: false, model: null };
  return {
    ...base,
    machineName: "Ayşe'nin MacBook'u",
    pairing: { workerId: "demo", name: "Ayşe'nin MacBook'u", address: null, relay: { host: "relay.slipwright.app", room: "00" }, pairedAt: at(86400) },
    connection: "connected",
    settings: { ...base.settings, agents },
    detected: {
      claude: { installed: true, version: "2.1.0 (Claude Code)", signedIn: true },
      codex: { installed: true, version: "codex-cli 0.50.0", signedIn: true },
      ios: { ok: true, detail: "Xcode 17.0" },
      android: { ok: true, detail: "SDK 36" },
      checkedAt: at(10),
    },
    secrets: { ...base.secrets, anthropic: "sk-ant-••••3f9A", github: "github_pat_••••8Kq2" },
    tasks: [
      {
        id: "demo-1", kind: "write", agent: "backend", project: "Randevu uygulaması",
        goal: "Randevu API: oluşturma, iptal, listeleme", phase: 4, phases: 9, jiraKey: "SCRUM-131", platform: null,
        model: "claude-code · sonnet", startedAt: Date.now() - 245_000, timeoutS: 1800, status: "writing",
        log: [
          { at: at(245), text: "git fetch --depth 1 github.com/acme/randevu.git @ a1b2c3d", tone: "dim" },
          { at: at(241), text: "checked out a1b2c3d", tone: "ok" },
          { at: at(240), text: "Jira: SCRUM-131 → In Progress", tone: "dim" },
          { at: at(239), text: "claude sonnet started" },
        ],
      },
      {
        id: "demo-2", kind: "write", agent: "web", project: "Randevu uygulaması",
        goal: "Giriş ve kayıt ekranları", phase: 3, phases: 9, jiraKey: "SCRUM-130", platform: null,
        model: "codex · gpt-5", startedAt: Date.now() - 62_000, timeoutS: 1800, status: "writing",
        log: [
          { at: at(62), text: "git fetch --depth 1 github.com/acme/randevu.git @ a1b2c3d", tone: "dim" },
          { at: at(58), text: "codex gpt-5 started" },
          { at: at(30), text: "codex: rg -n \"login\" web/src" },
        ],
      },
    ],
  };
}

function demoHistory(): HistoryEntry[] {
  const at = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();
  return [
    { id: "h1", kind: "write", agent: "backend", project: "Randevu uygulaması", goal: "Veri modeli + migration", phase: 1, phases: 9, jiraKey: "SCRUM-128", seconds: 840, outcome: "answered", detail: "claude-sonnet-5-5", at: at(3) },
    { id: "h2", kind: "write", agent: "backend", project: "Randevu uygulaması", goal: "Auth: oturum ve token", phase: 2, phases: 9, jiraKey: "SCRUM-129", seconds: 1320, outcome: "answered", detail: null, at: at(2) },
    { id: "h3", kind: "build", agent: "mobile", project: "", goal: "ios build", phase: null, phases: null, jiraKey: null, seconds: 412, outcome: "built", detail: "exit 0", at: at(1.5) },
    { id: "h4", kind: "write", agent: "backend", project: "Kafe sadakat", goal: "Bildirim servisi", phase: 7, phases: 11, jiraKey: "SCRUM-99", seconds: 540, outcome: "taken-back", detail: null, at: at(1) },
  ];
}
