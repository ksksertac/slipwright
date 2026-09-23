// The stream is what makes a window left open trustworthy: it reconnects, and it asks for
// what it missed rather than pretending nothing happened.
import { describe, expect, it, vi } from "vitest";
import { EventStream, type ServerEvent } from "../src/stream";

function sseResponse(frames: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

const frame = (id: number, type: string, data: Record<string, unknown>): string =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;

describe("the event stream", () => {
  it("reads whole frames, even when they arrive in pieces", async () => {
    const seen: ServerEvent[] = [];
    const whole = frame(1, "job.state", { job_id: "j1", payload: { state: "developing" } });
    const chunks = [whole.slice(0, 12), whole.slice(12), ": ping\n\n"];
    const http = vi.fn().mockResolvedValue(sseResponse(chunks)) as unknown as typeof fetch;
    const stream = new EventStream(
      () => "http://localhost:8500/",
      () => "tok",
      (e) => seen.push(e),
      http,
      async () => {
        stream.stop();
      },
    );

    stream.start();
    await vi.waitFor(() => expect(seen).toHaveLength(1));

    expect(seen[0]!.type).toBe("job.state");
    expect(seen[0]!.id).toBe(1);
    const [url, init] = (http as unknown as { mock: { calls: [string, RequestInit][] } }).mock
      .calls[0]!;
    expect(url).toBe("http://localhost:8500/api/events");
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer tok");
  });

  it("comes back asking for what it missed", async () => {
    const seen: ServerEvent[] = [];
    const calls: string[] = [];
    let round = 0;
    const http = (async (url: string) => {
      calls.push(String(url));
      round += 1;
      if (round === 1) return sseResponse([frame(7, "activity", { job_id: "j1" })]);
      return sseResponse([frame(8, "activity", { job_id: "j1" })]);
    }) as unknown as typeof fetch;
    const stream = new EventStream(
      () => "http://localhost:8500",
      () => "tok",
      (e) => seen.push(e),
      http,
      async () => {
        if (round >= 2) stream.stop();
      },
    );

    stream.start();
    await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));
    stream.stop();

    expect(calls[0]).toBe("http://localhost:8500/api/events");
    expect(calls[1]).toBe("http://localhost:8500/api/events?since=7");
  });

  it("waits longer each time a connection fails, up to half a minute", () => {
    const stream = new EventStream(
      () => "http://x",
      () => null,
      () => {},
    );
    expect(stream.backoff(1)).toBe(1000);
    expect(stream.backoff(2)).toBe(2000);
    expect(stream.backoff(4)).toBe(8000);
    expect(stream.backoff(10)).toBe(30_000);
  });

  it("does not connect at all until there is a token", async () => {
    const http = vi.fn() as unknown as typeof fetch;
    let waits = 0;
    const stream = new EventStream(
      () => "http://x",
      () => null,
      () => {},
      http,
      async () => {
        waits += 1;
        if (waits > 2) stream.stop();
      },
    );

    stream.start();
    await vi.waitFor(() => expect(waits).toBeGreaterThan(2));

    expect((http as unknown as { mock: { calls: unknown[] } }).mock.calls).toHaveLength(0);
  });
});
