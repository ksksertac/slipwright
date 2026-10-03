// settings.json: everything a server needs to lend itself to an account, in the folder it
// is run from. The desktop app keeps the same things behind a window and the system
// keyring; a server reached over SSH has neither, so here they are one file a person
// edits and uploads (SFTP), and the program reads it at start and again when it changes.
//
// A secret may be written as "env:NAME" to be read from the environment instead -- for a
// key somebody would rather keep in a systemd unit or a CI secret than in a file.

import { AGENTS, type AgentId, type ModelChoice, type ProviderId } from "@shared/types";

export const PROVIDERS: ProviderId[] = ["claude-code", "codex", "anthropic", "openai"];

export interface FileAgent {
  enabled?: boolean;
  /** "claude-code", "claude-code:sonnet", "codex:gpt-5", "anthropic:claude-sonnet-5-5" … */
  model?: string | null;
}

/** settings.json as a person writes it. Every field may be left out. */
export interface SettingsFile {
  code?: string;
  name?: string;
  paused?: boolean;
  max_concurrent?: number;
  work_dir?: string;
  run_builds?: boolean;
  agents?: Partial<Record<AgentId, FileAgent>>;
  keys?: { anthropic?: string; openai?: string };
  source?: { github_token?: string; bitbucket_user?: string; bitbucket_app_password?: string };
  jira?: { site?: string; email?: string; token?: string };
}

/** settings.json once read: defaults filled in, "env:" resolved, models parsed. */
export interface AgentSettingsFile {
  code: string | null;
  name: string | null;
  paused: boolean;
  maxConcurrent: number;
  workDir: string;
  runBuilds: boolean;
  agents: Record<AgentId, { enabled: boolean; model: ModelChoice | null }>;
  secrets: {
    anthropic: string | null;
    openai: string | null;
    github: string | null;
    bitbucket: string | null;
    jira: string | null;
  };
  bitbucketUser: string | null;
  jira: { site: string; email: string };
}

export class SettingsError extends Error {}

const KNOWN = new Set(["code", "name", "paused", "max_concurrent", "work_dir", "run_builds", "agents", "keys", "source", "jira"]);

/** "codex:gpt-5" -> { provider: "codex", model: "gpt-5" }; "claude-code" -> its default. */
export function parseModel(text: string | null | undefined, where: string): ModelChoice | null {
  if (text == null || text === "") return null;
  const [provider, ...rest] = String(text).split(":");
  if (!PROVIDERS.includes(provider as ProviderId)) {
    throw new SettingsError(`${where}: "${text}" -- the model is one of ${PROVIDERS.join(", ")}, optionally ":<model>"`);
  }
  return { provider: provider as ProviderId, model: rest.join(":") };
}

function secret(value: unknown, where: string, env: NodeJS.ProcessEnv, missing: string[]): string | null {
  if (value == null || value === "") return null;
  if (typeof value !== "string") throw new SettingsError(`${where} must be text`);
  if (value.startsWith("env:")) {
    const name = value.slice(4);
    const found = env[name];
    if (!found) missing.push(`${where} names ${name}, which is not set`);
    return found || null;
  }
  return value;
}

/**
 * Reads what a person wrote. What is wrong enough to do the wrong thing -- a model nobody
 * can run, a number that is not one -- is an error; what is merely unknown is a warning,
 * so a key from a newer version does not stop an older program.
 */
