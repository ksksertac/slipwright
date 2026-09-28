"""The bots that listen: one thread per account per chat service that has a bot set up.

Three of the four services let the server reach *out* for what people press -- Telegram
by long polling, Slack by Socket Mode, Discord by its gateway -- so they need no public
address and work on a laptop. Teams cannot; it pushes to an HTTP endpoint instead, which
is ``api/notify.py``'s job, and there is nothing to run for it here.

``Listeners.reconcile`` is the only entry point. It is called when the server starts and
whenever somebody saves a bot token, and it makes the running set match what is stored:
a new token starts a bot, a changed one restarts it, a removed one stops it. Each loop
backs off on failure and never takes the server down with it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from slipwright.notify.base import NotifyError
from slipwright.notify.core import Notifier
from slipwright.notify.discord import INTENTS, DiscordAdapter, handle_dispatch
from slipwright.notify.slack import SlackAdapter, handle_envelope
from slipwright.notify.telegram import TelegramAdapter, handle_update

if TYPE_CHECKING:
    from slipwright.engine import Engine

log = logging.getLogger(__name__)

#: The setting whose presence means "this account has a bot on this service".
BOT_SETTING = {
    "telegram": "notify.telegram.token",
    "slack": "notify.slack.app_token",
    "discord": "notify.discord.bot_token",
}

BACKOFF_S = (2, 5, 15, 30, 60)


@dataclass
class _Running:
    fingerprint: str
    stop: threading.Event
    thread: threading.Thread


class Listeners:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = threading.Lock()
        self._running: dict[tuple[str, str], _Running] = {}

    def _wanted(self) -> dict[tuple[str, str], str]:
        """Every (account, service) with a bot, and a fingerprint of its credentials."""
        wanted: dict[tuple[str, str], str] = {}
        store = self.engine.raw_store
        for channel, name in BOT_SETTING.items():
            for owner in store.owners_with_setting(name):
                notifier = Notifier(self.engine, owner or None)
                adapter = notifier.adapter(channel)
                if adapter is None or not adapter.has_bot:
                    continue
                secret = "|".join(sorted(notifier.config(channel).secrets.values()))
                wanted[(owner, channel)] = hashlib.sha256(secret.encode()).hexdigest()
        return wanted

    def reconcile(self) -> list[str]:
        """Start, restart and stop bots until the running set matches the settings."""
        try:
            wanted = self._wanted()
        except Exception:  # noqa: BLE001 - a bad row must not stop the others
            log.exception("chat listeners: could not read the settings")
            return []
        changed: list[str] = []
        with self._lock:
            for key, running in list(self._running.items()):
                if wanted.get(key) != running.fingerprint or not running.thread.is_alive():
                    running.stop.set()
                    del self._running[key]
                    changed.append(f"stopped {key[1]} for {key[0] or 'installation'}")
            for key, fingerprint in wanted.items():
                if key in self._running:
                    continue
                owner, channel = key
                stop = threading.Event()
                thread = threading.Thread(
                    target=_LOOPS[channel],
                    args=(self.engine, owner, stop),
                    name=f"notify-{channel}-{owner or 'installation'}",
                    daemon=True,
                )
                self._running[key] = _Running(fingerprint, stop, thread)
                thread.start()
                changed.append(f"started {channel} for {owner or 'installation'}")
        for line in changed:
            log.info("chat listeners: %s", line)
        return changed

    def stop_all(self) -> None:
        with self._lock:
            for running in self._running.values():
                running.stop.set()
            self._running.clear()

    def running(self) -> list[tuple[str, str]]:
        with self._lock:
            return [k for k, r in self._running.items() if r.thread.is_alive()]


def _forever(name: str, stop: threading.Event, once: Callable[[], None]) -> None:
    """Run ``once`` until stopped, waiting longer after each failure in a row."""
    failures = 0
    while not stop.is_set():
        started = time.monotonic()
        try:
            once()
            failures = 0
        except Exception as exc:  # noqa: BLE001 - a listener outlives every error
            # a connection that lived a while and then dropped is not a failure streak
            if time.monotonic() - started > 300:
                failures = 0
            wait = BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]
            failures += 1
            log.warning("%s: %s; again in %ss", name, exc, wait)
            stop.wait(wait)


# -- telegram --------------------------------------------------------------------------------


def _telegram(engine: Engine, owner: str, stop: threading.Event) -> None:
    offset = {"next": 0}

    def once() -> None:
        notifier = Notifier(engine, owner or None)
        adapter = notifier.adapter("telegram")
        assert isinstance(adapter, TelegramAdapter)
        # a webhook set on the bot (by another tool) makes getUpdates refuse
        adapter.call("deleteWebhook")
        while not stop.is_set():
            for update in adapter.updates(offset["next"]):
                offset["next"] = int(update.get("update_id", 0)) + 1
                try:
                    handle_update(notifier, adapter, update)
                except Exception:  # noqa: BLE001 - one bad update must not loop forever
                    log.exception("telegram: update %s failed", update.get("update_id"))

    _forever(f"telegram bot of {owner or 'installation'}", stop, once)


# -- slack -----------------------------------------------------------------------------------


def _slack(engine: Engine, owner: str, stop: threading.Event) -> None:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    def once() -> None:
        notifier = Notifier(engine, owner or None)
        adapter = notifier.adapter("slack")
        assert isinstance(adapter, SlackAdapter)
        with connect(adapter.socket_url(), open_timeout=15) as ws:
            while not stop.is_set():
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                except ConnectionClosed:
                    return
                envelope = json.loads(raw)
                if envelope.get("type") == "disconnect":
                    return  # Slack asks for a new connection now and then; open one
                envelope_id = envelope.get("envelope_id")
                submitted = (envelope.get("payload") or {}).get("type") == "view_submission"
                # a modal waits for our answer; everything else is acknowledged first so
                # a slow reply never makes Slack deliver it twice
                if envelope_id and not submitted:
                    ws.send(json.dumps({"envelope_id": envelope_id}))
                try:
                    answer = handle_envelope(notifier, adapter, envelope)
                except Exception:  # noqa: BLE001
                    log.exception("slack: envelope failed")
                    answer = None
                if envelope_id and submitted:
                    ack: dict[str, object] = {"envelope_id": envelope_id}
                    if answer:
                        ack["payload"] = answer
                    ws.send(json.dumps(ack))

    _forever(f"slack app of {owner or 'installation'}", stop, once)


# -- discord ---------------------------------------------------------------------------------


def _discord(engine: Engine, owner: str, stop: threading.Event) -> None:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    def once() -> None:
        notifier = Notifier(engine, owner or None)
        adapter = notifier.adapter("discord")
        assert isinstance(adapter, DiscordAdapter)
        with connect(adapter.gateway_url(), open_timeout=15, max_size=2**22) as ws:
            hello = json.loads(ws.recv(timeout=15))
            if hello.get("op") != 10:
                raise NotifyError(f"discord gateway said {hello.get('op')} before hello")
            interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
            seq: int | None = None
            ws.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": adapter.bot_token,
                            "intents": INTENTS,
                            "properties": {
                                "os": "linux",
                                "browser": "slipwright",
                                "device": "slipwright",
                            },
                        },
                    }
                )
            )
            beat_at = time.monotonic() + interval
            while not stop.is_set():
                if time.monotonic() >= beat_at:
                    ws.send(json.dumps({"op": 1, "d": seq}))
                    beat_at = time.monotonic() + interval
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                except ConnectionClosed as exc:
                    raise NotifyError(f"discord gateway closed: {exc}") from exc
                event = json.loads(raw)
                if event.get("s") is not None:
                    seq = int(event["s"])
                op = event.get("op")
                if op == 1:  # the gateway wants a beat now
                    ws.send(json.dumps({"op": 1, "d": seq}))
                elif op in (7, 9):  # reconnect / invalid session: start over
                    return
                elif op == 0:
                    try:
                        handle_dispatch(
                            notifier, adapter, str(event.get("t")), event.get("d") or {}
                        )
                    except Exception:  # noqa: BLE001
                        log.exception("discord: %s failed", event.get("t"))

    _forever(f"discord bot of {owner or 'installation'}", stop, once)


_LOOPS: dict[str, Callable[[Engine, str, threading.Event], None]] = {
    "telegram": _telegram,
    "slack": _slack,
    "discord": _discord,
}


__all__ = ["BOT_SETTING", "Listeners"]
