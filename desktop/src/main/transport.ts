// How a worker call reaches the server: one interface, two ways.
//
// On a LAN it is plain HTTP to the address the code carried (or found nearby). Anywhere
// else it goes through the relay: a WebSocket to the server's room, every request sealed
// to the server's key and every answer sealed back (docs/machines-protocol.md §3). The
// worker loop above neither knows nor cares which -- that is the point of the interface.

import { randomBytes } from "node:crypto";
import WebSocket from "ws";
import * as box from "./crypto";
import { Joiner, split, type Part } from "./parts";

export interface Reply {
  status: number;
  headers: Record<string, string>;
  body: Buffer;
}

export interface RequestOptions {
  token?: string | null;
  timeoutMs?: number;
}

export interface Transport {
  request(method: string, path: string, body?: unknown, options?: RequestOptions): Promise<Reply>;
  close(): void;
  /** For the connection card: "192.168.1.20:8000", "relay.slipwright.app". */
  readonly where: string;
  readonly via: "lan" | "relay";
}

/** The network did not carry the request at all -- as opposed to the server refusing it. */
export class TransportError extends Error {}

export function json<T = unknown>(reply: Reply): T {
  return JSON.parse(reply.body.toString("utf8")) as T;
}

/** What the server said went wrong, the way it says it (FastAPI's `detail`). */
export function detail(reply: Reply): string {
  try {
    const parsed = json<{ detail?: unknown }>(reply);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // not JSON: the text itself is the best there is
  }
  return reply.body.toString("utf8").slice(0, 300) || `HTTP ${reply.status}`;
}

function encode(body: unknown): { bytes: Buffer | null; type: string | null } {
  if (body === undefined || body === null) return { bytes: null, type: null };
  return { bytes: Buffer.from(JSON.stringify(body), "utf8"), type: "application/json" };
}

// -- direct -----------------------------------------------------------------------------

export class DirectTransport implements Transport {
  readonly via = "lan" as const;
  readonly where: string;

