import { describe, expect, it } from "vitest";
import { foldAnthropicEvent, sseData, type SseState } from "../src/main/models/api";
import { claudeArgs, parseClaudeOutput } from "../src/main/models/claude";
import { codexArgs, parseCodexOutput } from "../src/main/models/codex";
import { REFUSED } from "../src/main/models/types";

describe("Claude Code's answer", () => {
  const ok = JSON.stringify({
    type: "result",
    subtype: "success",
    is_error: false,
    result: '{"files": []}',
    usage: { input_tokens: 10, cache_creation_input_tokens: 100, cache_read_input_tokens: 1000, output_tokens: 42 },
    modelUsage: { "claude-haiku-4-5": {}, "claude-sonnet-5-5": {} },
  });

  it("is the result text, exactly, with every input token counted", () => {
    expect(parseClaudeOutput(ok)).toEqual({ text: '{"files": []}', isError: false, model: "claude-sonnet-5-5", inputTokens: 1110, outputTokens: 42 });
  });

  it("is found after warnings the CLI printed first", () => {
    expect(parseClaudeOutput(`warning: something\n${ok}\n`)?.text).toBe('{"files": []}');
  });

  it("says when it is an error, and a plan's refusal reads as one", () => {
    const failed = parseClaudeOutput(JSON.stringify({ type: "result", is_error: true, result: "Claude AI usage limit reached" }));
    expect(failed?.isError).toBe(true);
    expect(REFUSED.test(failed!.text)).toBe(true);
    expect(parseClaudeOutput("not json")).toBeNull();
  });

  it("is asked for with read-only tools and the prompt on stdin", () => {
    expect(claudeArgs("opus", null)).toEqual([
      "-p",
      "--output-format",
      "json",
      "--allowedTools",
      "Read,Grep,Glob",
      "--disallowedTools",
      expect.stringContaining("Edit"),
      "--model",
      "opus",
    ]);
    expect(claudeArgs("", "/tmp/i")).toContain("--add-dir");
  });
});

describe("Codex's answer", () => {
  const stdout = [
    '{"type":"thread.started","thread_id":"t"}',
    '{"type":"item.completed","item":{"type":"reasoning","text":"thinking"}}',
    '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
    JSON.stringify({ type: "item.completed", item: { type: "agent_message", text: '{"ok":true}' } }),
    '{"type":"turn.completed","usage":{"input_tokens":500,"output_tokens":20,"reasoning_output_tokens":30}}',
  ].join("\n");

  it("is the last agent message, with reasoning counted as output", () => {
    expect(parseCodexOutput(stdout)).toEqual({ text: '{"ok":true}', inputTokens: 500, outputTokens: 50, error: null });
  });

  it("reports an error event", () => {
    const failed = JSON.stringify({ type: "turn.failed", error: { message: "You have hit your usage limit" } });
    expect(parseCodexOutput(failed).error).toBe("You have hit your usage limit");
  });

  it("is asked for in a read-only sandbox, as providers/codex.py asks", () => {
    expect(codexArgs("gpt-5", "max", ["/a.png", "/b.png"])).toEqual([
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--ephemeral",
      "--sandbox",
      "read-only",
      "-m",
      "gpt-5",
      "-c",
      "model_reasoning_effort=high",
      "--image=/a.png,/b.png",
      "-",
    ]);
    expect(codexArgs("default", null, [])).toEqual(["exec", "--json", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", "-"]);
  });
});

describe("the Anthropic API's stream", () => {
  it("folds into the text and the tokens", () => {
    const events = [
      { type: "message_start", message: { model: "claude-sonnet-5-5", usage: { input_tokens: 7, cache_read_input_tokens: 3 } } },
      { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: '{"a"' } },
      { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: ":1}" } },
      { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 5 } },
    ];
    const body = events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}`).join("\n\n");
    const state: SseState = { text: "", model: null, inputTokens: null, outputTokens: null, stopReason: null, error: null };
    for (const event of sseData(body)) foldAnthropicEvent(state, event);
    expect(state).toEqual({ text: '{"a":1}', model: "claude-sonnet-5-5", inputTokens: 10, outputTokens: 5, stopReason: "end_turn", error: null });
  });
});
