import { mkdtempSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fromApp, parseModel, readSettings, SettingsError, template } from "../src/cli/settings";
import { forgetState, readState, writeState } from "../src/cli/state";

const read = (raw: unknown, env: NodeJS.ProcessEnv = {}) => readSettings(raw, { env, defaultWorkDir: "./work" });

describe("settings.json on a server", () => {
  it("is enough with nothing in it: three agents on, devops off, one task at a time", () => {
    const { settings, warnings } = read({});
    expect(settings.agents.backend.enabled).toBe(true);
    expect(settings.agents.devops.enabled).toBe(false);
    expect(settings.maxConcurrent).toBe(1);
    expect(settings.workDir).toBe("./work");
    expect(warnings).toEqual([]);
  });

  it("reads a model as provider and optional model", () => {
    expect(parseModel("claude-code", "x")).toEqual({ provider: "claude-code", model: "" });
    expect(parseModel("codex:gpt-5", "x")).toEqual({ provider: "codex", model: "gpt-5" });
    expect(() => parseModel("gemini", "agents.web.model")).toThrow(SettingsError);
  });

  it("takes a secret from the environment when it says env:", () => {
    const { settings, warnings } = read(
      { keys: { anthropic: "env:ANTHROPIC_API_KEY", openai: "env:NOT_SET" } },
      { ANTHROPIC_API_KEY: "sk-ant-x" },
    );
    expect(settings.secrets.anthropic).toBe("sk-ant-x");
    expect(settings.secrets.openai).toBeNull();
    expect(warnings.join()).toContain("NOT_SET");
  });

  it("warns of what it does not know instead of refusing to start", () => {
    const { warnings } = read({ colour: "blue", agents: { qa: { enabled: true } } });
    expect(warnings.join("\n")).toMatch(/"colour" is not a setting/);
    expect(warnings.join("\n")).toMatch(/agents.qa is not an agent/);
  });

  it("refuses what would do the wrong thing", () => {
    expect(() => read({ max_concurrent: 0 })).toThrow(SettingsError);
    expect(() => read([])).toThrow(SettingsError);
  });

  it("says when an agent's key is missing", () => {
    const { warnings } = read({ agents: { web: { model: "anthropic" } } });
    expect(warnings.join()).toContain("keys.anthropic is empty");
  });

  it("writes a template that reads back without a word", () => {
    const { warnings, settings } = read(template("build-1"));
    expect(warnings).toEqual([]);
    expect(settings.name).toBe("build-1");
    expect(settings.agents.backend.model).toEqual({ provider: "claude-code", model: "" });
  });
});

describe("the app's choices, saved for a server", () => {
  const app = {
    agents: {
      backend: { enabled: true, model: { provider: "claude-code" as const, model: "sonnet" } },
      web: { enabled: true, model: { provider: "codex" as const, model: "" } },
      mobile: { enabled: false, model: null },
      devops: { enabled: false, model: null },
    },
    maxConcurrent: 2,
    runBuilds: false,
    bitbucketUser: null,
    jira: { site: "acme.atlassian.net", email: "a@acme.com" },
  };
  const secrets = { anthropic: "sk-ant-1", openai: null, github: "ghp_1", bitbucket: null, jira: "ATATT1" };

  it("reads back on the server as the same choices", () => {
    const { settings, warnings } = read(fromApp(app, secrets, "srv", true));
    expect(warnings).toEqual([]);
    expect(settings.agents.backend.model).toEqual({ provider: "claude-code", model: "sonnet" });
    expect(settings.agents.web.model).toEqual({ provider: "codex", model: "" });
    expect(settings.agents.mobile.enabled).toBe(false);
    expect(settings.maxConcurrent).toBe(2);
    expect(settings.secrets.github).toBe("ghp_1");
  });

  it("leaves the keys out unless asked, as env: names to set on the server", () => {
    const file = fromApp(app, secrets, "srv", false);
    expect(JSON.stringify(file)).not.toContain("sk-ant-1");
    expect(file.keys?.anthropic).toBe("env:ANTHROPIC_API_KEY");
    expect(file.keys?.openai).toBe(""); // none here: nothing to name
    const { settings } = read(file, { ANTHROPIC_API_KEY: "sk-ant-server" });
    expect(settings.secrets.anthropic).toBe("sk-ant-server");
  });
});

describe("the pairing beside it", () => {
  it("is kept apart, readable by its owner alone, and forgotten on request", () => {
    const dir = mkdtempSync(join(tmpdir(), "sw-state-"));
    const path = join(dir, "slipwright-agent.state.json");
    expect(readState(path)).toBeNull();
    const state = {
      pairing: { workerId: "w1", name: "build-1", address: "http://10.0.0.2:8000", relay: null, pairedAt: "now" },
      token: "swk_x",
      relayClientSk: null,
      serverPk: null,
    };
    writeState(path, state);
    expect(readState(path)).toEqual(state);
    expect(JSON.parse(readFileSync(path, "utf8")).token).toBe("swk_x");
    if (process.platform !== "win32") expect(statSync(path).mode & 0o077).toBe(0);
    forgetState(path);
    expect(readState(path)).toBeNull();
  });
});
