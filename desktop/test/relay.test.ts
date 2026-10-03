// A whole pairing and a poll through a relay, against an in-memory host that does what
// docs/machines-protocol.md §3 says the server does. The relay here is a plain local
// WebSocket server standing in for both the relay and the installation behind it.

import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import WebSocket, { WebSocketServer } from "ws";
import { pair, WorkerClient } from "../src/main/client";
import { pack } from "../src/main/code";
import * as box from "../src/main/crypto";
import { Joiner, split } from "../src/main/parts";
import { RelayTransport } from "../src/main/transport";

const SECRET = Buffer.from("0123456789");
const ROOM = "00112233445566778899aabbccddeeff";

interface Host {
  port: number;
  seen: { path: string; auth: string | undefined; ts: number }[];
  close(): void;
}

function startHost(opts: { lie?: boolean } = {}): Promise<Host> {
  const server = box.newKeyPair();
  const seen: Host["seen"] = [];
  const wss = new WebSocketServer({ port: 0 });
  wss.on("connection", (socket, request) => {
    const url = new URL(request.url ?? "", "http://x");
    expect(url.pathname).toBe(`/v1/rooms/${ROOM}/guest`);
    const peer = url.searchParams.get("peer");
    const joiner = new Joiner();
    const send = (message: object) => {
      for (const part of split(Buffer.from(JSON.stringify(message)))) socket.send(JSON.stringify({ from: "host", ...part }));
    };
    socket.on("message", (data) => {
      const frame = JSON.parse(data.toString());
      expect(frame.to).toBe("host");
      const whole = joiner.add(frame);
      if (!whole) return;
      const m = JSON.parse(whole.toString());
      const clientPk = Buffer.from(m.pk, "base64");
      expect(clientPk.subarray(0, 16).toString("hex")).toBe(peer);
      if (m.k === "hello") {
        expect(m.code_id).toBe(box.codeId(SECRET));
        const pk = opts.lie ? box.newKeyPair().public : server.public;
        send({ k: "welcome", pk: pk.toString("base64"), mac: box.welcomeMac(SECRET, server.public, clientPk).toString("base64") });
        return;
      }
      const key = box.boxKey(server.secret, clientPk, clientPk, server.public);
      const request = JSON.parse(box.open(key, Buffer.from(m.n, "base64"), Buffer.from(m.c, "base64"), "c2s").toString());
      seen.push({ path: request.path, auth: request.headers.authorization, ts: request.ts });
      let status = 404;
      let body = "";
      if (request.path === "/api/worker/pair") {
        const sent = JSON.parse(Buffer.from(request.body, "base64").toString());
        status = sent.name === "laptop" ? 200 : 400;
        body = JSON.stringify({ worker_id: "w1", token: "swk_test" });
      } else if (request.path === "/api/worker/poll") {
        status = 200;
        body = JSON.stringify({ kind: "write", id: "c1", job_id: "j1", system: "s", prompt: "p", domain: "web" });
      }
      const answer = { id: request.id, status, headers: { "content-type": "application/json" }, body: Buffer.from(body).toString("base64") };
      const n = box.nonce();
      send({ k: "box", pk: server.public.toString("base64"), n: n.toString("base64"), c: box.seal(key, n, Buffer.from(JSON.stringify(answer)), "s2c").toString("base64") });
    });
  });
  return new Promise((resolve) =>
    wss.once("listening", () => resolve({ port: (wss.address() as AddressInfo).port, seen, close: () => wss.close() })),
  );
}

let host: Host | null = null;
afterEach(() => host?.close());

const through = (port: number) => (url: string) => new WebSocket(url.replace("wss://relay.test", `ws://127.0.0.1:${port}`));

describe("through the relay", () => {
  it("a machine pairs, keeps the server's key, and polls in sealed boxes", async () => {
    host = await startHost();
    const code = pack({ kind: "relay", host: "relay.test", room: ROOM }, SECRET);
    const paired = await pair(code, { name: "laptop", capabilities: ["write:web"], connectRelay: through(host.port) });
    expect(paired).toMatchObject({ workerId: "w1", token: "swk_test", address: null, relay: { host: "relay.test", room: ROOM } });
    expect(paired.serverPk).toHaveLength(32);

    const transport = new RelayTransport("relay.test", ROOM, { client: { secret: paired.clientSk!, public: box.publicFromSecret(paired.clientSk!) }, server: paired.serverPk }, through(host.port));
    const task = await new WorkerClient(transport, paired.token).poll(["write:web"], "laptop", 1);
    transport.close();
    expect(task).toMatchObject({ kind: "write", id: "c1", domain: "web" });
    expect(host.seen.map((s) => s.path)).toEqual(["/api/worker/pair", "/api/worker/poll"]);
    expect(host.seen[1]!.auth).toBe("Bearer swk_test");
    expect(Math.abs(host.seen[1]!.ts - Date.now() / 1000)).toBeLessThan(5);
  });

  it("a key the code does not vouch for is never trusted", async () => {
    host = await startHost({ lie: true });
    const code = pack({ kind: "relay", host: "relay.test", room: ROOM }, SECRET);
    await expect(pair(code, { name: "laptop", capabilities: [], connectRelay: through(host.port) })).rejects.toThrow(/does not vouch/);
    expect(host.seen).toEqual([]);
  });
});

describe("on a LAN", () => {
  let server: Server | null = null;
  afterEach(() => server?.close());

  it("a code made at localhost finds the server on its port, nearby", async () => {
    const asked: string[] = [];
    server = createServer((req, res) => {
      asked.push(req.url ?? "");
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ worker_id: "w2", token: "swk_lan" }));
    });
    await new Promise<void>((r) => server!.listen(0, "127.0.0.1", r));
    const port = (server.address() as AddressInfo).port;
    // kind 4 carries only the port: tried at localhost first
    const code = pack({ kind: "url", url: `http://localhost:${port}`, nearby: true }, SECRET);
    const paired = await pair(code, { name: "pc", capabilities: [], lookAround: async () => [] });
    expect(paired).toMatchObject({ workerId: "w2", token: "swk_lan", address: `http://localhost:${port}`, relay: null });
    expect(asked).toEqual(["/api/worker/pair"]);
  });
});
