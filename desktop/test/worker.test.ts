// The loop against a scripted server: a call is taken, written by the model, answered;
// a call the server takes back (409 on progress) is dropped without an answer.

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HistoryEntry } from "@shared/types";
import type { Call, WorkerClient } from "../src/main/client";
import { Worker, type WorkerHost } from "../src/main/worker";

const CALL: Call = {
  kind: "write",
  id: "c1",
  job_id: "j1",
  project: "Randevu",
  phase: 4,
  phases: 9,
  goal: "Randevu API",
  domain: "backend",
  system: "You write code.",
  prompt: "Write phase 4 as JSON.",
  timeout_s: 30,
  repo: null,
};

function sse(text: string): Response {
  const events = [
    { type: "message_start", message: { model: "claude-sonnet-5-5", usage: { input_tokens: 9 } } },
    { type: "content_block_delta", delta: { type: "text_delta", text } },
    { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 3 } },
  ];
  return new Response(events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(""), { status: 200 });
}

function scripted(progressStatus: number) {
  let handed = false;
  const calls: { what: string; body?: unknown }[] = [];
  const client = {
    poll: vi.fn(async () => {
      if (handed) {
        await new Promise((r) => setTimeout(r, 20));
        return null;
      }
      handed = true;
      return CALL;
    }),
    heartbeat: vi.fn(async () => undefined),
    progress: vi.fn(async (_id: string, text: string) => {
      calls.push({ what: "progress", body: text });
      return progressStatus;
    }),
    answer: vi.fn(async (_id: string, body: unknown) => {
      calls.push({ what: "answer", body });
      return 204;
    }),
    fail: vi.fn(async (_id: string, body: unknown) => {
      calls.push({ what: "fail", body });
      return 204;
    }),
  };
  return { client: client as unknown as WorkerClient, calls };
}

let dir: string;
afterEach(() => {
  vi.unstubAllGlobals();
  rmSync(dir, { recursive: true, force: true });
});

function host(client: WorkerClient, done: (e: HistoryEntry) => void): WorkerHost {
  dir = mkdtempSync(join(tmpdir(), "sw-worker-"));
  return {
    client: () => client,
    name: () => "pc",
    capabilities: () => ["write:backend"],
    holding: () => null,
    maxConcurrent: () => 1,
    workDir: () => dir,
    model: () => ({ provider: "anthropic", model: "" }),
    secret: (name) => (name === "anthropic" ? "sk-ant-test" : null),
    bitbucketUser: () => null,
    jira: () => ({ site: "", email: "", account: null }),
    rememberJiraAccount: () => undefined,
    toolchainEnv: () => ({}),
    recordHistory: () => undefined,
    connected: () => undefined,
    unpaired: () => undefined,
    done,
  };
}

describe("a call handed to this machine", () => {
  it("is written by the chosen model and answered with its text, exactly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse('{"files":[]}')));
    const { client, calls } = scripted(204);
    const finished = new Promise<HistoryEntry>((resolve) => {
      const worker = new Worker(host(client, (e) => {
        void worker.stop();
        resolve(e);
      }));
      worker.start();
    });
    const entry = await finished;
    expect(entry).toMatchObject({ outcome: "answered", agent: "backend", phase: 4 });
    expect(calls[0]).toEqual({ what: "progress", body: "hazırlanıyor · <1 dk" });
    const answer = calls.find((c) => c.what === "answer")!.body as Record<string, unknown>;
    expect(answer).toMatchObject({ text: '{"files":[]}', model: "claude-sonnet-5-5", input_tokens: 9, output_tokens: 3 });
    expect(calls.some((c) => c.what === "fail")).toBe(false);
  });

  it("taken back by the server (409) is dropped: no answer, no failure", async () => {
    // the model takes its time; the first progress already says the call is gone
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((resolve, reject) => {
            const timer = setTimeout(() => resolve(sse("{}")), 5000);
            init.signal?.addEventListener("abort", () => {
              clearTimeout(timer);
              reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
            });
          }),
      ),
    );
    const { client, calls } = scripted(409);
    const entry = await new Promise<HistoryEntry>((resolve) => {
      const worker = new Worker(host(client, (e) => {
        void worker.stop();
        resolve(e);
      }));
      worker.start();
    });
    expect(entry.outcome).toBe("taken-back");
    expect(calls.map((c) => c.what)).toEqual(["progress"]);
  });

  it("refused by the key's vendor is failed as rejected, so the server falls back at once", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { message: "invalid x-api-key" } }), { status: 401 })));
    const { client, calls } = scripted(204);
    const entry = await new Promise<HistoryEntry>((resolve) => {
      const worker = new Worker(host(client, (e) => {
        void worker.stop();
        resolve(e);
      }));
      worker.start();
    });
    expect(entry.outcome).toBe("rejected");
    expect(calls.find((c) => c.what === "fail")!.body).toMatchObject({ kind: "rejected" });
  });
});
