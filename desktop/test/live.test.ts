// Against a real Slipwright server, when one is named: pairs with a fresh connection code
// and polls once. Skipped otherwise. How the app was checked against the Python server:
//
//   uv run slipwright serve --no-auth --port 18765 --provider scripted --state-dir <tmp>
//   curl -X POST localhost:18765/api/workers/code -H 'content-type: application/json' -d '{"address":"http://127.0.0.1:18765"}'
//   SLIPWRIGHT_LIVE_CODE=SW-… npx vitest run test/live.test.ts

import { describe, expect, it } from "vitest";
import { pair, WorkerClient } from "../src/main/client";
import { DirectTransport } from "../src/main/transport";

const CODE = process.env.SLIPWRIGHT_LIVE_CODE;

describe.skipIf(!CODE)("a real server", () => {
  it("pairs with its code and is polled without being given anything it cannot do", async () => {
    const paired = await pair(CODE!, { name: "desktop-test", capabilities: ["write:backend"], lookAround: async () => [] });
    expect(paired.token).toMatch(/^swk_/);
    const client = new WorkerClient(new DirectTransport(paired.address!), paired.token);
    await client.heartbeat();
    expect(await client.poll(["write:backend"], "desktop-test", 1)).toBeNull();
  }, 30_000);
});
