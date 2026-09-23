// The server's event stream, read in the extension host. One connection for the window;
// when it drops we come back asking for what we missed (`?since=`), so a window left open
// overnight is never quietly out of date.
export type ServerEvent = {
  id: number;
  type: string;
  project_id?: string | null;
  job_id?: string | null;
  payload?: Record<string, unknown>;
};

type Fetch = typeof fetch;

export class EventStream {
  private controller: AbortController | null = null;
  private stopped = false;
  private lastId = 0;
  private attempt = 0;

  constructor(
    private readonly endpoint: () => string,
    private readonly token: () => string | null,
    private readonly onEvent: (event: ServerEvent) => void,
    private readonly http: Fetch = fetch,
    private readonly wait: (ms: number) => Promise<void> = (ms) =>
      new Promise((r) => setTimeout(r, ms)),
  ) {}

  /** How long to wait before the next attempt: 1s, 2s, 4s … capped at 30s. */
  backoff(attempt: number): number {
    return Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));
  }

  start(): void {
    this.stopped = false;
    void this.loop();
  }

  stop(): void {
    this.stopped = true;
    this.controller?.abort();
    this.controller = null;
  }

  private async loop(): Promise<void> {
    while (!this.stopped) {
      const token = this.token();
      if (!token) {
        await this.wait(2000);
        continue;
      }
      try {
        await this.connect(token);
        // a clean end means the server closed the stream; come back, but not in a tight loop
        this.attempt = 0;
        if (this.stopped) return;
        await this.wait(this.backoff(1));
      } catch {
        this.attempt += 1;
        if (this.stopped) return;
        await this.wait(this.backoff(this.attempt));
      }
    }
  }

  private async connect(token: string): Promise<void> {
    const controller = new AbortController();
    this.controller = controller;
    const since = this.lastId > 0 ? `?since=${this.lastId}` : "";
    const resp = await this.http(`${this.endpoint().replace(/\/+$/, "")}/api/events${since}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
      signal: controller.signal,
    });
    if (!resp.ok || !resp.body) throw new Error(`the stream refused to open (${resp.status})`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let cut = buffer.indexOf("\n\n");
      while (cut !== -1) {
        this.handle(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        cut = buffer.indexOf("\n\n");
      }
    }
  }

  /** One SSE frame: id, event and data lines, or a comment we ignore. */
  private handle(frame: string): void {
    let id = 0;
    let type = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("id: ")) id = Number(line.slice(4)) || 0;
      else if (line.startsWith("event: ")) type = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!data) return;
    if (id > 0) this.lastId = id;
    try {
      const parsed = JSON.parse(data) as Omit<ServerEvent, "id" | "type">;
      this.onEvent({ ...parsed, id, type });
    } catch {
      /* a frame we cannot read is not worth tearing the stream down for */
    }
  }
}
