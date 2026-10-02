# Machines: the wire protocol

What a machine lent to an account (Phase 17) and a Slipwright server say to each other,
directly or through the relay. Three programs speak it and must agree byte for byte:
the server (`slipwright/api/workers.py`, `slipwright/relay/`), the headless worker
(`slipwright/worker_agent.py`) and the desktop app (`desktop/`). The relay (`relay/`)
only carries it and can read none of it.

## 1. The worker API

Everything a machine does is one of these HTTP calls under `/api/worker/`. On a LAN they
are plain HTTP; through the relay each one is carried in an encrypted envelope (§3) and
answered the same way. Every call but `pair` carries `Authorization: Bearer swk_…`.

| Call | Body | Answer |
|---|---|---|
| `POST /pair` | `{code, name, capabilities}` | `200 {worker_id, token}`; `400` a bad copy; `403` used or run out |
| `POST /poll` | `{capabilities, wait_s ≤ 25, name?}` | `200` a build or a call; `204` nothing yet, ask again |
| `POST /heartbeat` | – | `204` |
| `GET /tasks/{id}/snapshot` | – | `200` tar.gz of the worktree |
| `POST /tasks/{id}/result` | `{exit_code, output, seconds}` | `204`; `409` not held |
| `POST /calls/{id}/progress` | `{text}` | `204`; `409` the call is no longer this machine's: stop |
| `POST /calls/{id}/answer` | `{text, model?, input_tokens?, output_tokens?, seconds}` | `204`; `409` not held |
| `POST /calls/{id}/fail` | `{message, kind}` (`rejected` \| `error` \| `timeout`) | `204` |

`401` from anything means the machine was removed: forget the pairing.

### Capabilities

Strings, each one a thing the machine can be given:

- `ios`, `android` -- it builds that platform (a build, T14)
- `write:backend`, `write:web`, `write:mobile`, `write:infra`, `write:docs`, `write:general`
  -- it writes phases of that domain with a model of its own (a call, T17)

Anything else is ignored. A machine that sends no `write:` capability is never given a call,
which is how a worker from before Phase 17 keeps working unchanged.

### A build (`kind: "build"`)

```json
{"kind": "build", "id": "…", "job_id": "…", "platform": "ios",
 "commands": [["build", "xcodebuild …"]], "timeout_s": 1800}
```

Unchanged from T14, with `kind` added.

### A call (`kind: "write"`)

One model call the server would otherwise have made itself: a specialist writing a phase.

```json
{
  "kind": "write",
  "id": "…",
  "job_id": "…",
  "project": "Randevu uygulaması",
  "phase": 4, "phases": 9,
  "goal": "Randevu API: oluşturma, iptal, listeleme",
  "role": "backend", "domain": "backend",
  "jira_key": "SCRUM-131",
  "system": "…", "prompt": "…",
  "output_schema": {…},
  "images": [{"media_type": "image/png", "data": "<base64>", "label": "…"}],
  "thinking_depth": "medium",
  "timeout_s": 1800,
  "repo": {"url": "https://github.com/acme/randevu.git", "branch": "slipwright/…", "commit": "a1b2c3…"}
}
```

The machine answers with **the model's text, exactly as it came**: one JSON object matching
`output_schema`. The server parses and validates it as it would its own provider's answer,
so a wrong answer costs a retry, never a wrong file. `repo` is where the code is, without
credentials; a machine with a source token may check it out read-only and let its model
read it (Claude Code's `Read`/`Grep`/`Glob`, Codex's read-only sandbox), and one without
answers from the prompt alone. `repo` is `null` when the project has no remote.

While it works the machine sends `progress` at least every 20 s; three missed (60 s) and
the call is taken back and asked of the server's own model. A `409` on `progress` means
exactly that happened: stop and drop the answer.

## 2. Connection codes

`SW-` and base32 (Crockford), as T14. The payload's address kinds:

| Kind | Payload | Meaning |
|---|---|---|
| 1, 2 | IPv4 + port | `http`/`https` to that address |
| 3 | URL text | that URL |
| 4 | port | `localhost`, or a host near it |
| **5** | `len(1) host(len) room(16)` | **the relay** at `wss://host`, in that room |
| 6 | as 5 | the same at `ws://host` -- a relay run for tests or on a LAN |

