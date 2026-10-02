// A live check of a deployed relay: a host and a guest in a fresh room, one frame each way.
//
//   node scripts/smoke.mjs https://slipwright-relay.<account>.workers.dev
//
// Uses Node 22's own WebSocket, so it needs nothing installed.

import { randomBytes } from "node:crypto";

const base = (process.argv[2] ?? "https://relay.slipwright.app").replace(/^http/, "ws").replace(/\/$/, "");
const room = randomBytes(16).toString("hex");
const token = randomBytes(32).toString("hex");
const peer = randomBytes(16).toString("hex");

function open(path) {
  const ws = new WebSocket(`${base}${path}`);
  const inbox = [];
  const waiting = [];
  ws.addEventListener("message", (event) => {
    const frame = JSON.parse(event.data);
    const taker = waiting.shift();
    taker ? taker(frame) : inbox.push(frame);
  });
  const closed = new Promise((resolve) => ws.addEventListener("close", (event) => resolve(event.code)));
  const opened = new Promise((resolve, reject) => {
    ws.addEventListener("open", () => resolve(), { once: true });
    ws.addEventListener("error", () => reject(new Error(`could not open ${path}`)), { once: true });
  });
  const next = () =>
    inbox.length
      ? Promise.resolve(inbox.shift())
      : new Promise((resolve, reject) => {
          waiting.push(resolve);
          setTimeout(() => reject(new Error("no frame within 10s")), 10_000);
        });
  return { ws, opened, closed, next, send: (frame) => ws.send(JSON.stringify(frame)) };
}

function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${JSON.stringify(actual)}`);
  if (!ok) process.exitCode = 1;
}

const info = await fetch(base.replace(/^ws/, "http") + "/").then((r) => r.json());
check("GET /", info.service, "slipwright-relay");

const host = open(`/v1/rooms/${room}/host?token=${token}`);
await host.opened;

const guest = open(`/v1/rooms/${room}/guest?peer=${peer}`);
await guest.opened;

guest.send({ to: "host", mid: "0123456789abcdef", part: 0, parts: 1, data: "aGVsbG8=" });
check("guest -> host", await host.next(), { from: peer, mid: "0123456789abcdef", part: 0, parts: 1, data: "aGVsbG8=" });

host.send({ to: peer, mid: "fedcba9876543210", part: 0, parts: 1, data: "d2VsY29tZQ==" });
check("host -> guest", await guest.next(), { from: "host", mid: "fedcba9876543210", part: 0, parts: 1, data: "d2VsY29tZQ==" });

host.send({ to: randomBytes(16).toString("hex"), data: "x" });
check("host -> nobody", await host.next(), { error: "no-such-peer" });

const stranger = open(`/v1/rooms/${room}/host?token=${randomBytes(32).toString("hex")}`);
check("another token", await stranger.closed, 4003);

const lonely = open(`/v1/rooms/${randomBytes(16).toString("hex")}/guest?peer=${peer}`);
check("guest without a host", await lonely.closed, 4004);

guest.ws.close(1000);
host.ws.close(1000);
