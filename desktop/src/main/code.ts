// Connection codes, read exactly as `slipwright/workers.py` writes them: "SW-" and
// Crockford base32 of  version(1) ‖ address ‖ secret(10) ‖ crc8, where crc8 is the low
// byte of zlib's CRC-32. Ported byte for byte rather than redesigned: the server and the
// Python worker read the same codes, and a code that one accepts and the other refuses
// would be the worst kind of bug to explain to somebody holding a laptop.

import { crc32 } from "node:zlib";

const PREFIX = "SW";
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
// a code is sometimes read off one screen and typed on another
const LOOKALIKE: Record<string, string> = { O: "0", I: "1", L: "1" };
const VERSION = 1;
const SECRET_BYTES = 10;
const ROOM_BYTES = 16;

// how the address is packed; 5 is the relay (docs/machines-protocol.md §2)
export const Kind = { HttpV4: 1, HttpsV4: 2, Url: 3, Nearby: 4, Relay: 5 } as const;

export type Address =
  | { kind: "url"; url: string; nearby: boolean }
  | { kind: "relay"; host: string; room: string };

export interface Code {
  address: Address;
  secret: Buffer;
}

export class CodeError extends Error {}

export function crc8(data: Uint8Array): number {
  return crc32(data) & 0xff;
}

export function unpack(code: string): Code {
  let text = code.trim().toUpperCase().replace(/[-\s]/g, "");
  text = text.replace(/[OIL]/g, (c) => LOOKALIKE[c] ?? c);
  if (!text.startsWith(PREFIX)) {
    throw new CodeError("not a Slipwright connection code (they start with SW-)");
  }
  text = text.slice(PREFIX.length);
  let n = 0n;
  for (const char of text) {
    const digit = ALPHABET.indexOf(char);
    if (digit < 0) throw new CodeError(`a connection code has no '${char}' in it; check the copy`);
    n = n * 32n + BigInt(digit);
  }
  const payload = bigToBytes(n);
  if (payload.length < 2 + SECRET_BYTES + 1 || payload[0] !== VERSION) {
    throw new CodeError("this code is incomplete, or from another version of Slipwright");
  }
  const body = payload.subarray(0, payload.length - 1);
  if (crc8(body) !== payload[payload.length - 1]) {
    throw new CodeError("this code does not add up: a character is missing or wrong");
  }
  const secret = Buffer.from(body.subarray(body.length - SECRET_BYTES));
  return { address: unpackAddress(body.subarray(1, body.length - SECRET_BYTES)), secret };
}

function unpackAddress(packed: Buffer): Address {
  if (packed.length === 0) throw new CodeError("this code carries no address");
  const kind = packed[0];
  const rest = packed.subarray(1);
  if ((kind === Kind.HttpV4 || kind === Kind.HttpsV4) && rest.length === 6) {
    const scheme = kind === Kind.HttpV4 ? "http" : "https";
    const ip = Array.from(rest.subarray(0, 4)).join(".");
    return { kind: "url", url: `${scheme}://${ip}:${rest.readUInt16BE(4)}`, nearby: false };
  }
  if (kind === Kind.Url) {
    return { kind: "url", url: rest.toString("utf8"), nearby: false };
  }
  if (kind === Kind.Nearby && rest.length === 2) {
    return { kind: "url", url: `http://localhost:${rest.readUInt16BE(0)}`, nearby: true };
  }
  if (kind === Kind.Relay && rest.length >= 1) {
    const len = rest[0]!;
    if (rest.length === 1 + len + ROOM_BYTES) {
      return {
        kind: "relay",
        host: rest.subarray(1, 1 + len).toString("utf8"),
        room: rest.subarray(1 + len).toString("hex"),
      };
    }
  }
  throw new CodeError("this code's address cannot be read");
}

/** The other direction. The server makes the codes; this is here so the tests can make
 *  the kinds the server's Python does not yet write (the relay, kind 5). */
export function pack(address: Address, secret: Uint8Array): string {
  let packed: Buffer;
  if (address.kind === "relay") {
    const host = Buffer.from(address.host, "utf8");
    packed = Buffer.concat([Buffer.from([Kind.Relay, host.length]), host, Buffer.from(address.room, "hex")]);
  } else if (address.nearby) {
    const port = Buffer.alloc(2);
    port.writeUInt16BE(Number(new URL(address.url).port || 80));
    packed = Buffer.concat([Buffer.from([Kind.Nearby]), port]);
  } else {
    packed = Buffer.concat([Buffer.from([Kind.Url]), Buffer.from(address.url.replace(/\/+$/, ""), "utf8")]);
  }
  let payload = Buffer.concat([Buffer.from([VERSION]), packed, Buffer.from(secret)]);
  payload = Buffer.concat([payload, Buffer.from([crc8(payload)])]);
  let n = BigInt("0x" + payload.toString("hex"));
  let text = "";
  while (n > 0n) {
    text = ALPHABET[Number(n % 32n)] + text;
    n /= 32n;
  }
  return `${PREFIX}-` + (text.match(/.{1,4}/g) ?? []).join("-");
}

function bigToBytes(n: bigint): Buffer {
  let hex = n.toString(16);
  if (hex.length % 2) hex = "0" + hex;
  return Buffer.from(hex, "hex");
}

/** Whether another machine could call this address: not loopback, and http(s). */
export function reachable(address: string): boolean {
  let url: URL;
  try {
    url = new URL(address.trim());
  } catch {
    return false;
  }
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (!["http:", "https:"].includes(url.protocol) || !host) return false;
  if (host === "localhost" || host.endsWith(".localhost")) return false;
  if (/^127\./.test(host) || host === "::1") return false;
  return true;
}
