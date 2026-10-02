import { env, runDurableObjectAlarm, runInDurableObject, SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { GUEST_FRAMES_PER_MINUTE, MAX_FRAME_BYTES, route } from "../src/frames";

const hex = (bytes: number) =>
  [...crypto.getRandomValues(new Uint8Array(bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");

type Socket = {
  ws: WebSocket;
  next: () => Promise<Record<string, unknown>>;
  closed: Promise<number>;
  send: (frame: unknown) => void;
};

/** Opens a socket through the Worker, exactly as a client on the internet would. */
async function connect(path: string): Promise<Socket> {
  const response = await SELF.fetch(`https://relay.test${path}`, { headers: { Upgrade: "websocket" } });
  expect(response.status).toBe(101);
  const ws = response.webSocket!;
  const inbox: Record<string, unknown>[] = [];
  const waiting: ((frame: Record<string, unknown>) => void)[] = [];
  let onClose: (code: number) => void = () => {};
  const closed = new Promise<number>((resolve) => (onClose = resolve));
  ws.addEventListener("message", (event) => {
    const frame = JSON.parse(event.data as string) as Record<string, unknown>;
    const taker = waiting.shift();
    if (taker) taker(frame);
    else inbox.push(frame);
  });
  ws.addEventListener("close", (event) => onClose(event.code));
  ws.accept();
  return {
    ws,
    closed,
    send: (frame) => ws.send(typeof frame === "string" ? frame : JSON.stringify(frame)),
    next: () => {
      const ready = inbox.shift();
      if (ready) return Promise.resolve(ready);
      return new Promise((resolve) => waiting.push(resolve));
    },
  };
}

function room() {
  const id = hex(16);
  const token = hex(32);
  return {
    id,
    token,
    host: (t = token) => connect(`/v1/rooms/${id}/host?token=${t}`),
    guest: (peer: string) => connect(`/v1/rooms/${id}/guest?peer=${peer}`),
  };
}

describe("the doors", () => {
  it("says what it is at the root", async () => {
    const response = await SELF.fetch("https://relay.test/");
    expect(await response.json()).toMatchObject({ service: "slipwright-relay" });
    expect((await SELF.fetch("https://relay.test/healthz")).status).toBe(200);
  });

  it("refuses an address that is not a room, a token or a peer", async () => {
    const upgrade = { headers: { Upgrade: "websocket" } };
    for (const path of [
      `/v1/rooms/not-a-room/host?token=${hex(32)}`,
      `/v1/rooms/${hex(16)}/host?token=short`,
      `/v1/rooms/${hex(16)}/host`,
      `/v1/rooms/${hex(16)}/guest?peer=${hex(15)}`,
    ]) {
      expect((await SELF.fetch(`https://relay.test${path}`, upgrade)).status).toBe(400);
    }
  });
});

describe("a room", () => {
  it("is claimed by the first host and refused to a host with another token", async () => {
    const r = room();
    const first = await r.host();
    const stranger = await r.host(hex(32));
    expect(await stranger.closed).toBe(4003);
    // The rightful host was not disturbed by the attempt.
    expect(first.ws.readyState).toBe(WebSocket.OPEN);
  });

  it("keeps only a digest of the host's token", async () => {
    const r = room();
    await r.host();
    const stub = env.ROOMS.get(env.ROOMS.idFromName(r.id));
    const kept = await runInDurableObject(stub, (_, state) => state.storage.get<string>("host"));
    expect(kept).toMatch(/^[0-9a-f]{64}$/);
    expect(kept).not.toBe(r.token);
  });

  it("hands the room to a newer host with the right token", async () => {
    const r = room();
    const old = await r.host();
    const fresh = await r.host();
    expect(await old.closed).toBe(4000);
    const peer = hex(16);
    const guest = await r.guest(peer);
    guest.send({ to: "host", n: 1 });
    expect(await fresh.next()).toEqual({ from: peer, n: 1 });
  });

  it("turns a guest away while nobody hosts it", async () => {
    const r = room();
    const guest = await r.guest(hex(16));
    expect(await guest.closed).toBe(4004);
  });

  it("is forgotten after thirty days without a host", async () => {
    const r = room();
    const host = await r.host();
    host.ws.close(1000);
    const stub = env.ROOMS.get(env.ROOMS.idFromName(r.id));
    await runInDurableObject(stub, async (_, state) => {
      // Wait for the close to reach the object before pretending a month went by.
      while (state.getWebSockets("host").some((ws) => ws.readyState === WebSocket.OPEN)) {
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      await state.storage.put("seen", Date.now() - 31 * 24 * 60 * 60 * 1000);
    });
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await runInDurableObject(stub, (_, state) => state.storage.get("host"))).toBeUndefined();
    // Anybody may claim it again: it is a new room.
    const newcomer = await r.host(hex(32));
    expect(newcomer.ws.readyState).toBe(WebSocket.OPEN);
  });
});

describe("frames", () => {
  it("reach the host from a guest, signed with the guest's peer", async () => {
    const r = room();
    const host = await r.host();
    const peer = hex(16);
    const guest = await r.guest(peer);
    guest.send({ to: "host", mid: "a1", part: 0, parts: 1, data: "c2VhbGVk" });
    expect(await host.next()).toEqual({ from: peer, mid: "a1", part: 0, parts: 1, data: "c2VhbGVk" });
  });

  it("reach a guest from the host, signed by the host", async () => {
    const r = room();
    const host = await r.host();
    const peer = hex(16);
    const guest = await r.guest(peer);
    host.send({ to: peer, mid: "b2", data: "YW5zd2Vy" });
    expect(await guest.next()).toEqual({ from: "host", mid: "b2", data: "YW5zd2Vy" });
  });

  it("cannot be passed off as another peer's", async () => {
    const r = room();
    const host = await r.host();
    const peer = hex(16);
    const guest = await r.guest(peer);
    guest.send({ to: "host", from: "host", data: "x" });
    expect(await host.next()).toEqual({ from: peer, data: "x" });
  });

  it("to a peer that is not there come back as no-such-peer", async () => {
    const r = room();
    const host = await r.host();
    host.send({ to: hex(16), data: "x" });
    expect(await host.next()).toEqual({ error: "no-such-peer" });
  });

  it("to a host that has gone come back as host-offline", async () => {
    const r = room();
    const host = await r.host();
    const guest = await r.guest(hex(16));
    host.ws.close(1000);
    await host.closed;
    guest.send({ to: "host", data: "x" });
    expect(await guest.next()).toEqual({ error: "host-offline" });
  });

  it("over a mebibyte are refused as too-large", async () => {
    const r = room();
    const host = await r.host();
    const guest = await r.guest(hex(16));
    guest.send({ to: "host", data: "x".repeat(MAX_FRAME_BYTES) });
    expect(await guest.next()).toEqual({ error: "too-large" });
    // The next, smaller one still goes through.
    guest.send({ to: "host", data: "y" });
    expect(await host.next()).toMatchObject({ data: "y" });
  });

  it("that are not a JSON object addressed properly are bad frames", async () => {
    const r = room();
    const host = await r.host();
    const guest = await r.guest(hex(16));
    for (const frame of ["not json", "[1,2]", JSON.stringify({ data: "no to" }), JSON.stringify({ to: hex(16) })]) {
      guest.send(frame);
      expect(await guest.next()).toEqual({ error: "bad-frame" });
    }
    guest.ws.send(new Uint8Array([1, 2, 3]));
    expect(await guest.next()).toEqual({ error: "bad-frame" });
    host.send({ to: "host" });
    expect(await host.next()).toEqual({ error: "bad-frame" });
  });

  it("from a guest are limited to 120 a minute, and from the host are not", async () => {
    const r = room();
    const host = await r.host();
    const peer = hex(16);
    const guest = await r.guest(peer);
    for (let i = 0; i <= GUEST_FRAMES_PER_MINUTE; i++) guest.send({ to: "host", i });
    expect(await guest.next()).toEqual({ error: "slow-down" });
    for (let i = 0; i < GUEST_FRAMES_PER_MINUTE; i++) expect(await host.next()).toEqual({ from: peer, i });

    for (let i = 0; i < GUEST_FRAMES_PER_MINUTE * 2; i++) host.send({ to: peer, i });
    for (let i = 0; i < GUEST_FRAMES_PER_MINUTE * 2; i++) expect(await guest.next()).toEqual({ from: "host", i });
  });

  it("from a second guest with the same peer replace the first", async () => {
    const r = room();
    const host = await r.host();
    const peer = hex(16);
    const first = await r.guest(peer);
    const second = await r.guest(peer);
    expect(await first.closed).toBe(4000);
    host.send({ to: peer, data: "x" });
    expect(await second.next()).toEqual({ from: "host", data: "x" });
  });
});

describe("route", () => {
  it("measures the limit in bytes, not characters", () => {
    const wide = "é".repeat(MAX_FRAME_BYTES / 2); // two bytes each
    expect(route(JSON.stringify({ to: "host", d: wide }), { role: "guest", peer: hex(16) })).toEqual({
      error: "too-large",
    });
  });
});
