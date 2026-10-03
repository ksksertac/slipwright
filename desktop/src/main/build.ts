// A mobile build handed to this machine (T14), as `slipwright worker` does it.
//
// The commands were written by a model, so they are treated the way the server treats a
// project's own commands (`gates/env.py`): an environment of named variables only -- a
// person's API keys and tokens in their shell are simply not there -- a fresh directory
// per build that is deleted afterwards, and only the commands of the build handed over.

import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import * as tar from "tar";
import type { Build } from "./client";
import { run } from "./proc";

/** Kept for every build's output, as the server's gate keeps it. */
export const MAX_OUTPUT = 200_000;

/** gates/env.py's ALLOWED, name for name. */
export const ALLOWED = [
  "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "CI", "TERM", "COLUMNS",
  "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT",
  // Windows: without these, spawning anything at all fails
  "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
  "PROCESSOR_ARCHITECTURE", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
  "PROGRAMFILES(X86)", "PROGRAMDATA",
];

export function projectEnv(source: NodeJS.ProcessEnv, extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  // Windows names are case-insensitive and Node keeps whichever case the OS gave
  const upper = new Map(Object.entries(source).map(([k, v]) => [k.toUpperCase(), [k, v] as const]));
  const env: NodeJS.ProcessEnv = {};
  for (const name of ALLOWED) {
    const found = upper.get(name);
    if (found && found[1] !== undefined) env[found[0]] = found[1];
  }
  env.CI ??= "1";
  return { ...env, ...extra };
}

/** Unpack only files and directories: no links that could point out of the build
 *  directory, no devices. node-tar already refuses absolute paths and `..`. */
export async function unpack(snapshot: Buffer, into: string): Promise<void> {
  await pipeline(
    Readable.from(snapshot),
    tar.x({ cwd: into, filter: (_path, entry) => "type" in entry && (entry.type === "File" || entry.type === "Directory") }),
  );
}

function shell(cmd: string): [string, string[]] {
  return process.platform === "win32"
    ? [process.env.ComSpec ?? "cmd.exe", ["/d", "/s", "/c", `"${cmd}"`]]
    : ["/bin/sh", ["-c", cmd]];
}

export async function runBuild(
  task: Build,
  snapshot: Buffer,
  options: { workDir: string; toolchainEnv: Record<string, string>; signal: AbortSignal; log: (t: string, tone?: "ok" | "bad") => void },
): Promise<{ exit_code: number; output: string; seconds: number }> {
  const started = Date.now();
  const where = mkdtempSync(join(options.workDir, "build-"));
  const chunks: string[] = [];
  let code = 0;
  try {
    await unpack(snapshot, where);
    const env = projectEnv(process.env, options.toolchainEnv);
    for (const [label, cmd] of task.commands) {
      options.log(`$ ${cmd}`);
      const [file, args] = shell(cmd);
      const ran = await run(file, args, { cwd: where, env, timeoutMs: task.timeout_s * 1000, signal: options.signal, keep: MAX_OUTPUT, verbatim: true });
      code = ran.timedOut ? 124 : (ran.code ?? 1);
      let output = (ran.stdout + ran.stderr).trimEnd();
      if (ran.timedOut) output += `\n[timed out after ${task.timeout_s}s]`;
      chunks.push(`$ ${cmd}\n${output}\n[${label}: exit ${code}]`);
      options.log(`${label}: exit ${code}`, code === 0 ? "ok" : "bad");
      if (code !== 0 || ran.cancelled) break;
    }
  } finally {
    rmSync(where, { recursive: true, force: true, maxRetries: 3 });
  }
  const text = chunks.join("\n\n");
  return { exit_code: code, output: text.slice(-MAX_OUTPUT), seconds: (Date.now() - started) / 1000 };
}
