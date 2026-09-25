"""The other language for everything the agents wrote.

A project has one language (``Project.language``): the agents write their backlog titles,
plan summaries, phase write-ups and test-case names in it, and that is the language Jira
and the pull request see. The *platform* has its own language, the TR/EN switch in the
corner, and the two need not agree -- a Turkish reader should not have to read an English
backlog because the project was set up in English.

So every people-facing string an agent produced is also kept in the other language. Not by
making each role answer twice -- the big answers already carry whole files and already run
into the output limit -- but by translating the prose once, on the way out, and caching it
by the source text itself. The first time somebody opens a project in the language it was
not written in, the strings it contains are translated in one batched call and stored; from
then on the page is served from the cache and nothing is asked again.

Nothing here can fail a job: it runs on the read path, and a provider that is down means a
page that shows the source text, not an error.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.providers import ModelProvider, ModelRequest, ProviderError
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.schemas.project import LANGUAGE_NAMES

log = logging.getLogger(__name__)

#: The platform speaks two languages; a project is written in one of them.
OTHER_LANGUAGE = {"tr": "en", "en": "tr"}

#: One call carries at most this many strings, so a large backlog does not hit the
#: output limit the way a single unbounded list would.
BATCH = 40

#: Shorter than this and there is nothing to translate (an id, a file name, a number).
MIN_CHARS = 3


class Translated(BaseModel):
    """What the translator answers: the same list, in the same order."""

    model_config = ConfigDict(extra="forbid")

    texts: list[str] = Field(
        description="One translation per input string, in the same order, same length."
    )


# -- which strings a page will show -----------------------------------------------------

# Notes are the engine's own sentences with the role's prose set into them (the web reads
# the sentence back in the platform's language; see web/src/i18n/notes.ts). Only the prose
# is worth translating, so it is lifted out by the same shapes that wrote it.
_PROSE_IN_NOTE: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\w+ phase \d+/\d+(?:, fix attempt \d+|, review fix \d+| part \d+)?: "
        r"(.*) \(\d+ files[^)]*\)$"
    ),
    re.compile(r"^qa: tests written and green \(\d+ files\) — (.*)$"),
    re.compile(r"^.*; supervisor: (?:re-plan|asks you|same specialist fixes) \((.*)\)$"),
    re.compile(r"^supervisor: \w+ \((.*)\)$"),
    re.compile(
        r"^supervisor: recommends \w+ \(confidence [\d.]+, risk \w+\)"
        r"; waits for you: (.*)$"
    ),
)


def prose_in_note(note: str) -> str | None:
    """The part of a history note an agent wrote, if any. A note the engine composed on
    its own (counts, phase numbers, gate results) has nothing to translate."""
    for pattern in _PROSE_IN_NOTE:
        m = pattern.match(note)
        if m:
            return m.group(1).strip() or None
    return None


def _walk_breakdown(node: Any, out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    for key in ("title", "description", "goal", "summary", "name", "message", "fix"):
        value = node.get(key)
        if isinstance(value, str):
            out.append(value)
    for key in ("epics", "stories", "tasks", "phases", "violations", "test_cases", "reasons"):
        for child in node.get(key) or []:
            if isinstance(child, str):
                out.append(child)
            else:
                _walk_breakdown(child, out)


def strings_of(job: Job) -> list[str]:
    """Every people-facing string this development holds, in the order a page meets them.

    Deliberately *not* included: the request and any feedback, which the human typed and
    which no one should see paraphrased; file paths, commands and branch names, which are
    not prose; and the pull-request title and body, which belong to the host in the
    project's own language."""
    out: list[str] = []
    data = job.data
    for blob in (data.backlog, data.plan):
        _walk_breakdown(blob, out)
    if isinstance(data.plan, dict):
        for decision in data.plan.get("decisions") or []:
            if isinstance(decision, str):
                out.append(decision)
    for case in data.test_cases:
        _walk_breakdown(case, out)
    for review in data.reviews:
        _walk_breakdown(review, out)
    if isinstance(data.supervision, dict):
        _walk_breakdown(data.supervision, out)
        for reason in data.supervision.get("reasons") or []:
            if isinstance(reason, str):
                out.append(reason)
    for step in job.history:
        prose = step.note and prose_in_note(step.note)
        if prose:
            out.append(prose)
    return _clean(out)


