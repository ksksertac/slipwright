// The client is the only thing that talks to the server, so it is the thing worth testing:
// how it signs in, what it does with a refusal, and how a development is started.
import { describe, expect, it } from "vitest";
import { ApiError, SlipwrightApi, isWaiting, stateLabel } from "../src/api";
import { headline, icon } from "../src/tree";

type Call = { url: string; method: string; headers: Record<string, string>; body?: string };

function server(routes: Record<string, (call: Call) => Response>): {
  fetch: typeof fetch;
  calls: Call[];
} {
  const calls: Call[] = [];
  const fake = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const call: Call = {
      url,
      method: init?.method ?? "GET",
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body as string | undefined,
    };
    calls.push(call);
    const key = `${call.method} ${new URL(url).pathname}`;
    const route = routes[key];
    if (!route) return new Response("no route", { status: 404 });
    return route(call);
  }) as unknown as typeof fetch;
  return { fetch: fake, calls };
}

const json = (body: unknown, init: ResponseInit = {}): Response =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });

describe("signing in", () => {
  it("logs in, asks who that is and keeps a token of its own", async () => {
    const { fetch, calls } = server({
      "POST /api/auth/login": () =>
        json(
          { id: "u1", username: "ada", is_admin: true },
          { headers: { "set-cookie": "session=abc", "content-type": "application/json" } },
        ),
      "POST /api/users/u1/tokens": (call) => {
        expect(call.headers["Cookie"]).toBe("session=abc");
        expect(JSON.parse(call.body!)).toEqual({ name: "vs code" });
        return json({ token: { id: "t1", name: "vs code" }, secret: "sw_secret" }, { status: 201 });
      },
    });
    const api = new SlipwrightApi("http://localhost:8500/", null, fetch);

    const { secret, me } = await api.signIn("ada", "pw");

    expect(secret).toBe("sw_secret");
    expect(me.username).toBe("ada");
    expect(calls[0]!.url).toBe("http://localhost:8500/api/auth/login");
    expect(calls[0]!.headers["Authorization"]).toBeUndefined();
  });

  it("says plainly that the sign-in was refused", async () => {
    const { fetch } = server({
      "POST /api/auth/login": () => json({ detail: "wrong username or password" }, { status: 401 }),
    });
    const api = new SlipwrightApi("http://localhost:8500", null, fetch);
    await expect(api.signIn("ada", "no")).rejects.toThrow(/did not accept/);
  });

  it("reports a server that cannot be reached at all", async () => {
    const fake = (async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    const api = new SlipwrightApi("http://nowhere:8500", null, fake);
    await expect(api.projects()).rejects.toThrow(/could not be reached/);
  });
});

describe("talking to the server with a token", () => {
  it("carries the bearer token and reads the projects", async () => {
    const { fetch, calls } = server({
      "GET /api/projects": () => json([{ id: "p1", name: "demo", description: "" }]),
    });
    const api = new SlipwrightApi("http://localhost:8500", "sw_secret", fetch);

    const projects = await api.projects();

    expect(projects).toHaveLength(1);
    expect(calls[0]!.headers["Authorization"]).toBe("Bearer sw_secret");
  });

  it("starts a development and hands back the job", async () => {
    const { fetch, calls } = server({
      "POST /api/projects/p1/jobs": () =>
        json({ id: "j1", project_id: "p1", request: "add /health", state: "backlog" }, { status: 201 }),
    });
    const api = new SlipwrightApi("http://localhost:8500", "sw_secret", fetch);

    const job = await api.startDevelopment("p1", "add /health");

    expect(job.id).toBe("j1");
    expect(JSON.parse(calls[0]!.body!)).toEqual({ request: "add /health" });
  });

  it("passes the server's own words on when it refuses", async () => {
    const { fetch } = server({
      "POST /api/projects/p1/jobs": () =>
        json({ detail: "a development is already running" }, { status: 409 }),
    });
    const api = new SlipwrightApi("http://localhost:8500", "t", fetch);
    await expect(api.startDevelopment("p1", "x")).rejects.toThrow("a development is already running");
    await expect(api.startDevelopment("p1", "x")).rejects.toBeInstanceOf(ApiError);
  });

  it("builds the pages a person opens in a browser", () => {
    const api = new SlipwrightApi("http://localhost:8500/", "t");
    expect(api.urlFor("project", "p1")).toBe("http://localhost:8500/projects/p1");
    expect(api.urlFor("job", "j1", "p1")).toBe("http://localhost:8500/projects/p1/jobs/j1");
  });
});

describe("what the tree shows", () => {
  it("names every state a person can meet, and marks the ones that wait", () => {
    expect(stateLabel("awaiting_architecture_approval")).toBe("waiting: the work list");
    expect(stateLabel("done")).toBe("done");
    expect(stateLabel("something_new")).toBe("something_new");
    expect(isWaiting("awaiting_test_approval")).toBe(true);
    expect(isWaiting("developing")).toBe(false);
  });

  it("shortens a request to its first line", () => {
    expect(headline("add /health\nwith tests")).toBe("add /health");
    expect(headline("x".repeat(90))).toHaveLength(72);
    expect(headline("x".repeat(90)).endsWith("…")).toBe(true);
  });

  it("picks an icon that says what is happening", () => {
    expect(icon("done")).toBe("pass-filled");
    expect(icon("failed")).toBe("error");
    expect(icon("awaiting_test_approval")).toBe("bell-dot");
    expect(icon("developing")).toBe("sync");
  });
});
