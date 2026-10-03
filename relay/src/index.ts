// The Slipwright relay: a meeting point for an installation that cannot be reached (behind
// a NAT, on a laptop) and the machines paired to it. It is deliberately a dumb pipe. What
// passes through it is sealed end to end (docs/machines-protocol.md §3, "The box"), and the
// pairing proves the server's key with a MAC the relay cannot forge, so the relay is
// trusted with nothing but delivery -- and is written so that it could not do more if it
// wanted to: it reads `to`, writes `from`, and never logs a frame.

import { DurableObject } from "cloudflare:workers";
import { errorFrame, PEER, ROOM, route, spend, TOKEN, type RelayError, type Window } from "./frames";

export const VERSION = "1.0.0";

export interface Env {
  ROOMS: DurableObjectNamespace<Room>;
}

// Close codes a client can act on. 4003 and 4004 are the protocol's; the others say why a
// socket the client did nothing wrong on went away, so it knows whether to reconnect.
const REFUSED_TOKEN = 4003;
const NO_HOST = 4004;
const REPLACED = 4000;

// A room nobody hosts is forgotten after this long. An installation that comes back later
// simply claims it again with the token it kept; its guests' keys live with the guests and
// the server, never here, so nothing of value is lost.
const IDLE_MS = 30 * 24 * 60 * 60 * 1000;

type Attachment = { role: "host" } | { role: "guest"; peer: string; window?: Window };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return Response.json({ service: "slipwright-relay", version: VERSION });
    }
    if (request.method === "GET" && url.pathname === "/healthz") {
      return Response.json({ ok: true });
    }

    const match = /^\/v1\/rooms\/([^/]+)\/(host|guest)$/.exec(url.pathname);
    if (!match) return new Response("not found\n", { status: 404 });
    if (request.method !== "GET") return new Response("method not allowed\n", { status: 405 });

    // Ids are compared as text in storage and in socket tags, so one spelling of each: an
    // upper-case room would otherwise be a different room.
    const room = match[1]!.toLowerCase();
    const role = match[2] as "host" | "guest";
    if (!ROOM.test(room)) return new Response("bad room\n", { status: 400 });
    if (role === "host") {
      const token = (url.searchParams.get("token") ?? "").toLowerCase();
      if (!TOKEN.test(token)) return new Response("bad token\n", { status: 400 });
    } else {
      const peer = (url.searchParams.get("peer") ?? "").toLowerCase();
      if (!PEER.test(peer)) return new Response("bad peer\n", { status: 400 });
    }
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response("expected a websocket\n", { status: 426 });
    }

    // One object per room, so everything about a room -- who holds it, who is in it -- is
    // decided in one place, one event at a time.
    return env.ROOMS.get(env.ROOMS.idFromName(room)).fetch(request);
  },
} satisfies ExportedHandler<Env>;

/**
 * One installation's room. Sockets are accepted through the hibernation API, so a room
 * whose host and guests are connected but quiet -- most of them, most of the time -- costs
 * nothing while it waits; anything that must survive a hibernation is kept in a socket's
 * tags and attachment, or in storage, never in a field of this object.
 */
