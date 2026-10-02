// Against a real server through the real relay, when a relay code is named: pairs through
// the room, waits for the one call queued for the account, and answers it -- the whole of
// what a machine on another network does, minus the model. Skipped otherwise. Run with a
// server whose Machines page has *Reach machines on other networks* on:
//
//   SLIPWRIGHT_LIVE_RELAY_CODE=SW-… npx vitest run test/live-relay.test.ts

import { describe, expect, it } from "vitest";
import { pair, WorkerClient } from "../src/main/client";
import { publicFromSecret } from "../src/main/crypto";
import { RelayTransport } from "../src/main/transport";

const CODE = process.env.SLIPWRIGHT_LIVE_RELAY_CODE;

describe.skipIf(!CODE)("a real server, through the relay", () => {
  it("pairs through the room, takes a call and answers it", async () => {
    const paired = await pair(CODE!, { name: "desktop-relay-test", capabilities: ["write:backend"] });
    expect(paired.relay).not.toBeNull();
    expect(paired.token).toMatch(/^swk_/);

    // as the app does on its next start: the keys kept at pairing, nothing else
    const transport = new RelayTransport(paired.relay!.host, paired.relay!.room, {
      client: { secret: paired.clientSk!, public: publicFromSecret(paired.clientSk!) },
      server: paired.serverPk,
    });
    const client = new WorkerClient(transport, paired.token);
    try {
      await client.heartbeat();
      let call = null;
      for (let i = 0; i < 6 && !call; i++) call = await client.poll(["write:backend"], "desktop-relay-test", 5);
      expect(call?.kind).toBe("write");
      if (call?.kind !== "write") return;
      expect(await client.progress(call.id, "through the relay")).toBe(204);
      const answered = await client.answer(call.id, {
        text: JSON.stringify({ summary: "written on a machine far away", changes: [] }),
        model: "live-test",
        seconds: 1,
      });
      expect(answered).toBe(204);
    } finally {
      transport.close();
    }
  }, 120_000);
});
