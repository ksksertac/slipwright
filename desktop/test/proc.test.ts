import { describe, expect, it } from "vitest";
import { run } from "../src/main/proc";

// a parent that starts a child and waits on it, as `codex` (a Node shim) starts its binary
const PARENT = `
const { spawn } = require("node:child_process");
const child = spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000)"], { stdio: "inherit" });
console.log("child " + child.pid);
setTimeout(() => {}, 60000);
`;

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

describe("a child process", () => {
  it("that runs past its time is ended with everything it started", async () => {
    const started = Date.now();
    let childPid = 0;
    const ran = await run(process.execPath, ["-e", PARENT], {
      timeoutMs: 1500,
      onStdout: (chunk) => {
        const m = /child (\d+)/.exec(chunk);
        if (m) childPid = Number(m[1]);
      },
    });
    expect(ran.timedOut).toBe(true);
    expect(Date.now() - started).toBeLessThan(10_000);
    expect(childPid).toBeGreaterThan(0);
    // taskkill /T and the process-group kill are not instant
    for (let i = 0; i < 50 && alive(childPid); i++) await new Promise((r) => setTimeout(r, 100));
    expect(alive(childPid)).toBe(false);
  });

  it("hears its prompt on stdin", async () => {
    const ran = await run(process.execPath, ["-e", "process.stdin.pipe(process.stdout)"], { stdin: "a long prompt" });
    expect(ran.stdout).toBe("a long prompt");
    expect(ran.code).toBe(0);
  });
});
