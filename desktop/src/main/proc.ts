// Starting other programs -- `claude`, `codex`, `git`, a build's shell line -- and, more
// to the point, stopping them.
//
// Two things here were learned the hard way elsewhere in Slipwright:
//  * `codex` on the PATH is a Node script that starts the real binary as its child.
//    Killing only the process we started left the binary thinking, on the person's plan,
//    for an answer nobody wanted (providers/codex.py). So every child is started at the
//    head of a group of its own and the whole tree is ended together.
//  * An app started from the Dock or the Start menu does not get the PATH a terminal has.
//    `claude` in ~/.local/bin or /opt/homebrew/bin is simply not found. So the login
//    shell is asked for its PATH once, and the usual install places are added.

import { execFile, spawn, type ChildProcess, type SpawnOptions } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, extname, join } from "node:path";

const IS_WIN = process.platform === "win32";

/** Called once at startup: widen PATH to what a terminal would have. */
export async function adoptShellPath(env: NodeJS.ProcessEnv = process.env): Promise<void> {
  const home = homedir();
  const extra = IS_WIN
    ? [join(home, ".local", "bin"), join(process.env.APPDATA ?? "", "npm")]
    : [join(home, ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin", join(home, ".npm-global", "bin"), join(home, ".volta", "bin")];
  let fromShell: string | null = null;
  if (!IS_WIN) {
    const shell = env.SHELL || (process.platform === "darwin" ? "/bin/zsh" : "/bin/bash");
    fromShell = await new Promise<string | null>((resolve) => {
      // -i -l: the files a terminal reads; the marker keeps a chatty profile's output out
      execFile(shell, ["-ilc", 'printf "__SWPATH__%s__SWPATH__" "$PATH"'], { timeout: 5000 }, (error, stdout) => {
        const found = /__SWPATH__(.*)__SWPATH__/.exec(String(stdout ?? ""));
        resolve(error && !found ? null : (found?.[1] ?? null));
      });
    });
  }
  const parts = [...(fromShell ?? "").split(delimiter), ...(env.PATH ?? "").split(delimiter), ...extra].filter(Boolean);
  env.PATH = [...new Set(parts)].join(delimiter);
}

/** Where `name` is on PATH, honouring PATHEXT on Windows; null when it is not there. */
export function which(name: string, env: NodeJS.ProcessEnv = process.env): string | null {
  const dirs = (env.PATH ?? env.Path ?? "").split(delimiter).filter(Boolean);
  const exts = IS_WIN ? (env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM").split(";").map((e) => e.toLowerCase()) : [""];
  for (const dir of dirs) {
    for (const ext of IS_WIN && extname(name) ? [""] : exts) {
      const candidate = join(dir, name + ext);
      try {
        if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
      } catch {
        // unreadable directory on PATH: skip it
      }
    }
  }
  return null;
}

// cmd.exe's own quoting: wrap in quotes and double any quote inside. Only flags, model
// names and temp paths are ever passed this way -- prompts always go on stdin
function cmdQuote(arg: string): string {
  if (/^[\w./:=@,+-]+$/.test(arg)) return arg;
  return `"${arg.replace(/"/g, '""')}"`;
}

/** Start `file` with `args` at the head of its own process group. A Windows `.cmd` shim
 *  (how npm installs `codex`) cannot be started without a shell since Node's 2024 fix
 *  for batch-file injection, so it goes through `cmd.exe /d /s /c` with every argument
 *  quoted here, never through `shell: true` and its guessing. */
export function start(file: string, args: string[], options: SpawnOptions = {}): ChildProcess {
  if (IS_WIN && /\.(cmd|bat)$/i.test(file)) {
    const line = [file, ...args].map(cmdQuote).join(" ");
    return spawn(process.env.ComSpec ?? "cmd.exe", ["/d", "/s", "/c", `"${line}"`], {
      ...options,
      windowsVerbatimArguments: true,
      windowsHide: true,
    });
  }
  return spawn(file, args, { ...options, detached: !IS_WIN, windowsHide: true });
}

/** End `child` and everything it started. */
export function killTree(child: ChildProcess): void {
  if (child.pid === undefined || child.exitCode !== null) return;
  if (IS_WIN) {
    spawn("taskkill", ["/F", "/T", "/PID", String(child.pid)], { windowsHide: true, stdio: "ignore" }).on("error", () => undefined);
  } else {
    try {
      process.kill(-child.pid, "SIGKILL"); // the group: started detached, so it leads one
    } catch {
      // already gone
    }
  }
  try {
    child.kill("SIGKILL"); // whatever the group kill missed, the head at least
  } catch {
    // already gone
  }
}

export interface Ran {
  code: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  cancelled: boolean;
}

export interface RunOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  stdin?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  onStdout?: (chunk: string) => void;
  onStderr?: (chunk: string) => void;
  /** Keep only the last this many characters of each stream. */
  keep?: number;
  /** Windows: pass the arguments as written (a shell line for cmd.exe /s /c). */
  verbatim?: boolean;
}

/** Run to the end, or until the timeout or the signal ends the whole tree. */
export function run(file: string, args: string[], options: RunOptions = {}): Promise<Ran> {
  return new Promise((resolve, reject) => {
    let child: ChildProcess;
    try {
      child = start(file, args, {
        cwd: options.cwd,
        env: options.env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsVerbatimArguments: options.verbatim,
      });
    } catch (error) {
      reject(error);
      return;
    }
    const keep = options.keep ?? 5_000_000;
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let cancelled = false;
    child.stdout?.setEncoding("utf8").on("data", (chunk: string) => {
      stdout = (stdout + chunk).slice(-keep);
      options.onStdout?.(chunk);
    });
    child.stderr?.setEncoding("utf8").on("data", (chunk: string) => {
      stderr = (stderr + chunk).slice(-keep);
      options.onStderr?.(chunk);
    });
    const timer = options.timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          killTree(child);
        }, options.timeoutMs)
      : null;
    const onAbort = () => {
      cancelled = true;
      killTree(child);
    };
    if (options.signal?.aborted) onAbort();
    options.signal?.addEventListener("abort", onAbort, { once: true });
    child.once("error", (error) => {
      if (timer) clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      reject(error);
    });
    child.once("close", (code) => {
      if (timer) clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      resolve({ code, stdout, stderr, timedOut, cancelled });
    });
    child.stdin?.on("error", () => undefined); // a child that exits early closes its stdin
    child.stdin?.end(options.stdin ?? "");
  });
}

/** A short command whose output is all that matters: `--version` and the like. */
export async function output(name: string, args: string[], timeoutMs = 10_000): Promise<string | null> {
  const file = which(name);
  if (!file) return null;
  try {
    const ran = await run(file, args, { timeoutMs });
    return ran.code === 0 ? (ran.stdout || ran.stderr).trim() : null;
  } catch {
    return null;
  }
}
