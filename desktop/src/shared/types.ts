// What the main process and the page say to each other. The page never sees a secret:
// keys and tokens go in through `save*` calls and come back only as a masked hint.

export const AGENTS = ["backend", "web", "mobile", "devops"] as const;
export type AgentId = (typeof AGENTS)[number];

export type ProviderId = "claude-code" | "codex" | "anthropic" | "openai";

export interface ModelChoice {
  provider: ProviderId;
  /** Empty means the provider's own default (the CLI's, or ours for an API key). */
  model: string;
}

export interface AgentSettings {
  enabled: boolean;
  model: ModelChoice | null;
}

export interface Settings {
  paused: boolean;
  startAtLogin: boolean;
  notOnBattery: boolean;
  runBuilds: boolean;
  notifyDone: boolean;
  maxConcurrent: number;
  workDir: string;
  theme: "system" | "light" | "dark";
  agents: Record<AgentId, AgentSettings>;
  github: { user: string | null };
  bitbucket: { user: string | null };
  jira: { site: string; email: string; account: string | null };
}

export interface Pairing {
  workerId: string;
  name: string;
  /** "http://192.168.1.20:8000" for a LAN pairing; null through the relay. */
  address: string | null;
  relay: { host: string; room: string } | null;
  pairedAt: string;
}

export type Connection = "unpaired" | "connecting" | "connected" | "offline";

export interface LogLine {
  at: string;
  text: string;
  tone?: "ok" | "bad" | "dim";
}

export interface TaskView {
  id: string;
  kind: "write" | "build";
  agent: AgentId;
  project: string;
  goal: string;
  phase: number | null;
  phases: number | null;
  jiraKey: string | null;
  platform: string | null;
  model: string;
  startedAt: number;
  timeoutS: number;
  status: string;
  log: LogLine[];
}

export interface HistoryEntry {
  id: string;
  kind: "write" | "build";
  agent: AgentId;
  project: string;
  goal: string;
  phase: number | null;
  phases: number | null;
  jiraKey: string | null;
  seconds: number;
  outcome: "answered" | "built" | "build-failed" | "taken-back" | "failed" | "timeout" | "rejected";
  detail: string | null;
  at: string;
}

export interface CliInfo {
  installed: boolean;
  version: string | null;
  /** true / false when it could be told cheaply, null when not. */
  signedIn: boolean | null;
}

export interface Detected {
  claude: CliInfo;
  codex: CliInfo;
  ios: { ok: boolean; detail: string | null };
  android: { ok: boolean; detail: string | null };
  checkedAt: string | null;
}

export interface Secrets {
  anthropic: string | null;
  openai: string | null;
  github: string | null;
  bitbucket: string | null;
  jira: string | null;
}

export interface AppState {
  version: string;
  machineName: string;
  pairing: Pairing | null;
  connection: Connection;
  connectionError: string | null;
  /** Why no work is being asked for even though nothing is paused by hand. */
  holding: "battery" | null;
  settings: Settings;
  /** Each secret only as a hint ("sk-ant-…3f9A") or null. */
  secrets: Secrets;
  detected: Detected;
  capabilities: string[];
  tasks: TaskView[];
}

export interface Result {
  ok: boolean;
  message: string;
}

/** The bridge the preload puts on `window.agent`. */
export interface AgentApi {
  state(): Promise<AppState>;
  onState(listener: (state: AppState) => void): () => void;
  history(): Promise<HistoryEntry[]>;
  pair(code: string): Promise<Result>;
  forget(): Promise<Result>;
  saveSettings(patch: Partial<Omit<Settings, "agents">>): Promise<void>;
  saveAgent(agent: AgentId, patch: Partial<AgentSettings>): Promise<void>;
  saveSecret(name: keyof Secrets, value: string | null): Promise<void>;
  saveSource(github: string | null, bitbucketUser: string | null, bitbucket: string | null): Promise<Result>;
  saveJira(site: string, email: string, token: string | null): Promise<Result>;
  detect(): Promise<Detected>;
  chooseWorkDir(): Promise<string | null>;
}
