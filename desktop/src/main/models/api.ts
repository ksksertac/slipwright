// A person's own API key, Anthropic's or OpenAI's, called straight from this machine.
// Plain fetch rather than either SDK: one request shape each, and the app stays free of
// two large dependencies for it. The key never leaves the main process except in the
// request header to its own vendor.

import { Cancelled, ModelFailure, type ModelAnswer, type ModelCall } from "./types";

export const ANTHROPIC_DEFAULT = "claude-sonnet-5-5";
export const OPENAI_DEFAULT = "gpt-5";

const EFFORT: Record<string, string> = { low: "low", medium: "medium", high: "high", max: "max" };

function failure(status: number, body: string, vendor: string): ModelFailure {
  let message = body.slice(0, 400);
  try {
    const parsed = JSON.parse(body) as { error?: { message?: string } };
    message = parsed.error?.message ?? message;
  } catch {
    // not JSON
  }
  // a key that is wrong, out of credit or over its limit will be the same on a retry
  const kind = status === 401 || status === 403 || status === 429 || status === 402 ? "rejected" : "error";
  return new ModelFailure(`${vendor} ${status}: ${message}`, kind);
}

function signals(call: ModelCall): AbortSignal {
  return AbortSignal.any([call.signal, AbortSignal.timeout(call.timeoutMs)]);
}

function aborted(call: ModelCall, error: unknown): Error {
  if (call.signal.aborted) return new Cancelled("taken back");
  if ((error as Error)?.name === "TimeoutError") return new ModelFailure("the API call timed out", "timeout");
  return new ModelFailure(`could not reach the API: ${(error as Error)?.message ?? error}`, "error");
}

export interface SseState {
  text: string;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  stopReason: string | null;
  error: string | null;
}

/** Folds Anthropic's stream events into the answer. Streamed because a phase can be long:
 *  a non-streamed request with a large max_tokens risks the connection timing out first. */
export function foldAnthropicEvent(state: SseState, event: Record<string, unknown>): void {
  switch (event.type) {
    case "message_start": {
      const message = (event.message ?? {}) as { model?: string; usage?: Record<string, number> };
      state.model = message.model ?? state.model;
      const u = message.usage ?? {};
      state.inputTokens = (u.input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0);
      break;
    }
    case "content_block_delta": {
      const delta = (event.delta ?? {}) as { type?: string; text?: string };
      if (delta.type === "text_delta" && delta.text) state.text += delta.text;
      break;
    }
    case "message_delta": {
      const usage = (event.usage ?? {}) as { output_tokens?: number };
      const delta = (event.delta ?? {}) as { stop_reason?: string };
      if (usage.output_tokens != null) state.outputTokens = usage.output_tokens;
      if (delta.stop_reason) state.stopReason = delta.stop_reason;
      break;
    }
    case "error": {
      const error = (event.error ?? {}) as { type?: string; message?: string };
      state.error = `${error.type ?? "error"}: ${error.message ?? ""}`;
      break;
    }
  }
}

/** Splits an SSE body into the JSON of each `data:` line. */
export function* sseData(text: string): Generator<Record<string, unknown>> {
  for (const block of text.split(/\r?\n\r?\n/)) {
    for (const line of block.split(/\r?\n/)) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        yield JSON.parse(data);
      } catch {
        // half an event: the caller only passes whole blocks
      }
    }
  }
}

export async function callAnthropic(call: ModelCall, key: string): Promise<ModelAnswer> {
  const model = call.model || ANTHROPIC_DEFAULT;
  const content: unknown[] = call.images.map((image) => ({
    type: "image",
    source: { type: "base64", media_type: image.media_type, data: image.data },
  }));
  const labels = call.images.map((image, n) => (image.label ? `Image ${n + 1}: ${image.label}` : null)).filter(Boolean);
  content.push({ type: "text", text: (labels.length ? labels.join("\n") + "\n\n" : "") + call.prompt });
  const body: Record<string, unknown> = {
    model,
    max_tokens: 64000,
    stream: true,
    system: call.system,
    messages: [{ role: "user", content }],
  };
  const effort = call.thinkingDepth ? EFFORT[call.thinkingDepth] : undefined;
  if (effort) body.output_config = { effort };
  call.log(`Anthropic API · ${model}`);
  let response: Response;
  try {
    response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01" },
      body: JSON.stringify(body),
      signal: signals(call),
    });
  } catch (error) {
    throw aborted(call, error);
  }
  if (!response.ok || !response.body) throw failure(response.status, await response.text(), "Anthropic");
  const state: SseState = { text: "", model, inputTokens: null, outputTokens: null, stopReason: null, error: null };
  const decoder = new TextDecoder();
  let pending = "";
  try {
    for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
      pending += decoder.decode(chunk, { stream: true });
      const cut = pending.lastIndexOf("\n\n");
      if (cut < 0) continue;
      for (const event of sseData(pending.slice(0, cut))) foldAnthropicEvent(state, event);
      pending = pending.slice(cut + 2);
    }
    for (const event of sseData(pending)) foldAnthropicEvent(state, event);
  } catch (error) {
    throw aborted(call, error);
  }
  if (state.error) throw new ModelFailure(`Anthropic: ${state.error}`, /rate_limit|authentication|permission|billing/.test(state.error) ? "rejected" : "error");
  if (!state.text) throw new ModelFailure(`Anthropic gave no answer (${state.stopReason ?? "no stop reason"})`, "error");
  return { text: state.text, model: state.model, inputTokens: state.inputTokens, outputTokens: state.outputTokens };
}

export async function callOpenAI(call: ModelCall, key: string): Promise<ModelAnswer> {
  const model = call.model || OPENAI_DEFAULT;
  const content: unknown[] = [{ type: "text", text: call.prompt }];
  for (const image of call.images) {
    content.push({ type: "image_url", image_url: { url: `data:${image.media_type};base64,${image.data}` } });
  }
  call.log(`OpenAI API · ${model}`);
  let response: Response;
  try {
    response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model,
        // json_object needs the word "JSON" somewhere in the messages; the server's
        // prompts always ask for one, and the system line says so regardless
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: `${call.system}\n\nAnswer with one JSON object.` },
          { role: "user", content },
        ],
      }),
      signal: signals(call),
    });
  } catch (error) {
    throw aborted(call, error);
  }
  const text = await response.text().catch((error) => {
    throw aborted(call, error);
  });
  if (!response.ok) throw failure(response.status, text, "OpenAI");
  const parsed = JSON.parse(text) as {
    model?: string;
    choices?: { message?: { content?: string } }[];
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };
  const answer = parsed.choices?.[0]?.message?.content ?? "";
  if (!answer) throw new ModelFailure("OpenAI gave no answer", "error");
  return {
    text: answer,
    model: parsed.model ?? model,
    inputTokens: parsed.usage?.prompt_tokens ?? null,
    outputTokens: parsed.usage?.completion_tokens ?? null,
  };
}