An address of kind 5 or 6 reads back as `wss://host/v1/rooms/<room hex>`, which is how a
machine knows to pair through the relay rather than call the server.

then the 10-byte secret and a CRC-8 check byte, unchanged.

## 3. The relay

### Rooms

A room is one installation. Its id is 16 random bytes (hex in URLs), made once and kept in
the installation's settings (`relay.room`), with a 32-byte host token (`relay.host_token`).
The room id is what a guest needs to reach it; it is not a secret of any weight, since
everything said in the room is encrypted end to end.

```
wss://relay.slipwright.app/v1/rooms/{room}/host?token={host_token}
wss://relay.slipwright.app/v1/rooms/{room}/guest?peer={peer}
```

- The first host connection claims the room (the relay keeps `sha256(token)`); a later one
  with another token is refused (`4003`). A second host connection with the right token
  replaces the first.
- A guest's `peer` is the hex of the first 16 bytes of its public key. A guest may connect
  only while the room has a host (`4004` otherwise).
- Frames are JSON text, at most 1 MiB each:
  - guest → relay `{"to": "host", ...}` arrives at the host as `{"from": "<peer>", ...}`
  - host → relay `{"to": "<peer>", ...}` arrives at that guest as `{"from": "host", ...}`
  - the relay removes `to`, sets `from` -- replacing any `from` the sender wrote, so a
    guest cannot pose as the host or another peer -- and touches nothing else
  - a connection replaced by a newer one for the same host or peer is closed with `4000`
  - a guest stays connected while the host is away and is told `host-offline`, so a server
    restarting does not disconnect every machine
  - `{"error": "host-offline" | "no-such-peer" | "too-large" | "slow-down"}` from the relay
- A guest may send 120 frames a minute; the host is not limited.
- A room nobody has hosted for 30 days is forgotten.

### Messages inside the frames

Every frame between peers carries one *part* of one message:

```json
{"mid": "<16 hex>", "part": 0, "parts": 3, "data": "<base64>"}
```

Parts are cut at 512 KiB of `data`; the receiver joins them in order. The joined bytes are
a JSON object, one of:

- `{"k": "hello", "pk": b64, "code_id": hex}` -- guest, pairing only. `code_id` is
  `sha256(secret)`, which the server already keeps; the secret itself never leaves the
  code in the clear.
- `{"k": "welcome", "pk": b64, "mac": b64}` -- host. `mac` is
  `HMAC-SHA256(pair_key, server_pk ‖ client_pk)` with
  `pair_key = HMAC-SHA256(secret, "slipwright-relay-pair")`. The guest checks it before
  trusting `pk`: the relay could hand it a key of its own, but cannot sign one. From then
  on the guest keeps the server's key with its token.
- `{"k": "box", "pk": b64, "n": b64, "c": b64}` -- an encrypted request (guest) or
  response (host).

### The box

X25519, HKDF-SHA256 and ChaCha20-Poly1305 -- in `cryptography` on the server and in
Node's own `crypto`, so neither side needs a library for it.

```
shared = X25519(my_secret_key, their_public_key)
key    = HKDF-SHA256(shared, salt = client_pk ‖ server_pk, info = "slipwright-relay-v1", 32)
c      = ChaCha20-Poly1305(key).encrypt(nonce = n (12 random bytes), plaintext, aad = dir)
```

`dir` is `c2s` for a guest's request and `s2c` for the host's answer, so a request cannot be
reflected back as an answer. `pk` in a request is the guest's public key; in an answer the
host's.

A request, once opened:

```json
{"id": "<16 hex>", "ts": 1790977000, "method": "POST", "path": "/api/worker/poll",
 "headers": {"authorization": "Bearer swk_…", "content-type": "application/json"},
 "body": "<base64>"}
```

An answer: `{"id": "…", "status": 200, "headers": {"content-type": "…"}, "body": "<base64>"}`.

The host serves only paths under `/api/worker/`, refuses a `ts` more than five minutes off,
and answers each request at most once.

### Pairing through the relay

1. Guest connects to the room, sends `hello` with a fresh key pair's public key.
2. Host finds the code by `code_id`, answers `welcome`. A code it does not know gets no
   answer (the guest times out and says the code is used or run out).
3. Guest checks `mac`, then sends `POST /api/worker/pair` in a box, as on a LAN.
4. From then on: boxes only, each request to the key it kept.
