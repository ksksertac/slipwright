# Slipwright Agent

A desktop app (macOS, Windows, Linux) that lends this computer to a Slipwright account.
Paired once with a connection code, it takes phases to **write** with the person's own
model -- Claude Code or Codex as installed and signed in, or an Anthropic / OpenAI API key --
and **builds** iOS and Android when the machine can (Xcode, Android SDK + JDK).

It speaks the worker protocol itself, in TypeScript ([docs/machines-protocol.md](../docs/machines-protocol.md)):
plain HTTP to a server on the same network, or sealed end to end through the relay from
anywhere. Nothing of Slipwright's Python is needed on the machine.

## How it is put together

| | |
|---|---|
| `src/main/` | the main process: pairing, the worker loop, the models, git, Jira, secrets |
| `src/main/code.ts` | `SW-` codes, read byte for byte as `slipwright/workers.py` writes them, plus kind 5 (relay) |
| `src/main/crypto.ts`, `parts.ts`, `transport.ts` | the relay: X25519 + HKDF + ChaCha20-Poly1305 in Node's own `crypto`, 512 KiB message parts, one `request()` for LAN and relay alike |
| `src/main/worker.ts` | poll, build, write; `progress` every 15 s, a 409 drops the call |
| `src/main/models/` | Claude Code (`claude -p`, read-only tools), Codex (`codex exec`, read-only sandbox), the two APIs |
| `src/preload/` | the one typed bridge; the page is sandboxed, with no Node in it |
| `src/renderer/` | the window. Every word is in `src/renderer/src/i18n.ts`, keyed by its English text |

Secrets (the worker token, the relay keys, API keys, source and Jira tokens) are sealed with
Electron's `safeStorage` -- the Keychain on macOS, DPAPI on Windows, the keyring on Linux --
into `secrets.bin` under the app's user-data folder. Without a keyring they are kept for the
run only, never written in the clear. Settings and the last 200 handled tasks sit beside it
as JSON.

## Running it

```bash
cd desktop
npm install
npm run dev          # the app with hot reload
npm test             # vitest: codes, crypto vectors, parts, relay, worker loop, parsing
npm run typecheck
npm run lint
npm run build        # into out/
```

If `npm run dev` starts Node instead of a window, `ELECTRON_RUN_AS_NODE` is set in your shell
(some editors set it); unset it.

`npx electron . --screenshot shot.png [--theme light|dark] [--page models] [--demo]` renders
the window once, saves it and quits -- how the UI is checked without a person clicking.
`--demo` fills it with a made-up pairing and two running phases; it never talks to a server.

`test/live.test.ts` pairs with a real server when `SLIPWRIGHT_LIVE_CODE` is set; the comment
in it says how to get one from a local `slipwright serve`.

## Packaging

```bash
npm run dist:win     # NSIS installer in dist/
npm run dist:mac     # .dmg and .zip (on a Mac)
npm run dist:linux   # AppImage and .deb
npx electron-builder --win --dir   # unpacked, to try without installing
```

