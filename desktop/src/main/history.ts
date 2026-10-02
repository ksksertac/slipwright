// The last 200 things this machine did, for the History page. Kept on the machine only:
// the server has the authoritative record; this is what a person asks "what did my
// laptop do last night" of.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { HistoryEntry } from "@shared/types";

export const KEEP = 200;

export class History {
  private entries: HistoryEntry[];

  constructor(private readonly path: string) {
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8"));
      this.entries = Array.isArray(parsed) ? parsed.slice(0, KEEP) : [];
    } catch {
      this.entries = [];
    }
  }

  list(): HistoryEntry[] {
    return this.entries;
  }

  add(entry: HistoryEntry): void {
    this.entries = [entry, ...this.entries].slice(0, KEEP);
    try {
      mkdirSync(dirname(this.path), { recursive: true });
      writeFileSync(this.path, JSON.stringify(this.entries, null, 1));
    } catch {
      // a full disk loses a history line, not the work
    }
  }
}
