// A relay frame is at most 1 MiB, and a build's snapshot is far more. So every message
// between peers is cut into parts of 512 KiB of data (base64 of it stays well under the
// frame limit) and joined again on arrival (docs/machines-protocol.md §3).

import { randomBytes } from "node:crypto";

export const PART_BYTES = 512 * 1024;

export interface Part {
  mid: string;
  part: number;
  parts: number;
  data: string;
}

export function split(message: Uint8Array, mid: string = randomBytes(8).toString("hex")): Part[] {
  const parts = Math.max(1, Math.ceil(message.length / PART_BYTES));
  const out: Part[] = [];
  for (let i = 0; i < parts; i++) {
    const chunk = message.subarray(i * PART_BYTES, (i + 1) * PART_BYTES);
    out.push({ mid, part: i, parts, data: Buffer.from(chunk).toString("base64") });
  }
  return out;
}

/** Collects parts until a message is whole. A message that never completes is dropped
 *  after `ttlMs`, so a peer that went away mid-message does not hold memory forever. */
export class Joiner {
  private pending = new Map<string, { parts: (Buffer | undefined)[]; got: number; since: number }>();

  constructor(private ttlMs = 120_000) {}

  /** The whole message once its last part arrived; null until then. */
  add(part: Part, now = Date.now()): Buffer | null {
    this.expire(now);
    if (!isPart(part)) throw new Error("not a message part");
    if (part.parts === 1) return Buffer.from(part.data, "base64");
    let entry = this.pending.get(part.mid);
    if (!entry) {
      entry = { parts: new Array<Buffer | undefined>(part.parts), got: 0, since: now };
      this.pending.set(part.mid, entry);
    }
    if (entry.parts.length !== part.parts) throw new Error("parts of one message disagree on how many there are");
    if (entry.parts[part.part] === undefined) {
      entry.parts[part.part] = Buffer.from(part.data, "base64");
      entry.got += 1;
    }
    if (entry.got < part.parts) return null;
    this.pending.delete(part.mid);
    return Buffer.concat(entry.parts as Buffer[]);
  }

  private expire(now: number): void {
    for (const [mid, entry] of this.pending) {
      if (now - entry.since > this.ttlMs) this.pending.delete(mid);
    }
  }
}

export function isPart(value: unknown): value is Part {
  const p = value as Part;
  return (
    !!p &&
    typeof p.mid === "string" &&
    Number.isInteger(p.part) &&
    Number.isInteger(p.parts) &&
    p.parts >= 1 &&
    p.parts <= 4096 &&
    p.part >= 0 &&
    p.part < p.parts &&
    typeof p.data === "string"
  );
}
