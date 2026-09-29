"""A stand-in for OpenAI's ``codex`` CLI, for the subscription provider's tests.

``exec`` answers in the ``--json`` event stream with whatever ``FAKE_CODEX_ANSWER`` says
(and records its argv, stdin and environment next to ``CODEX_HOME``); ``FAKE_CODEX_FAIL``
makes it report an error instead. ``login --device-auth`` prints a link and a code the way
the real one does, then "is approved" a moment later by writing ``auth.json``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

home = Path(os.environ["CODEX_HOME"])
args = sys.argv[1:]

if args[:1] == ["exec"]:
    prompt = sys.stdin.read()
    (home / "last_call.json").write_text(
        json.dumps({"argv": args, "stdin": prompt, "env": sorted(os.environ)}), encoding="utf-8"
    )
    print(json.dumps({"type": "thread.started", "thread_id": "t1"}))
    print(json.dumps({"type": "turn.started"}))
    fail_file = home / "fail.txt"
    fail = fail_file.read_text(encoding="utf-8") if fail_file.exists() else ""
    if fail:
        print(json.dumps({"type": "error", "message": fail}))
        print(json.dumps({"type": "turn.failed", "error": {"message": fail}}))
        sys.exit(1)
    answer = (
        (home / "answer.txt").read_text(encoding="utf-8")
        if (home / "answer.txt").exists()
        else '{"ok": true}'
    )
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i0", "type": "reasoning", "text": "thinking"},
            }
        )
    )
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i1", "type": "agent_message", "text": answer},
            }
        )
    )
    print(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1200,
                    "cached_input_tokens": 0,
                    "output_tokens": 30,
                    "reasoning_output_tokens": 12,
                },
            }
        )
    )
    sys.exit(0)

if args[:2] == ["login", "--device-auth"]:
    print("\x1b[1mWelcome to Codex\x1b[0m", flush=True)
    print("1. Open this link in your browser: https://auth.openai.com/codex/device", flush=True)
    print("2. Enter this one-time code: ABCD-EFGHI", flush=True)
    time.sleep(0.5)
    (home / "auth.json").write_text('{"tokens": {}}', encoding="utf-8")
    print("Successfully logged in", flush=True)
    sys.exit(0)

print(f"fake codex: unknown command {args}", file=sys.stderr)
sys.exit(2)
