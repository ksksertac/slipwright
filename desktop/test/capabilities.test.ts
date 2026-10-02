import { describe, expect, it } from "vitest";
import { agentFor, capabilities } from "../src/main/capabilities";
import { NOTHING } from "../src/main/detect";
import { defaultSettings } from "../src/main/store";

const claude = { ...NOTHING, claude: { installed: true, version: "2", signedIn: true } };
const noKeys = { anthropic: false, openai: false };

describe("what a machine says it can be given", () => {
  it("is nothing at all with no model and no toolchain", () => {
    expect(capabilities(defaultSettings(), NOTHING, noKeys)).toEqual([]);
  });

  it("is a write domain for each agent that is on and has a model it can run", () => {
    const s = defaultSettings();
    s.agents.backend.model = { provider: "claude-code", model: "" };
    s.agents.web.model = { provider: "codex", model: "" }; // not installed: not offered
    s.agents.mobile.model = { provider: "anthropic", model: "" };
    s.agents.devops = { enabled: false, model: { provider: "claude-code", model: "" } };
    expect(capabilities(s, claude, { anthropic: true, openai: false })).toEqual([
      "write:backend",
      "write:general",
      "write:docs",
      "write:mobile",
    ]);
  });

  it("includes the platforms it builds, unless builds are switched off", () => {
    const found = { ...NOTHING, ios: { ok: true, detail: "Xcode 17" }, android: { ok: true, detail: "Android SDK 36" } };
    const s = defaultSettings();
    expect(capabilities(s, found, noKeys)).toEqual(["ios", "android"]);
    s.runBuilds = false;
    expect(capabilities(s, found, noKeys)).toEqual([]);
  });

  it("does not offer a CLI that is known to be signed out", () => {
    const s = defaultSettings();
    s.agents.backend.model = { provider: "claude-code", model: "" };
    const out = { ...NOTHING, claude: { installed: true, version: "2", signedIn: false } };
    expect(capabilities(s, out, noKeys)).toEqual([]);
  });

  it("hands each domain to its agent", () => {
    expect(["backend", "general", "docs", "web", "mobile", "infra", undefined].map(agentFor)).toEqual([
      "backend",
      "backend",
      "backend",
      "web",
      "mobile",
      "devops",
      "backend",
    ]);
  });
});