def _clean(texts: list[str]) -> list[str]:
    """Unique, in first-seen order, and worth a translator's time."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in texts:
        text = (raw or "").strip()
        if len(text) < MIN_CHARS or text in seen:
            continue
        if not any(ch.isalpha() for ch in text):
            continue
        seen.add(text)
        out.append(text)
    return out


# -- the call ---------------------------------------------------------------------------

_SYSTEM = (
    "You translate short product and engineering prose between Turkish and English for a "
    "software delivery tool. Translate meaning, not words. Keep code, identifiers, file "
    "paths, commands, URLs, Jira keys, product names and acronyms exactly as they are. "
    "Keep the register plain and the length close to the original. Respond with a single "
    "JSON object matching the schema and nothing else."
)


def translate(
    texts: list[str],
    *,
    source: str,
    target: str,
    provider: ModelProvider,
    profile: Profile,
    timeout_s: float = 120.0,
) -> dict[str, str]:
    """``{source text: translation}`` for as many strings as came back usable.

    Never raises: whatever could not be translated is simply absent from the result, and
    the caller shows the source text for those."""
    if source == target:
        return {}
    done: dict[str, str] = {}
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        try:
            done.update(
                _one_batch(
                    batch,
                    source=source,
                    target=target,
                    provider=provider,
                    profile=profile,
                    timeout_s=timeout_s,
                )
            )
        except (ProviderError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log.warning("translation batch failed (%s -> %s): %s", source, target, exc)
        except Exception as exc:  # noqa: BLE001 - a read path must never raise
            log.warning("translation batch failed (%s -> %s): %r", source, target, exc)
    return done


def _one_batch(
    batch: list[str],
    *,
    source: str,
    target: str,
    provider: ModelProvider,
    profile: Profile,
    timeout_s: float,
) -> dict[str, str]:
    # the translator borrows the Product Owner's model -- the role whose whole job is
    # writing for people -- but never its thinking budget: this is not a thinking task
    cfg = profile.roles[RoleName.PO]
    request = ModelRequest(
        role=RoleName.PO,
        model=cfg.model,
        provider=cfg.provider,
        thinking_depth=ThinkingDepth.OFF,
        permissions=(),
        system=_SYSTEM,
        prompt=(
            f"Translate each string from {LANGUAGE_NAMES.get(source, source)} to "
            f"{LANGUAGE_NAMES.get(target, target)}.\n"
            "Answer with the same number of strings, in the same order.\n\n"
            + json.dumps({"texts": batch}, ensure_ascii=False, indent=2)
            + "\n\nRespond with one JSON object matching this JSON Schema:\n"
            + json.dumps(Translated.model_json_schema(), indent=2, sort_keys=True)
        ),
        output_schema=Translated.model_json_schema(),
        timeout_s=timeout_s,
    )
    response = provider.complete(request)
    answer = Translated.model_validate_json(_unfenced(response.text))
    if len(answer.texts) != len(batch):
        raise ValueError(f"asked for {len(batch)} strings, got {len(answer.texts)}")
    return {
        src: out.strip()
        for src, out in zip(batch, answer.texts, strict=True)
        if out.strip() and out.strip() != src
    }


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _unfenced(text: str) -> str:
    m = _FENCE.match(text or "")
    return m.group(1) if m else (text or "")


__all__ = [
    "BATCH",
    "OTHER_LANGUAGE",
    "Translated",
    "prose_in_note",
    "strings_of",
    "translate",
]
