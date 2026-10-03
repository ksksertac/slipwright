// What the program writes for itself beside settings.json: the pairing. Kept apart from
// settings.json on purpose -- that file is a person's, edited and uploaded again and
// again over SFTP; the token in here is the machine's whole identity, made once, and an
// upload of a fresh settings.json must never take it away.

import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { Pairing } from "@shared/types";

export interface PairingState {
  pairing: Pairing;
  token: string;
  /** Through the relay only: this machine's secret key and the server's public key. */
  relayClientSk: string | null;
  serverPk: string | null;
}

export function readState(path: string): PairingState | null {
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as PairingState;
    return raw && typeof raw.token === "string" && raw.pairing ? raw : null;
  } catch {
    return null;
  }
}

/** Readable by this user alone, and never half-written: a crash leaves the old file. */
export function writeState(path: string, state: PairingState): void {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.tmp`;
  writeFileSync(temp, JSON.stringify(state, null, 2), { mode: 0o600 });
  renameSync(temp, path);
  try {
    chmodSync(path, 0o600);
  } catch {
    // Windows: the folder's own permissions are the protection
  }
}

export function forgetState(path: string): void {
  if (existsSync(path)) rmSync(path, { force: true });
}
