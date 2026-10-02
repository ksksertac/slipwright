import { describe, expect, it } from "vitest";
import { projectEnv } from "../src/main/build";
import { inProgress, siteUrl } from "../src/main/jira";
import { authHeader, gitEnv } from "../src/main/source";
import { hint } from "../src/main/store";
import { progressText } from "../src/main/worker";

describe("a build's environment", () => {
  it("is an allow list: a key in the person's shell is not there", () => {
    const env = projectEnv({ PATH: "/bin", HOME: "/h", ANTHROPIC_API_KEY: "sk-ant-x", GH_TOKEN: "ghp_x" }, { ANDROID_HOME: "/sdk" });
    expect(env).toEqual({ PATH: "/bin", HOME: "/h", CI: "1", ANDROID_HOME: "/sdk" });
  });
});

describe("the source token", () => {
  const creds = { github: "ghp_secret", bitbucketUser: "ayse", bitbucket: "app-pass" };

  it("is sent only to the host it belongs to", () => {
    expect(authHeader("https://github.com/acme/x.git", creds)).toBe(`Authorization: Basic ${Buffer.from("x-access-token:ghp_secret").toString("base64")}`);
    expect(authHeader("https://bitbucket.org/acme/x.git", creds)).toBe(`Authorization: Basic ${Buffer.from("ayse:app-pass").toString("base64")}`);
    expect(authHeader("https://evil.example.com/github.com/x.git", creds)).toBeNull();
  });

  it("reaches git through its environment, never its URL or argv", () => {
    const env = gitEnv("Authorization: Basic abc");
    expect(env.GIT_CONFIG_KEY_0).toBe("http.extraheader");
    expect(env.GIT_CONFIG_VALUE_0).toBe("Authorization: Basic abc");
    expect(env.GIT_TERMINAL_PROMPT).toBe("0");
  });

  it("is shown only as a hint", () => {
    expect(hint("sk-ant-api03-abcdefgh3f9A")).toBe("sk-ant-••••3f9A");
    expect(hint(null)).toBeNull();
  });
});

describe("Jira", () => {
  it("moves an issue by the In Progress category, whatever the status is called", () => {
    const move = inProgress([
      { id: "11", name: "Done", to: { statusCategory: { key: "done" } } },
      { id: "21", name: "Başla", to: { name: "Devam ediyor", statusCategory: { key: "indeterminate" } } },
    ]);
    expect(move?.id).toBe("21");
    expect(inProgress([{ id: "1", name: "x", to: { statusCategory: { key: "new" } } }])).toBeNull();
    expect(siteUrl("https://acme.atlassian.net/")).toBe("https://acme.atlassian.net");
  });
});

describe("progress", () => {
  it("says what the machine is doing and for how long", () => {
    expect(progressText(0, 30_000)).toBe("yazıyor · <1 dk");
    expect(progressText(0, 3 * 60_000 + 5)).toBe("yazıyor · 3 dk");
  });
});
