// The worker API (docs/machines-protocol.md §1) over whichever transport the pairing
// chose, and pairing itself. Nothing here knows whether the bytes go over a LAN or
// through the relay.

import { unpack } from "./code";
import * as box from "./crypto";
import { candidates } from "./lan";
import { detail, DirectTransport, json, RelayTransport, TransportError, type Reply, type Transport } from "./transport";

/** The server no longer knows this machine (401), or a code was refused. */
export class Unpaired extends Error {}

export interface Paired {
  workerId: string;
  token: string;
  address: string | null;
  relay: { host: string; room: string } | null;
  /** Only through the relay: this machine's secret key and the server's public key. */
  clientSk: Buffer | null;
  serverPk: Buffer | null;
}

export interface PairOptions {
  name: string;
  capabilities: string[];
  lookAround?: (port: number) => Promise<string[]>;
  connectRelay?: ConstructorParameters<typeof RelayTransport>[3];
}

export async function pair(code: string, options: PairOptions): Promise<Paired> {
  const { address, secret } = unpack(code); // a bad copy is refused before the network
  const body = { code: code.trim(), name: options.name, capabilities: options.capabilities };
  if (address.kind === "relay") {
    const keys = { client: box.newKeyPair(), server: null };
    const relay = new RelayTransport(address.host, address.room, keys, options.connectRelay);
    try {
      await relay.handshake(secret);
      const got = await relay.request("POST", "/api/worker/pair", body, { timeoutMs: 30_000 });
      if (got.status !== 200) throw new Unpaired(detail(got));
      const answer = json<{ worker_id: string; token: string }>(got);
      return {
        workerId: answer.worker_id,
        token: answer.token,
        address: null,
        relay: { host: address.host, room: address.room },
        clientSk: keys.client.secret,
        serverPk: keys.server,
      };
    } finally {
      relay.close();
    }
  }
  // the first refusal is the one to show: a server further down the list that never made
  // this code would only say it does not know it
  let refused: string | null = null;
  for await (const candidate of candidates(address.url, options.lookAround)) {
    let got: Reply;
    try {
      got = await new DirectTransport(candidate).request("POST", "/api/worker/pair", body, { timeoutMs: 15_000 });
    } catch (error) {
      if (error instanceof TransportError) continue;
      throw error;
    }
    if (got.status === 200) {
      const answer = json<{ worker_id: string; token: string }>(got);
      return { workerId: answer.worker_id, token: answer.token, address: candidate, relay: null, clientSk: null, serverPk: null };
    }
    refused ??= detail(got);
  }
  if (refused) throw new Unpaired(refused);
  const port = new URL(address.url).port || "80";
  throw new Unpaired(`no Slipwright server found: tried ${address.url}, this machine and its network on port ${port}`);
}

export interface Build {
  kind: "build";
  id: string;
  job_id: string;
  platform: string;
  commands: [string, string][];
  timeout_s: number;
}

export interface Call {
  kind: "write";
  id: string;
  job_id: string;
  project?: string;
  phase?: number;
  phases?: number;
  goal?: string;
  role?: string;
  domain?: string;
  jira_key?: string | null;
  system: string;
  prompt: string;
  output_schema?: unknown;
  images?: { media_type: string; data: string; label?: string | null }[];
  thinking_depth?: string | null;
  timeout_s?: number;
  repo?: { url: string; branch?: string | null; commit: string } | null;
}

export type Task = Build | Call;

export class WorkerClient {
  constructor(
    readonly transport: Transport,
    private readonly token: string,
  ) {}

  private async call(method: string, path: string, body?: unknown, timeoutMs?: number): Promise<Reply> {
    const reply = await this.transport.request(method, `/api/worker${path}`, body, { token: this.token, timeoutMs });
    if (reply.status === 401) throw new Unpaired("the server does not know this machine any more; pair it again");
    return reply;
  }

  async poll(capabilities: string[], name: string, waitS = 25): Promise<Task | null> {
    const got = await this.call("POST", "/poll", { capabilities, wait_s: waitS, name }, (waitS + 35) * 1000);
    if (got.status === 204) return null;
    if (got.status !== 200) throw new TransportError(`poll: ${detail(got)}`);
    const task = json<Task & { kind?: string }>(got);
    // a server from before Phase 17 sends builds without `kind`
    return { ...task, kind: task.kind === "write" ? "write" : "build" } as Task;
  }

  async heartbeat(): Promise<void> {
    await this.call("POST", "/heartbeat");
  }

  async snapshot(id: string): Promise<Buffer> {
    const got = await this.call("GET", `/tasks/${encodeURIComponent(id)}/snapshot`, undefined, 10 * 60_000);
    if (got.status !== 200) throw new Error(`snapshot: ${detail(got)}`);
    return got.body;
  }

  async result(id: string, body: { exit_code: number; output: string; seconds: number }): Promise<number> {
    return (await this.call("POST", `/tasks/${encodeURIComponent(id)}/result`, body)).status;
  }

  /** 409 means the call was taken back: stop and drop the answer. */
  async progress(id: string, text: string): Promise<number> {
    return (await this.call("POST", `/calls/${encodeURIComponent(id)}/progress`, { text })).status;
  }

  async answer(id: string, body: { text: string; model?: string | null; input_tokens?: number | null; output_tokens?: number | null; seconds: number }): Promise<number> {
    return (await this.call("POST", `/calls/${encodeURIComponent(id)}/answer`, body, 120_000)).status;
  }

  async fail(id: string, body: { message: string; kind: "rejected" | "error" | "timeout" }): Promise<number> {
    return (await this.call("POST", `/calls/${encodeURIComponent(id)}/fail`, body)).status;
  }
}
