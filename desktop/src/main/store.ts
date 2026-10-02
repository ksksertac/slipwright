// What the app keeps between runs, in two files under userData:
//   settings.json -- what a person chose; nothing in it would hurt anybody to read
//   secrets.bin   -- tokens and keys, each sealed with Electron's safeStorage (the
//                    Keychain on macOS, DPAPI on Windows, the keyring on Linux)
// The sealing is injected so the tests can run without Electron.

import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { AGENTS, type AgentId, type AgentSettings, type Pairing, type Settings } from "@shared/types";

export interface Sealer {
  available(): boolean;
  seal(text: string): Buffer;
  unseal(data: Buffer): string;
}

/** Every secret the app holds, by name. The first three are the pairing's. */
export type SecretName =
  | "token"
  | "relayClientSk"
  | "serverPk"
  | "anthropic"
  | "openai"
  | "github"
  | "bitbucket"
  | "jira";

export function defaultSettings(): Settings {
  const agents = Object.fromEntries(
    AGENTS.map((a): [AgentId, AgentSettings] => [a, { enabled: a !== "devops", model: null }]),
  ) as Record<AgentId, AgentSettings>;
  return {
    paused: false,
    startAtLogin: false,
    notOnBattery: true,
    runBuilds: true,
    notifyDone: false,
    maxConcurrent: 1,
    workDir: join(homedir(), "Slipwright Agent", "work"),
    theme: "system",
    agents,
    github: { user: null },
    bitbucket: { user: null },
    jira: { site: "", email: "", account: null },
  };
}

interface OnDisk {
  settings: Settings;
  pairing: Pairing | null;
}

function writeAtomic(path: string, data: string | Buffer): void {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.tmp`;
  writeFileSync(temp, data, { mode: 0o600 });
  renameSync(temp, path); // a crash mid-write leaves the old file, never half of one
  try {
    chmodSync(path, 0o600);
  } catch {
    // Windows: the profile directory is the protection
  }
}

export class Store {
  settings: Settings;
  pairing: Pairing | null;
  private secrets: Partial<Record<SecretName, string>> = {};

  constructor(
    private readonly dir: string,
    private readonly sealer: Sealer,
  ) {
    const loaded = this.readSettings();
    this.settings = loaded.settings;
    this.pairing = loaded.pairing;
    this.secrets = this.readSecrets();
  }

  private get settingsPath(): string {
    return join(this.dir, "settings.json");
  }

  private get secretsPath(): string {
    return join(this.dir, "secrets.bin");
  }

  private readSettings(): OnDisk {
    const base = defaultSettings();
    try {
      const raw = JSON.parse(readFileSync(this.settingsPath, "utf8")) as Partial<OnDisk>;
      const s = raw.settings ?? ({} as Partial<Settings>);
      // merged over the defaults, so a setting added in a later version has a value
      const agents = { ...base.agents };
      for (const a of AGENTS) agents[a] = { ...base.agents[a], ...(s.agents?.[a] ?? {}) };
      return {
        settings: { ...base, ...s, agents, jira: { ...base.jira, ...(s.jira ?? {}) } },
        pairing: raw.pairing ?? null,
      };
    } catch {
      return { settings: base, pairing: null };
    }
  }

  private readSecrets(): Partial<Record<SecretName, string>> {
    if (!existsSync(this.secretsPath) || !this.sealer.available()) return {};
    try {
      const sealed = JSON.parse(readFileSync(this.secretsPath, "utf8")) as Record<string, string>;
      const out: Partial<Record<SecretName, string>> = {};
      for (const [name, value] of Object.entries(sealed)) {
        out[name as SecretName] = this.sealer.unseal(Buffer.from(value, "base64"));
      }
      return out;
    } catch {
      // sealed by another user or machine (a copied profile): unreadable is as good as gone
      return {};
    }
  }

  save(): void {
    writeAtomic(this.settingsPath, JSON.stringify({ settings: this.settings, pairing: this.pairing } satisfies OnDisk, null, 2));
  }

  secret(name: SecretName): string | null {
    return this.secrets[name] ?? null;
  }

  /** Without safeStorage (a Linux desktop with no keyring) secrets live for this run
   *  only: a token on disk in the clear is worse than pairing again. */
  setSecret(name: SecretName, value: string | null): void {
    if (value) this.secrets[name] = value;
    else delete this.secrets[name];
    if (!this.sealer.available()) return;
    const sealed: Record<string, string> = {};
    for (const [key, text] of Object.entries(this.secrets)) {
      if (text) sealed[key] = this.sealer.seal(text).toString("base64");
    }
    writeAtomic(this.secretsPath, JSON.stringify(sealed));
  }

  persistent(): boolean {
    return this.sealer.available();
  }
}

/** "sk-ant-…3f9A": enough to recognise a key, never enough to use it. */
export function hint(secret: string | null): string | null {
  if (!secret) return null;
  if (secret.length <= 8) return "••••";
  const head = /^(sk-ant-|sk-proj-|sk-|github_pat_|ghp_|ATATT)/.exec(secret)?.[1] ?? "";
  return `${head}••••${secret.slice(-4)}`;
}