  constructor(private readonly address: string) {
    this.address = address.replace(/\/+$/, "");
    this.where = this.address.replace(/^https?:\/\//, "");
  }

  async request(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<Reply> {
    const { bytes, type } = encode(body);
    const headers: Record<string, string> = {};
    if (type) headers["content-type"] = type;
    if (options.token) headers.authorization = `Bearer ${options.token}`;
    let response: Response;
    try {
      response = await fetch(this.address + path, {
        method,
        headers,
        body: bytes ?? undefined,
        signal: AbortSignal.timeout(options.timeoutMs ?? 60_000),
      });
    } catch (error) {
      throw new TransportError(`cannot reach ${this.where}: ${(error as Error).message}`);
    }
    const out: Record<string, string> = {};
    response.headers.forEach((value, key) => (out[key] = value));
    return { status: response.status, headers: out, body: Buffer.from(await response.arrayBuffer()) };
  }

  close(): void {}
}

// -- the relay --------------------------------------------------------------------------

export interface RelayKeys {
  /** This machine's X25519 key pair, made at pairing and kept with the token. */
  client: box.KeyPair;
  /** The server's public key, proved at pairing by the welcome's MAC. */
  server: Buffer | null;
}

interface Waiter {
  resolve: (message: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  match: (message: Record<string, unknown>) => boolean;
  timer: NodeJS.Timeout;
}

/** A guest may send 120 frames a minute; the relay answers `slow-down` past that. Staying
 *  under it here is cheaper than being told. */
const FRAMES_PER_MINUTE = 110;

export class RelayTransport implements Transport {
  readonly via = "relay" as const;
  readonly where: string;
  private socket: WebSocket | null = null;
  private opening: Promise<WebSocket> | null = null;
  private joiner = new Joiner();
  private waiters = new Set<Waiter>();
  private sent: number[] = [];
  private key: Buffer | null = null;

  constructor(
    private readonly host: string,
    private readonly room: string,
    private readonly keys: RelayKeys,
    /** Injectable so the tests can run the whole exchange against an in-memory host. */
    private readonly connect: (url: string) => WebSocket = (url) => new WebSocket(url, { maxPayload: 2 * 1024 * 1024 }),
  ) {
    this.where = host;
  }

  get url(): string {
    const peer = this.keys.client.public.subarray(0, 16).toString("hex");
    return `wss://${this.host}/v1/rooms/${this.room}/guest?peer=${peer}`;
  }

  /** Pairing (§3 "Pairing through the relay"): hello, check the welcome's MAC, and only
   *  then trust the key it carries. Returns the server's public key. */
  async handshake(secret: Buffer, timeoutMs = 20_000): Promise<Buffer> {
    const waiting = this.wait((m) => m.k === "welcome", timeoutMs);
    try {
      await this.send({ k: "hello", pk: this.keys.client.public.toString("base64"), code_id: box.codeId(secret) });
    } catch (error) {
      waiting.catch(() => undefined);
      throw error;
    }
    const welcome = await waiting.catch((error: Error) => {
      // a code the host does not know gets no answer at all, by design
      throw error instanceof TransportError && /timed out/.test(error.message)
        ? new TransportError("the server did not answer this code: it was used, or ran out (15 minutes)")
        : error;
    });
    const serverPk = Buffer.from(String(welcome.pk ?? ""), "base64");
    const mac = Buffer.from(String(welcome.mac ?? ""), "base64");
    if (serverPk.length !== 32 || !box.checkWelcome(secret, serverPk, this.keys.client.public, mac)) {
      throw new TransportError("the relay handed over a key the code does not vouch for; not trusting it");
    }
    this.keys.server = serverPk;
    this.key = null;
    return serverPk;
  }

  async request(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<Reply> {
    const server = this.keys.server;
    if (!server) throw new TransportError("no server key: pair through the relay first");
    this.key ??= box.boxKey(this.keys.client.secret, server, this.keys.client.public, server);
    const { bytes, type } = encode(body);
    const headers: Record<string, string> = {};
    if (type) headers["content-type"] = type;
    if (options.token) headers.authorization = `Bearer ${options.token}`;
    const id = randomBytes(8).toString("hex");
    const inner = {
      id,
      ts: Math.floor(Date.now() / 1000),
      method,
      path,
      headers,
      body: bytes ? bytes.toString("base64") : "",
    };
    const n = box.nonce();
    const c = box.seal(this.key, n, Buffer.from(JSON.stringify(inner)), "c2s");
    const key = this.key;
    const answered = this.wait((m) => {
      if (m.k !== "box" || m.pk !== server.toString("base64")) return false;
      try {
        const opened = JSON.parse(box.open(key, Buffer.from(String(m.n), "base64"), Buffer.from(String(m.c), "base64"), "s2c").toString("utf8"));
        if (opened.id !== id) return false;
        m.opened = opened;
        return true;
      } catch {
        return false; // not for us, or tampered with: either way not the answer
      }
    }, options.timeoutMs ?? 60_000);
    try {
      await this.send({ k: "box", pk: this.keys.client.public.toString("base64"), n: n.toString("base64"), c: c.toString("base64") });
    } catch (error) {
      answered.catch(() => undefined); // its own rejection is this one; nobody else awaits it
      throw error;
    }
    const message = await answered;
    const opened = message.opened as { status: number; headers?: Record<string, string>; body?: string };
    return {
      status: Number(opened.status),
      headers: opened.headers ?? {},
      body: Buffer.from(opened.body ?? "", "base64"),
    };
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
    this.fail(new TransportError("closed"));
  }

  // -- the socket -----------------------------------------------------------------------

  private async open(): Promise<WebSocket> {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return this.socket;
    this.opening ??= new Promise<WebSocket>((resolve, reject) => {
      const socket = this.connect(this.url);
      const done = (error?: Error) => {
        this.opening = null;
        if (error) reject(error);
        else resolve(socket);
      };
      socket.once("open", () => {
        this.socket = socket;
        done();
      });
      socket.once("error", (error) => done(new TransportError(`relay: ${error.message}`)));
      socket.on("message", (data) => this.receive(data.toString()));
      socket.on("close", (code) => {
        if (this.socket === socket) this.socket = null;
        // 4004: the room has no host -- the server is off, or not reaching the relay
        const why = code === 4004 ? "the server is not connected to the relay" : `relay closed (${code})`;
        this.fail(new TransportError(why));
        done(new TransportError(why));
      });
    });
    return this.opening;
  }

  private async send(message: Record<string, unknown>): Promise<void> {
    const socket = await this.open();
    for (const part of split(Buffer.from(JSON.stringify(message), "utf8"))) {
      await this.throttle();
      socket.send(JSON.stringify({ to: "host", ...part }));
    }
  }

  private async throttle(): Promise<void> {
    const now = Date.now();
    this.sent = this.sent.filter((t) => now - t < 60_000);
    if (this.sent.length >= FRAMES_PER_MINUTE) {
      await new Promise((r) => setTimeout(r, 60_000 - (now - this.sent[0]!) + 50));
    }
    this.sent.push(Date.now());
  }

  private receive(text: string): void {
    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(text);
    } catch {
      return;
    }
    if (typeof frame.error === "string") {
      if (frame.error === "host-offline") this.fail(new TransportError("the server is not connected to the relay"));
      return; // too-large / slow-down concern one message; its waiter times out
    }
    if (frame.from !== "host") return;
    let whole: Buffer | null;
    try {
      whole = this.joiner.add(frame as unknown as Part);
    } catch {
      return;
    }
    if (!whole) return;
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(whole.toString("utf8"));
    } catch {
      return;
    }
    for (const waiter of this.waiters) {
      if (waiter.match(message)) {
        this.waiters.delete(waiter);
        clearTimeout(waiter.timer);
        waiter.resolve(message);
        return;
      }
    }
  }

  private wait(match: Waiter["match"], timeoutMs: number): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      const waiter: Waiter = {
        resolve,
        reject,
        match,
        timer: setTimeout(() => {
          this.waiters.delete(waiter);
          reject(new TransportError("the relay request timed out"));
        }, timeoutMs),
      };
      this.waiters.add(waiter);
    });
  }

  private fail(error: Error): void {
    for (const waiter of this.waiters) {
      clearTimeout(waiter.timer);
      waiter.reject(error);
    }
    this.waiters.clear();
  }
}
