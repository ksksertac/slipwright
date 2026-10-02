// Codex, as `slipwright/providers/codex.py` drives it -- with two differences that follow
// from where it runs. The server keeps a private CODEX_HOME per account; here it is the
// person's own `codex`, signed in as them, so their home is used as it is. And the server
// runs it in an empty directory; here it runs in the call's checkout when there is one,
// still in the read-only sandbox, so it can read the code it is writing against.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { run, which } from "../proc";
import { Cancelled, cliEnv, imageLabels, ModelFailure, preamble, REFUSED, type ModelAnswer, type ModelCall } from "./types";

const EFFORT: Record<string, string> = { low: "low", medium: "medium", high: "high", max: "high" };

export interface CodexResult {
  text: string;
  inputTokens: number | null;
  outputTokens: number | null;
  error: string | null;
}

/** (answer, tokens, error) out of `codex exec --json`: the last agent message is the
 *  answer, `turn.completed` carries the usage. */
export function parseCodexOutput(stdout: string): CodexResult {
  const out: CodexResult = { text: "", inputTokens: null, outputTokens: null, error: null };
  for (const event of codexEvents(stdout)) {
    const kind = String(event.type ?? "");
    if (kind === "item.completed") {
      const item = (event.item ?? {}) as Record<string, unknown>;
      if ((item.type === "agent_message" || item.type === "assistant_message") && item.text) out.text = String(item.text);
    } else if (kind === "turn.completed") {
      const usage = (event.usage ?? {}) as Record<string, number | undefined>;
      if (usage.input_tokens != null) out.inputTokens = Number(usage.input_tokens);
      if (usage.output_tokens != null) out.outputTokens = Number(usage.output_tokens) + Number(usage.reasoning_output_tokens ?? 0);
    } else if (kind === "error" || kind === "turn.failed") {
      const nested = (event.error ?? {}) as Record<string, unknown>;
      out.error = String(event.message ?? nested.message ?? kind);
    }
  }
  return out;
}

export function codexEvents(stdout: string): Record<string, unknown>[] {
  const events: Record<string, unknown>[] = [];
  for (const raw of stdout.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line.startsWith("{")) continue;
    try {
      const event = JSON.parse(line);
      if (event && typeof event === "object") events.push(event);
    } catch {
      // a line that is not an event: the CLI's own chatter
    }
  }
  return events;
}

export function codexArgs(model: string, depth: string | null, images: string[]): string[] {
  const args = ["exec", "--json", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only"];
  if (model && model !== "default") args.push("-m", model);
  // unquoted on purpose: Codex reads a -c value as TOML and falls back to the bare string,
  // and a quote would have to survive cmd.exe on Windows
  const effort = depth ? EFFORT[depth] : undefined;
  if (effort) args.push("-c", `model_reasoning_effort=${effort}`);
  // one --image=a,b rather than --image a b: the flag takes several values and would
  // swallow the "-" that says the prompt is on stdin
  if (images.length) args.push(`--image=${images.join(",")}`);
  args.push("-");
  return args;
}

/** A line for the live log from one event, when it says something a person would want. */
function describe(event: Record<string, unknown>): string | null {
  if (event.type !== "item.started" && event.type !== "item.completed") return null;
  const item = (event.item ?? {}) as Record<string, unknown>;
  if (item.type === "command_execution" && event.type === "item.started") return `codex: ${String(item.command ?? "").slice(0, 160)}`;
  if (item.type === "reasoning" && event.type === "item.completed" && item.text) return `codex: ${String(item.text).split("\n")[0]!.slice(0, 160)}`;
  return null;
}

export async function callCodex(call: ModelCall): Promise<ModelAnswer> {
  const file = which("codex");
  if (!file) throw new ModelFailure("Codex is not installed on this machine", "error");
  const paths: string[] = [];
  if (call.images.length) {
    const dir = join(call.scratch, "images");
    mkdirSync(dir, { recursive: true });
    call.images.forEach((image, n) => {
      const path = join(dir, `image-${n + 1}.${image.media_type === "image/png" ? "png" : "jpg"}`);
      writeFileSync(path, Buffer.from(image.data, "base64"));
      paths.push(path);
    });
  }
  const stdin = imageLabels(paths, call.images) + preamble(!!call.checkout) + `${call.system}\n\n${call.prompt}`;
  call.log(`codex ${call.model || "(default model)"} started`);
  let pending = "";
  const ran = await run(file, codexArgs(call.model, call.thinkingDepth, paths), {
    cwd: call.checkout ?? call.scratch,
    env: cliEnv(),
    stdin,
    timeoutMs: call.timeoutMs,
    signal: call.signal,
    onStdout: (chunk) => {
      pending += chunk;
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const event of codexEvents(lines.join("\n"))) {
        const said = describe(event);
        if (said) call.log(said);
      }
    },
  });
  if (ran.cancelled) throw new Cancelled("taken back");
  if (ran.timedOut) throw new ModelFailure(`codex exec timed out after ${Math.round(call.timeoutMs / 1000)}s`, "timeout");
  const result = parseCodexOutput(ran.stdout);
  if (result.error || (ran.code !== 0 && !result.text)) {
    const why = result.error ?? ((ran.stderr || ran.stdout).trim().slice(-400) || `exit ${ran.code}`);
    throw new ModelFailure(`Codex: ${why}`, REFUSED.test(why) ? "rejected" : "error");
  }
  if (!result.text) throw new ModelFailure("codex exec gave no answer", "error");
  return { text: result.text, model: call.model || null, inputTokens: result.inputTokens, outputTokens: result.outputTokens };
}
