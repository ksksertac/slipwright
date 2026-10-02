// Finding a server on this network, as `worker_agent._candidates` does.
//
// A code made at `localhost` -- a local install, often in Docker, which cannot see its own
// network address -- carries only a port. So the code's address is tried first when it is
// one another machine could reach, then this machine itself, then every host of this
// machine's /24 that accepts a connection on that port. Only the server that made the
// code accepts it, so a wrong door costs a refusal and nothing else.

import { createSocket } from "node:dgram";
import { connect } from "node:net";
import { reachable } from "./code";

export async function* candidates(address: string, lookAround: (port: number) => Promise<string[]> = nearbyServers): AsyncGenerator<string> {
  const url = new URL(address);
  if (reachable(address)) yield address.replace(/\/+$/, "");
  if (url.protocol !== "http:") return; // a server behind https has a real name
  const port = Number(url.port || 80);
  yield `http://localhost:${port}`;
  // lazy: the network is only searched when nothing nearer answered
  for (const host of await lookAround(port)) yield `http://${host}:${port}`;
}

/** This machine's address on its network: the one a packet out would leave from. A UDP
 *  socket that is only connected sends nothing. */
export function ownAddress(): Promise<string | null> {
  return new Promise((resolve) => {
    const socket = createSocket("udp4");
    const finish = (value: string | null) => {
      try {
        socket.close();
      } catch {
        // already closed
      }
      resolve(value);
    };
    socket.once("error", () => finish(null));
    // TEST-NET: never routed anywhere real
    socket.connect(9, "192.0.2.1", () => {
      const me = socket.address().address;
      finish(me && !me.startsWith("127.") ? me : null);
    });
  });
}

export async function nearbyServers(port: number): Promise<string[]> {
  const me = await ownAddress();
  if (!me) return [];
  const base = me.split(".").slice(0, 3).join(".");
  const hosts: string[] = [];
  for (let i = 1; i < 255; i++) if (`${base}.${i}` !== me) hosts.push(`${base}.${i}`);
  // a probe is only a TCP connect, so the whole of a home network is looked at in a
  // second or two, 64 at a time
  const found: string[] = [];
  for (let i = 0; i < hosts.length; i += 64) {
    const batch = hosts.slice(i, i + 64);
    const answers = await Promise.all(batch.map((h) => probe(h, port)));
    batch.forEach((h, n) => answers[n] && found.push(h));
  }
  return found;
}

function probe(host: string, port: number, timeoutMs = 400): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = connect({ host, port });
    const done = (ok: boolean) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs, () => done(false));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}
