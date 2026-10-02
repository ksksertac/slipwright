// What the relay does to a frame, kept apart from the sockets so it can be read -- and
// tested -- as plain functions. The rule is docs/machines-protocol.md §3: the relay adds
// `from`, removes `to`, and touches nothing else. Everything a peer says to another is
// sealed end to end before it gets here, so there is nothing else worth touching.

export const ROOM = /^[0-9a-f]{32}$/;
export const PEER = /^[0-9a-f]{32}$/;
export const TOKEN = /^[0-9a-f]{64}$/;

// One part of a message carries at most 512 KiB of data, which is ~683 KiB once base64'd;
// a mebibyte leaves room for the envelope and refuses anything that is not a part.
export const MAX_FRAME_BYTES = 1024 * 1024;

export const GUEST_FRAMES_PER_MINUTE = 120;
export const WINDOW_MS = 60_000;

export type RelayError = "host-offline" | "no-such-peer" | "too-large" | "slow-down" | "bad-frame";

export const errorFrame = (error: RelayError): string => JSON.stringify({ error });

/** Who sent a frame: the host, or the guest with this peer id. */
export type Sender = { role: "host" } | { role: "guest"; peer: string };

export type Routed = { to: "host" | string; frame: string } | { error: RelayError };

const encoder = new TextEncoder();

/** The size the limit is about: bytes on the wire, not UTF-16 code units. */
export function frameBytes(text: string): number {
  // A string can never be more than three bytes per code unit, nor fewer than one, so most
  // frames are decided without encoding them at all.
  if (text.length > MAX_FRAME_BYTES) return text.length;
  if (text.length * 3 <= MAX_FRAME_BYTES) return text.length;
  return encoder.encode(text).byteLength;
}

/**
 * Where a frame goes and what arrives there, or the error its sender is told.
 *
 * A guest may speak only to the host; the host only to a peer. Neither can pretend to be
 * the other: whatever `from` a sender wrote is dropped and the relay's own put in its
 * place, since `from` is the one thing a receiver takes the relay's word for.
 */
export function route(text: string, sender: Sender): Routed {
  if (frameBytes(text) > MAX_FRAME_BYTES) return { error: "too-large" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { error: "bad-frame" };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { error: "bad-frame" };
  }

  const { to, from: _claimed, ...rest } = parsed as Record<string, unknown>;
  if (typeof to !== "string") return { error: "bad-frame" };

  if (sender.role === "guest") {
    if (to !== "host") return { error: "bad-frame" };
    return { to: "host", frame: JSON.stringify({ from: sender.peer, ...rest }) };
  }
  if (!PEER.test(to)) return { error: "bad-frame" };
  return { to, frame: JSON.stringify({ from: "host", ...rest }) };
}

/** A fixed window of frames: small enough to live in a socket's attachment. */
export type Window = { start: number; count: number };

/**
 * Counts one frame against a guest's minute, returning the window to keep and whether the
 * frame may pass. A fixed window lets a burst of twice the rate straddle a boundary; for a
 * limit meant to stop a runaway loop rather than meter anybody, that is fine.
 */
export function spend(window: Window | undefined, now: number): { window: Window; ok: boolean } {
  if (!window || now - window.start >= WINDOW_MS) {
    return { window: { start: now, count: 1 }, ok: true };
  }
  const next = { start: window.start, count: window.count + 1 };
  return { window: next, ok: next.count <= GUEST_FRAMES_PER_MINUTE };
}
