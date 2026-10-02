// The project's code, at the commit a call was written from, for the model to read.
//
// One shallow fetch of exactly that commit into a cache per repository, then a copy of
// its tree (`git archive`) into the call's own directory. The copy is thrown away with
// the call; nothing the model could do to it reaches the cache or the remote.
//
// The token rides in an `http.extraheader` given to git through GIT_CONFIG_* variables:
// never in the URL (git would print it in errors and keep it in FETCH_HEAD), never in a
// config file, and not in argv either, where any process on the machine could read it.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import * as tar from "tar";
import { run, start, which } from "./proc";

export interface Repo {
  url: string;
  branch?: string | null;
  commit: string;
}

export interface SourceCredentials {
  github: string | null;
  bitbucketUser: string | null;
  bitbucket: string | null;
}

/** The Authorization header for this repository's host, or null for one we hold nothing
 *  for. A token is only ever sent to the host it belongs to. */
export function authHeader(url: string, creds: SourceCredentials): string | null {
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  const basic = (user: string, secret: string) => `Authorization: Basic ${Buffer.from(`${user}:${secret}`).toString("base64")}`;
  if ((host === "github.com" || host.endsWith(".github.com")) && creds.github) return basic("x-access-token", creds.github);
  if (host === "bitbucket.org" && creds.bitbucket && creds.bitbucketUser) return basic(creds.bitbucketUser, creds.bitbucket);
  return null;
}

export function gitEnv(header: string | null): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env, GIT_TERMINAL_PROMPT: "0", GCM_INTERACTIVE: "never" };
  if (header) {
    env.GIT_CONFIG_COUNT = "1";
    env.GIT_CONFIG_KEY_0 = "http.extraheader";
    env.GIT_CONFIG_VALUE_0 = header;
  }
  return env;
}

// two calls on one repository must not fetch into its cache at the same time
const locks = new Map<string, Promise<unknown>>();

async function locked<T>(key: string, work: () => Promise<T>): Promise<T> {
  const before = locks.get(key) ?? Promise.resolve();
  const mine = before.catch(() => undefined).then(work);
  locks.set(key, mine);
  try {
    return await mine;
  } finally {
    if (locks.get(key) === mine) locks.delete(key);
  }
}

/** The commit's tree in `into`. Throws with git's own words when it cannot. */
export async function checkout(repo: Repo, creds: SourceCredentials, cacheRoot: string, into: string, signal: AbortSignal, log: (t: string) => void): Promise<void> {
  const git = which("git");
  if (!git) throw new Error("git is not installed");
  if (!/^[0-9a-f]{7,64}$/i.test(repo.commit)) throw new Error("not a commit id");
  const cache = join(cacheRoot, createHash("sha256").update(repo.url).digest("hex").slice(0, 16) + ".git");
  const env = gitEnv(authHeader(repo.url, creds));
  await locked(cache, async () => {
    if (!existsSync(cache)) {
      mkdirSync(cache, { recursive: true });
      const init = await run(git, ["init", "--bare", "--quiet", cache], { env });
      if (init.code !== 0) throw new Error(init.stderr.trim() || "git init failed");
    }
    const have = await run(git, ["--git-dir", cache, "cat-file", "-e", `${repo.commit}^{commit}`], { env });
    if (have.code === 0) return;
    log(`git fetch --depth 1 ${repo.url.replace(/^https?:\/\//, "")} @ ${repo.commit.slice(0, 7)}`);
    const fetched = await run(git, ["--git-dir", cache, "fetch", "--depth", "1", "--no-tags", repo.url, repo.commit], { env, signal, timeoutMs: 5 * 60_000 });
    if (fetched.code !== 0) throw new Error(fetched.stderr.trim().split("\n").pop() || "git fetch failed");
  });
  mkdirSync(into, { recursive: true });
  const archive = start(git, ["--git-dir", cache, "archive", "--format=tar", repo.commit], { env, stdio: ["ignore", "pipe", "ignore"] });
  await pipeline(archive.stdout as Readable, tar.x({ cwd: into }));
}
