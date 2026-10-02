# The Slipwright relay

A meeting point for a Slipwright installation and the machines paired to it when they are
not on the same network: a server behind a NAT, a laptop on a café's Wi-Fi. Both sides dial
*out* to `relay.slipwright.app`, and the relay passes frames between them. It is a
Cloudflare Worker with one Durable Object per installation (a *room*).

The contract is [docs/machines-protocol.md §3](../docs/machines-protocol.md#3-the-relay).

## What it can and cannot see

It is built to be trusted with delivery and nothing else.

| It sees | It cannot see |
|---|---|
| a room id: which installation | any request or answer -- each is sealed end to end (X25519, ChaCha20-Poly1305) between the machine and the server |
| a peer id: half of a machine's public key | worker tokens, code secrets, model keys, source -- all inside the boxes |
| the size and timing of frames | which path a request is for |
| `sha256` of the host token, never the token | |

It cannot pose as the server either. At pairing the server proves its key with a MAC made
from the connection code's secret, which never passes through the relay; a key the relay
swapped in would fail that check. It reads `to`, writes `from` (over any the sender claimed), touches nothing else, and
does not log frames (observability is off in `wrangler.toml`).

## Rooms

```
wss://relay.slipwright.app/v1/rooms/{room}/host?token={host_token}    the installation
wss://relay.slipwright.app/v1/rooms/{room}/guest?peer={peer}          a machine
```

- The first host to connect claims the room; another token is closed with `4003`. The same
  token again replaces the earlier connection (closed `4000`).
- A machine may join only while the host is there (`4004` otherwise). The same peer again
  replaces the earlier connection.
- Frames are JSON text up to 1 MiB. Errors come back to the sender as
  `{"error": "host-offline" | "no-such-peer" | "too-large" | "slow-down" | "bad-frame"}`.
- A machine may send 120 frames a minute; the host is not limited.
- A room nobody has hosted for 30 days is forgotten.

`GET /` answers `{"service": "slipwright-relay", "version": ...}`; `GET /healthz` answers
`{"ok": true}`.

## Working on it

```bash
cd relay
npm install          # npm 10.9 trips on vitest's peers; `npx npm@11 install` does not
npm test             # inside workerd, against the real Durable Object and real sockets
npm run typecheck
npm run dev          # a local relay on http://localhost:8787
node scripts/smoke.mjs http://localhost:8787    # a host, a guest, a frame each way
```

`compatibility_date` must not be newer than the workerd that
`@cloudflare/vitest-pool-workers` ships, or the tests cannot start.

## Deploying

```bash
npx wrangler login
npm run deploy
node scripts/smoke.mjs https://relay.slipwright.app
```

`relay.slipwright.app` is a custom domain on the `slipwright.app` zone; the deploy creates
its DNS record. It runs on the free plan (SQLite-backed Durable Objects, hibernating
sockets: a quiet room costs nothing).

## Running your own

Nothing ties an installation to this relay. To use your own:

1. In `wrangler.toml`, put your own host in `routes` -- or delete the line and set
   `workers_dev = true` to use `slipwright-relay.<you>.workers.dev`.
2. `npm run deploy`, then `node scripts/smoke.mjs https://<your host>`.
3. Start the server with `SLIPWRIGHT_RELAY=wss://<your host>`. Connection codes it makes
   from then on carry that host, so its machines go there too.

Since everything is sealed end to end, running your own buys independence, not privacy:
the public relay already sees nothing it could use.