export class Room extends DurableObject<Env> {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.endsWith("/host")) {
      return this.host((url.searchParams.get("token") ?? "").toLowerCase());
    }
    return this.guest((url.searchParams.get("peer") ?? "").toLowerCase());
  }

  private async host(token: string): Promise<Response> {
    // Only a digest is kept, so storage read by anybody does not hand them the room.
    const digest = await sha256(token);
    const claimed = await this.ctx.storage.get<string>("host");
    if (claimed === undefined) {
      await this.ctx.storage.put("host", digest);
    } else if (claimed !== digest) {
      return refuse(REFUSED_TOKEN, "this room belongs to another installation");
    }

    // The right token again is the same installation reconnecting -- after a restart, or
    // across a network change before the old socket noticed it was dead. The newest wins.
    for (const old of this.open("host")) old.close(REPLACED, "replaced by a newer host connection");

    const [client, server] = pair();
    this.ctx.acceptWebSocket(server, ["host"]);
    server.serializeAttachment({ role: "host" } satisfies Attachment);
    await this.touch();
    return new Response(null, { status: 101, webSocket: client });
  }

  private async guest(peer: string): Promise<Response> {
    // A guest with nobody to talk to is turned away rather than left waiting: the room's id
    // is in every connection code, and a relay holding sockets open for rooms whose
    // installation is gone would be holding them for anybody who once saw one.
    if (this.open("host").length === 0) return refuse(NO_HOST, "the installation is not connected");

    // A peer id is half the guest's public key. The same one again is the same machine
    // reconnecting; anybody else claiming it gains nothing, as they cannot open a box.
    for (const old of this.open(`peer:${peer}`)) old.close(REPLACED, "replaced by a newer connection");

    const [client, server] = pair();
    this.ctx.acceptWebSocket(server, ["guest", `peer:${peer}`]);
    server.serializeAttachment({ role: "guest", peer } satisfies Attachment);
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    // Frames are JSON text by the protocol; a binary one is a client that is not ours.
    if (typeof message !== "string") return tell(ws, "bad-frame");

    const me = ws.deserializeAttachment() as Attachment;
    if (me.role === "guest") {
      const { window, ok } = spend(me.window, Date.now());
      ws.serializeAttachment({ ...me, window } satisfies Attachment);
      if (!ok) return tell(ws, "slow-down");
    }

    const routed = route(message, me.role === "host" ? { role: "host" } : { role: "guest", peer: me.peer });
    if ("error" in routed) return tell(ws, routed.error);

    const target = routed.to === "host" ? this.open("host")[0] : this.open(`peer:${routed.to}`)[0];
    if (!target) return tell(ws, routed.to === "host" ? "host-offline" : "no-such-peer");
    try {
      target.send(routed.frame);
    } catch {
      // Closed between the lookup and the send: the same as not being there.
      tell(ws, routed.to === "host" ? "host-offline" : "no-such-peer");
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    // Complete the closing handshake. 1005 and 1006 are reported, never sent.
    try {
      ws.close(code === 1005 || code === 1006 ? 1000 : code, reason);
    } catch {
      // Already closed from this side.
    }
    // A host leaving starts the room's idle clock. Its guests stay connected: the usual
    // reason is a server restarting, and they hear `host-offline` until it is back.
    if ((ws.deserializeAttachment() as Attachment | null)?.role === "host") await this.touch();
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    if ((ws.deserializeAttachment() as Attachment | null)?.role === "host") await this.touch();
  }

  async alarm(): Promise<void> {
    if (this.open("host").length > 0) {
      // Hosted all along: nothing to forget yet.
      await this.touch();
      return;
    }
    const seen = (await this.ctx.storage.get<number>("seen")) ?? 0;
    if (Date.now() - seen >= IDLE_MS) {
      await this.ctx.storage.deleteAlarm();
      await this.ctx.storage.deleteAll();
    } else {
      await this.ctx.storage.setAlarm(seen + IDLE_MS);
    }
  }

  /** Records that the room was hosted just now and pushes its forgetting back. */
  private async touch(): Promise<void> {
    const now = Date.now();
    await this.ctx.storage.put("seen", now);
    await this.ctx.storage.setAlarm(now + IDLE_MS);
  }

  /** Sockets with this tag that can still be sent to; a replaced one lingers while closing. */
  private open(tag: string): WebSocket[] {
    return this.ctx.getWebSockets(tag).filter((ws) => ws.readyState === WebSocket.OPEN);
  }
}

function pair(): [WebSocket, WebSocket] {
  const { 0: client, 1: server } = new WebSocketPair();
  return [client, server];
}

/**
 * Accepts and at once closes with a code. Answering the upgrade with a plain 403 would
 * reach a WebSocket client as nothing but "failed to connect"; a close code is something
 * it can act on -- 4003 means stop, 4004 means try later.
 */
function refuse(code: number, reason: string): Response {
  const [client, server] = pair();
  server.accept();
  server.close(code, reason);
  return new Response(null, { status: 101, webSocket: client });
}

function tell(ws: WebSocket, error: RelayError): void {
  try {
    ws.send(errorFrame(error));
  } catch {
    // The sender has gone too; there is nobody left to tell.
  }
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
