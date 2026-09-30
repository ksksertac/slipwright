"""Running the agents on a ChatGPT plan, through OpenAI's own Codex CLI.

A fake ``codex`` (tests/fake_codex.py) stands in for the real one: it answers ``exec`` in
the ``--json`` event stream and "approves" ``login --device-auth`` a moment after printing
its code.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.config import Settings
from slipwright.engine import Engine
from slipwright.providers import ModelRequest, ProviderRejectedError, ProviderTimeoutError
from slipwright.providers.codex import CodexProvider, Logins, read_answer
from slipwright.providers.registry import CHATGPT
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

FAKE = [sys.executable, str(Path(__file__).with_name("fake_codex.py"))]


def _request(**kw: object) -> ModelRequest:
    base: dict[str, object] = {
        "role": RoleName.ARCHITECT,
        "model": "gpt-6-sol",
        "thinking_depth": ThinkingDepth.HIGH,
        "system": "You are the Architect.",
        "prompt": "Plan it. Answer as JSON.",
        "output_schema": {"type": "object"},
        "timeout_s": 60,
    }
    base.update(kw)
    return ModelRequest(**base)  # type: ignore[arg-type]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "codex" / "u1"
    path.mkdir(parents=True)
    return path


def _signed_in(home: Path) -> Path:
    (home / "auth.json").write_text("{}", encoding="utf-8")
    return home


# -- the provider ---------------------------------------------------------------------------


def test_an_answer_comes_from_codex_exec_with_its_tokens(home: Path) -> None:
    (_signed_in(home) / "answer.txt").write_text('{"summary": "done"}', encoding="utf-8")
    response = CodexProvider(home, command=FAKE).complete(_request())

    assert response.text == '{"summary": "done"}'
    assert (response.input_tokens, response.output_tokens) == (1200, 42)
    call = json.loads((home / "last_call.json").read_text(encoding="utf-8"))
    assert call["argv"][:2] == ["exec", "--json"]
    assert call["argv"][call["argv"].index("-m") : call["argv"].index("-m") + 2] == [
        "-m",
        "gpt-6-sol",
    ]
    assert 'model_reasoning_effort="high"' in call["argv"]
    assert call["argv"][-1] == "-"  # the prompt came on stdin, not the command line
    assert "You are the Architect." in call["stdin"] and "Plan it." in call["stdin"]


def test_codex_sees_its_own_home_and_none_of_the_servers_secrets(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    monkeypatch.setenv("SLIPWRIGHT_SECRET_KEY", "must-not-leak-either")
    CodexProvider(_signed_in(home), command=FAKE).complete(_request())
    env = json.loads((home / "last_call.json").read_text(encoding="utf-8"))["env"]
    assert "CODEX_HOME" in env
    assert "OPENAI_API_KEY" not in env and "SLIPWRIGHT_SECRET_KEY" not in env


def test_the_default_model_is_whatever_the_plan_gives_codex(home: Path) -> None:
    CodexProvider(_signed_in(home), command=FAKE).complete(_request(model="default"))
    argv = json.loads((home / "last_call.json").read_text(encoding="utf-8"))["argv"]
    assert "-m" not in argv


def test_not_signed_in_and_a_spent_plan_end_the_step_at_once(home: Path) -> None:
    provider = CodexProvider(home, command=FAKE)
    with pytest.raises(ProviderRejectedError, match="not signed in"):
        provider.complete(_request())

    _signed_in(home)
    (home / "fail.txt").write_text("You've hit your usage limit.", encoding="utf-8")
    with pytest.raises(ProviderRejectedError, match="usage limit"):
        provider.complete(_request())


def test_a_call_that_times_out_leaves_nothing_of_codex_running(home: Path) -> None:
    """``codex`` is a Node wrapper around a native binary. The timeout killed the wrapper
    and the binary was left behind, working on the person's plan for an answer nobody
    would read -- one more every time a call timed out, and stopping the development did
    not reach them."""
    (_signed_in(home) / "hang.txt").write_text("1", encoding="utf-8")
    beat = home / "beat"
    with pytest.raises(ProviderTimeoutError):
        CodexProvider(home, command=FAKE).complete(_request(timeout_s=3))
    assert beat.exists(), "the child had started before the call was given up on"

    time.sleep(0.5)  # whatever was mid-write lands
    before = beat.stat().st_size
    time.sleep(1.0)
    assert beat.stat().st_size == before, "the child is still working"


def test_only_the_agents_last_message_is_the_answer() -> None:
    stream = "\n".join(
        json.dumps(e)
        for e in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "draft"}},
            {"type": "item.completed", "item": {"type": "command_execution", "text": "ls"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "final"}},
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}},
        )
    )
    assert read_answer("noise\n" + stream) == ("final", 5, 2, None)


# -- signing in -----------------------------------------------------------------------------


def test_signing_in_shows_the_link_and_the_code_and_then_holds(home: Path) -> None:
    logins = Logins(command=FAKE)
    login = logins.start(home)
    assert login.url == "https://auth.openai.com/codex/device"
    assert login.code == "ABCD-EFGHI"

    deadline = time.monotonic() + 10
    while logins.status(home) != "signed_in" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert logins.status(home) == "signed_in"

    logins.sign_out(home)
    assert logins.status(home) == "signed_out"


# -- where it is offered --------------------------------------------------------------------


def test_it_is_on_for_a_local_install_and_off_for_a_hosted_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLIPWRIGHT_RUNNER", raising=False)
    assert Settings.from_env({}).chatgpt_enabled is True
    assert (
        Settings.from_env({"SLIPWRIGHT_DATABASE_URL": "postgresql://x/y"}).chatgpt_enabled is False
    )
    monkeypatch.setenv("SLIPWRIGHT_RUNNER", "docker")
    assert Settings.from_env({}).chatgpt_enabled is False
    forced = Settings.from_env({"SLIPWRIGHT_CHATGPT_SUBSCRIPTION": "1"})
    assert forced.chatgpt_enabled is True


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(store, Workspace(worktrees_root, PortAllocator(8960, 8999)), seed_profile=seed)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_a_hosted_installation_does_not_offer_it_at_all(client: TestClient) -> None:
    names = [p["name"] for p in client.get("/api/settings/providers").json()]
    assert CHATGPT not in names
    assert client.post("/api/settings/providers/chatgpt/login").status_code == 404


def test_signed_in_it_is_a_provider_an_agent_can_run_on(
    engine: Engine, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIPWRIGHT_CODEX_BIN", " ".join(f'"{p}"' for p in FAKE))
    engine.codex_root = tmp_path / "codex"
    engine.codex_logins = Logins(command=FAKE)

    row = next(p for p in client.get("/api/settings/providers").json() if p["name"] == CHATGPT)
    assert (row["kind"], row["key_set"]) == ("subscription", False)

    started = client.post("/api/settings/providers/chatgpt/login").json()
    assert started["code"] == "ABCD-EFGHI" and started["status"] == "waiting"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if client.get("/api/settings/providers/chatgpt/login").json()["status"] == "signed_in":
            break
        time.sleep(0.1)
    row = next(p for p in client.get("/api/settings/providers").json() if p["name"] == CHATGPT)
    assert (row["key_set"], row["key_hint"]) == (True, "ChatGPT")

    engine.assign_agent(RoleName.ARCHITECT, CHATGPT, "default")
    response = engine.provider.complete(_request(model="whatever-the-profile-says"))
    assert response.text == '{"ok": true}'
    assert response.provider == CHATGPT


def test_the_sign_in_card_keeps_watching_while_you_approve_elsewhere() -> None:
    """Approving is done on OpenAI's site, so the answer this card waits for changes
    while the person is looking at another tab. The app refetches nothing on window
    focus, and a paused interval plus no focus refetch is a card that says "waiting for
    you to approve it" long after the approval landed -- a reload was the only way out.
    It also has to watch until it is signed in rather than only while the server says
    "waiting", or one answer of any other kind stops the polling for good.
    """
    hooks = (Path(__file__).resolve().parent.parent / "web" / "src" / "api" / "hooks.ts").read_text(
        encoding="utf-8"
    )
    login = hooks[hooks.index("export function useChatGPTLogin") :][:1200]
    assert "refetchIntervalInBackground: true" in login
    assert '(q) => (q.state.data?.status === "signed_in" ? false : 3000)' in login
