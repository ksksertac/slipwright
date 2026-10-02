// Claude Code, as the person installed it and signed in to it.
//
// One `claude -p --output-format json` per call: the prompt on stdin (far longer than a
// command line allows, and on Windows a command line is 32K), the checkout as the working
// directory, and only the tools that read. The server applies whatever comes back; the
// model's job here is to answer, never to edit, so Edit/Write/Bash are not given to it.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { run, which } from "../proc";
import { Cancelled, cliEnv, imageLabels, ModelFailure, preamble, REFUSED, type ModelAnswer, type ModelCall } from "./types";

export const READ_ONLY_TOOLS = "Read,Grep,Glob";
const NEVER = "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch";

export interface ClaudeResult {
  text: string;
  isError: boolean;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
}

/** The result object of `--output-format json`. Read leniently: an older CLI printed
 *  warnings before it, and `stream-json` ends with the same object as its last line. */
export function parseClaudeOutput(stdout: string): ClaudeResult | null {
  const candidates = [stdout.trim(), ...stdout.split(/\r?\n/).reverse()];
  for (const line of candidates) {
    const text = line.trim();
    if (!text.startsWith("{")) continue;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text);
    } catch {
      continue;
    }
    if (parsed.type !== "result" && !("result" in parsed)) continue;
    const usage = (parsed.usage ?? {}) as Record<string, number | undefined>;
    const counted = ["input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"].map((k) => usage[k]);
    const input = counted.some((n) => typeof n === "number") ? counted.reduce<number>((a, n) => a + (n ?? 0), 0) : null;
    const models = Object.keys((parsed.modelUsage ?? {}) as object);
    return {
      text: typeof parsed.result === "string" ? parsed.result : "",
      isError: parsed.is_error === true || (typeof parsed.subtype === "string" && parsed.subtype.startsWith("error")),
      // the model that did most of the work; Claude Code also uses a small one for chores
      model: models.find((m) => !/haiku/i.test(m)) ?? models[0] ?? null,
      inputTokens: input,
      outputTokens: typeof usage.output_tokens === "number" ? usage.output_tokens : null,
    };
  }
  return null;
}

export function claudeArgs(model: string, imageDir: string | null): string[] {
  const args = ["-p", "--output-format", "json", "--allowedTools", READ_ONLY_TOOLS, "--disallowedTools", NEVER];
  if (model && model !== "default") args.push("--model", model);
  if (imageDir) args.push("--add-dir", imageDir);
  return args;
}

export async function callClaude(call: ModelCall): Promise<ModelAnswer> {
  const file = which("claude");
  if (!file) throw new ModelFailure("Claude Code is not installed on this machine", "error");
  let imageDir: string | null = null;
  const paths: string[] = [];
  if (call.images.length) {
    imageDir = join(call.scratch, "images");
    mkdirSync(imageDir, { recursive: true });
    call.images.forEach((image, n) => {
      const path = join(imageDir!, `image-${n + 1}.${image.media_type === "image/png" ? "png" : "jpg"}`);
      writeFileSync(path, Buffer.from(image.data, "base64"));
      paths.push(path);
    });
  }
  const stdin = preamble(!!call.checkout) + imageLabels(paths, call.images) + `${call.system}\n\n${call.prompt}`;
  call.log(`claude ${call.model || "(default model)"} started`);
  const ran = await run(file, claudeArgs(call.model, imageDir), {
    cwd: call.checkout ?? call.scratch,
    env: cliEnv(),
    stdin,
    timeoutMs: call.timeoutMs,
    signal: call.signal,
    onStderr: (chunk) => chunk.trim() && call.log(chunk.trim().slice(0, 200)),
  });
  if (ran.cancelled) throw new Cancelled("taken back");
  if (ran.timedOut) throw new ModelFailure(`claude timed out after ${Math.round(call.timeoutMs / 1000)}s`, "timeout");
  const result = parseClaudeOutput(ran.stdout);
  if (!result || result.isError || !result.text) {
    const why = (result?.text || ran.stderr || ran.stdout).trim().slice(-400) || `exit ${ran.code}`;
    throw new ModelFailure(`Claude Code: ${why}`, REFUSED.test(why) ? "rejected" : "error");
  }
  return { text: result.text, model: result.model ?? (call.model || null), inputTokens: result.inputTokens, outputTokens: result.outputTokens };
}