Icons come from `build/icon.png` (512 px, made from the web app's logo by `npm run icon`);
electron-builder derives the `.ico` and `.icns` from it. Each platform is best built on
itself: the macOS build in particular needs a Mac.

### Signing

- **macOS.** Gatekeeper refuses an app that is not signed and notarized. Both need an Apple
  Developer account (paid): set `CSC_LINK` / `CSC_KEY_PASSWORD` to the Developer ID
  certificate and `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`, then turn
  `notarize` on in `electron-builder.yml`. Unsigned, a person must right-click → Open the
  first time.
- **Windows.** An unsigned installer runs, but SmartScreen warns ("Windows protected your
  PC" → More info → Run anyway) until the file has reputation. A code-signing certificate
  (`CSC_LINK`, `CSC_KEY_PASSWORD`) removes the warning; an EV certificate removes it at once.
- **Linux.** Nothing to sign; the AppImage needs `chmod +x`.

## On a server: slipwright-agent

A server reached over SSH has no window and usually no keyring, so the app's worker also
comes as one file with no window at all: `out/cli/slipwright-agent.cjs`, built by
`npm run build:cli`. It needs Node 20 or newer and nothing else -- no `npm install`, no
Electron, no Python. It does what the app does, and reads what the app keeps behind its
window from **`settings.json` in the folder it is run from**.

```bash
mkdir ~/slipwright && cd ~/slipwright        # upload slipwright-agent.cjs here (SFTP)
node slipwright-agent.cjs init               # writes settings.json to fill in
# put the code from Slipwright (Settings → Machines → Connect a machine) in "code",
# choose each agent's model; upload the file again whenever you like
node slipwright-agent.cjs check              # models found, agents, tokens, pairing
node slipwright-agent.cjs                    # pairs the first time, then takes work
```

`settings.json`:

```json
{
  "code": "SW-…",
  "name": "build-server-1",
  "max_concurrent": 1,
  "work_dir": "./work",
  "run_builds": true,
  "agents": {
    "backend": { "enabled": true, "model": "claude-code:sonnet" },
    "web":     { "enabled": true, "model": "codex" },
    "mobile":  { "enabled": false },
    "devops":  { "enabled": false }
  },
  "keys":   { "anthropic": "env:ANTHROPIC_API_KEY", "openai": "" },
  "source": { "github_token": "env:GITHUB_TOKEN", "bitbucket_user": "", "bitbucket_app_password": "" },
  "jira":   { "site": "acme.atlassian.net", "email": "you@acme.com", "token": "env:JIRA_TOKEN" }
}
```

- A model is `claude-code`, `codex`, `anthropic` or `openai`, optionally `:<model>`. Claude
  Code and Codex must be installed and signed in on the server (`claude`, `codex login`).
- Any secret may be `"env:NAME"`, read from the environment, so it can live in a systemd
  unit rather than the file. A file holding keys should be `chmod 600`; the program warns
  when others can read it.
- The pairing is kept in **`slipwright-agent.state.json`** beside it, readable by its owner
  only, so uploading a new `settings.json` never unpairs the machine. The code is used once;
  delete the state file to pair again.
- `settings.json` is read again within seconds of changing: switch an agent off or change
  its model without a restart. A file that does not parse is reported and the last good
  one is kept.
- Stopping it (Ctrl+C, `systemctl stop`) hands back what it holds; the server writes that
  phase itself.
- The app writes this file for you: **Ayarlar → Sunucuda çalıştır → settings.json olarak
  kaydet**, with or without the keys.

To keep it running, a systemd unit (`/etc/systemd/system/slipwright-agent.service`):

```ini
[Unit]
Description=Slipwright Agent
After=network-online.target

[Service]
User=slipwright
WorkingDirectory=/home/slipwright/slipwright
ExecStart=/usr/bin/node /home/slipwright/slipwright/slipwright-agent.cjs
Environment=ANTHROPIC_API_KEY=sk-ant-…
Restart=always

[Install]
WantedBy=multi-user.target
```

Run it as a user of its own: the build commands it runs are written by a model.

## What it does with a phase

1. Polls with what it can be given: `ios` / `android` when found (and builds are on), and
   `write:<domain>` for every agent switched on that has a model it can run.
2. A **call**: moves the Jira issue to *In Progress* under the person's own account (if Jira
   is set), shallow-fetches the commit into a cache when a source token is set and copies its
   tree into a throwaway folder, runs the agent's model there read-only, and posts its text
   back exactly as it came. The server parses and validates it; a wrong answer is a retry,
   never a wrong file. Cancelled, timed out or refused, the whole process tree is ended.
3. A **build**: downloads the snapshot, unpacks it (files and folders only) into a fresh
   folder, runs the commands with an allow-listed environment (`gates/env.py`'s list) and
   posts the result, with a heartbeat every 20 s.

The token for git rides in `http.extraheader` through `GIT_CONFIG_*` variables: never in the
URL, a config file or the command line.
