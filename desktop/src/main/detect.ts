// What this machine has: the model CLIs a person may already be signed in to, and the
// toolchains a mobile build needs. Looked at on start and when the Models page asks.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { CliInfo, Detected } from "@shared/types";
import { output, which } from "./proc";

export const NOTHING: Detected = {
  claude: { installed: false, version: null, signedIn: null },
  codex: { installed: false, version: null, signedIn: null },
  ios: { ok: false, detail: null },
  android: { ok: false, detail: null },
  checkedAt: null,
};

export interface Toolchains {
  /** Variables a build needs to find the Android SDK; added to its allow-listed env. */
  env: Record<string, string>;
}

export const toolchains: Toolchains = { env: {} };

export async function detect(): Promise<Detected> {
  const [claude, codex, ios, android] = await Promise.all([detectClaude(), detectCodex(), detectIos(), detectAndroid()]);
  return { claude, codex, ios, android, checkedAt: new Date().toISOString() };
}

function firstLine(text: string | null): string | null {
  return text ? (text.split(/\r?\n/)[0] ?? "").trim() || null : null;
}

// Signed in or not is only a hint, and only where it costs a file read: asking the CLI
// would spend a request on the person's plan. "Not known" is said as null, never false,
// so an agent is not switched off on a guess -- a call that is refused says so plainly.
async function detectClaude(): Promise<CliInfo> {
  const version = firstLine(await output("claude", ["--version"]));
  if (!version) return { installed: false, version: null, signedIn: null };
  const home = homedir();
  let signedIn: boolean | null = null;
  try {
    const config = JSON.parse(readFileSync(join(home, ".claude.json"), "utf8")) as { oauthAccount?: unknown };
    if (config.oauthAccount) signedIn = true;
  } catch {
    // no config yet: never run, or run elsewhere
  }
  if (signedIn === null && existsSync(join(home, ".claude", ".credentials.json"))) signedIn = true;
  return { installed: true, version, signedIn };
}

async function detectCodex(): Promise<CliInfo> {
  const version = firstLine(await output("codex", ["--version"]));
  if (!version) return { installed: false, version: null, signedIn: null };
  const home = process.env.CODEX_HOME || join(homedir(), ".codex");
  return { installed: true, version, signedIn: existsSync(join(home, "auth.json")) ? true : null };
}

/** `xcodebuild` is run, not just found: the Command Line Tools install a stub of it that
 *  only says Xcode is required. */
async function detectIos(): Promise<Detected["ios"]> {
  if (process.platform !== "darwin") return { ok: false, detail: null };
  if (!which("xcodebuild")) return { ok: false, detail: "no-xcode" };
  const said = firstLine(await output("xcodebuild", ["-version"], 60_000));
  return said ? { ok: true, detail: said } : { ok: false, detail: "xcode-unopened" };
}

/** An SDK with platforms in it and a JDK. Android Studio keeps both in places of its own,
 *  so they are looked for there when the environment does not name them. */
async function detectAndroid(): Promise<Detected["android"]> {
  const home = homedir();
  const sdkCandidates = [
    process.env.ANDROID_HOME,
    process.env.ANDROID_SDK_ROOT,
    process.platform === "darwin" ? join(home, "Library", "Android", "sdk") : null,
    process.platform === "win32" ? join(process.env.LOCALAPPDATA ?? "", "Android", "Sdk") : null,
    process.platform === "linux" ? join(home, "Android", "Sdk") : null,
  ].filter((p): p is string => !!p);
  const sdk = sdkCandidates.find((p) => existsSync(join(p, "platforms")));
  const studioJdk = [
    "/Applications/Android Studio.app/Contents/jbr/Contents/Home",
    join(process.env.ProgramFiles ?? "C:\\Program Files", "Android", "Android Studio", "jbr"),
    "/opt/android-studio/jbr",
  ].find((p) => existsSync(p));
  const java = process.env.JAVA_HOME || studioJdk || (which("java") ? "" : null);
  if (!sdk || java === null) {
    toolchains.env = {};
    return { ok: false, detail: sdk ? "no-jdk" : null };
  }
  toolchains.env = { ANDROID_HOME: sdk, ...(java ? { JAVA_HOME: java } : {}) };
  let level = "";
  try {
    const levels = readdirSync(join(sdk, "platforms"))
      .map((d) => Number(/android-(\d+)/.exec(d)?.[1]))
      .filter((n) => !Number.isNaN(n));
    if (levels.length) level = ` ${Math.max(...levels)}`;
  } catch {
    // the name was enough
  }
  return { ok: true, detail: `SDK${level}` };
}