export function readSettings(
  raw: unknown,
  { env = process.env, defaultWorkDir }: { env?: NodeJS.ProcessEnv; defaultWorkDir: string },
): { settings: AgentSettingsFile; warnings: string[] } {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new SettingsError("settings.json must be one JSON object");
  }
  const file = raw as SettingsFile & Record<string, unknown>;
  const warnings = Object.keys(file)
    .filter((k) => !KNOWN.has(k) && !k.startsWith("_"))
    .map((k) => `settings.json: "${k}" is not a setting; it is ignored`);
  const missing: string[] = [];

  const max = file.max_concurrent ?? 1;
  if (!Number.isInteger(max) || max < 1 || max > 8) throw new SettingsError("max_concurrent is a whole number from 1 to 8");

  const agents = {} as AgentSettingsFile["agents"];
  for (const agent of AGENTS) {
    const own = file.agents?.[agent];
    // devops is off unless asked for, as in the app: an infra phase deploys things
    const enabled = own?.enabled ?? (own?.model ? true : agent !== "devops");
    agents[agent] = { enabled, model: parseModel(own?.model, `agents.${agent}.model`) };
  }
  for (const key of Object.keys(file.agents ?? {})) {
    if (!(AGENTS as readonly string[]).includes(key)) warnings.push(`agents.${key} is not an agent (${AGENTS.join(", ")})`);
  }

  const settings: AgentSettingsFile = {
    code: typeof file.code === "string" && file.code.trim() ? file.code.trim() : null,
    name: typeof file.name === "string" && file.name.trim() ? file.name.trim().slice(0, 120) : null,
    paused: file.paused === true,
    maxConcurrent: max,
    workDir: typeof file.work_dir === "string" && file.work_dir ? file.work_dir : defaultWorkDir,
    runBuilds: file.run_builds !== false,
    agents,
    secrets: {
      anthropic: secret(file.keys?.anthropic, "keys.anthropic", env, missing),
      openai: secret(file.keys?.openai, "keys.openai", env, missing),
      github: secret(file.source?.github_token, "source.github_token", env, missing),
      bitbucket: secret(file.source?.bitbucket_app_password, "source.bitbucket_app_password", env, missing),
      jira: secret(file.jira?.token, "jira.token", env, missing),
    },
    bitbucketUser: file.source?.bitbucket_user || null,
    jira: { site: file.jira?.site ?? "", email: file.jira?.email ?? "" },
  };
  for (const agent of AGENTS) {
    const choice = agents[agent].model;
    if (agents[agent].enabled && choice?.provider === "anthropic" && !settings.secrets.anthropic) {
      warnings.push(`agents.${agent} writes with an Anthropic key, and keys.anthropic is empty`);
    }
    if (agents[agent].enabled && choice?.provider === "openai" && !settings.secrets.openai) {
      warnings.push(`agents.${agent} writes with an OpenAI key, and keys.openai is empty`);
    }
  }
  return { settings, warnings: [...warnings, ...missing] };
}

/** The app's own choices as a settings.json for a server: what somebody sets up behind
 *  the window once, then uploads. Keys travel only when asked for -- a file is easier to
 *  leave lying about than a keyring -- and are otherwise left as "env:" names to fill. */
export function fromApp(
  app: { agents: Record<AgentId, { enabled: boolean; model: ModelChoice | null }>; maxConcurrent: number; runBuilds: boolean; bitbucketUser: string | null; jira: { site: string; email: string } },
  secrets: AgentSettingsFile["secrets"],
  name: string,
  withSecrets: boolean,
): SettingsFile & Record<string, unknown> {
  const own = (value: string | null, env: string) => (withSecrets ? (value ?? "") : value ? `env:${env}` : "");
  const agents = Object.fromEntries(
    AGENTS.map((a) => {
      const m = app.agents[a].model;
      return [a, { enabled: app.agents[a].enabled, model: m ? (m.model ? `${m.provider}:${m.model}` : m.provider) : null }];
    }),
  ) as Partial<Record<AgentId, FileAgent>>;
  return {
    _help: template(name)._help,
    code: "",
    _code: template(name)._code,
    name,
    paused: false,
    max_concurrent: app.maxConcurrent,
    work_dir: "./work",
    run_builds: app.runBuilds,
    agents,
    keys: { anthropic: own(secrets.anthropic, "ANTHROPIC_API_KEY"), openai: own(secrets.openai, "OPENAI_API_KEY") },
    source: {
      github_token: own(secrets.github, "GITHUB_TOKEN"),
      bitbucket_user: app.bitbucketUser ?? "",
      bitbucket_app_password: own(secrets.bitbucket, "BITBUCKET_APP_PASSWORD"),
    },
    jira: { site: app.jira.site, email: app.jira.email, token: own(secrets.jira, "JIRA_TOKEN") },
  };
}

/** What `slipwright-agent init` writes: every setting, with what it means beside it. */
export function template(name: string): SettingsFile & Record<string, unknown> {
  return {
    _help: "Slipwright Agent on a server. Fields starting with _ are notes and are ignored. A secret may be \"env:NAME\" to read it from the environment.",
    code: "",
    _code: "The connection code from Slipwright: Settings -> Machines -> Connect a machine. Used once; the pairing is kept in slipwright-agent.state.json beside this file.",
    name,
    paused: false,
    max_concurrent: 1,
    work_dir: "./work",
    run_builds: true,
    agents: {
      backend: { enabled: true, model: "claude-code" },
      web: { enabled: true, model: "claude-code" },
      mobile: { enabled: true, model: "claude-code" },
      devops: { enabled: false, model: null },
    },
    _models: "claude-code, codex, anthropic or openai; add :<model> to choose one, e.g. claude-code:sonnet, codex:gpt-5, anthropic:claude-sonnet-5-5",
    keys: { anthropic: "", openai: "" },
    source: { github_token: "", bitbucket_user: "", bitbucket_app_password: "" },
    _source: "Read access is enough: the model reads the repository, and only Slipwright ever pushes.",
    jira: { site: "", email: "", token: "" },
  };
}
