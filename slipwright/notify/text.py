"""What a notification says, in the two languages the interface speaks.

One ``Message`` per event, rendered by each channel in its own way -- Slack blocks, an
Adaptive Card, plain text -- from the same parts: a headline, the lines under it, and
where to open it. Nothing here knows about a chat service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import RoleName

GATE_NAME: dict[str, dict[JobState, str]] = {
    "tr": {
        JobState.AWAITING_BACKLOG_APPROVAL: "backlog",
        JobState.AWAITING_ARCHITECTURE_APPROVAL: "mimari",
        JobState.AWAITING_DESIGN_APPROVAL: "tasarım",
        JobState.AWAITING_REVIEW_APPROVAL: "standart incelemesi",
        JobState.AWAITING_DECISION: "karar",
        JobState.AWAITING_DEPLOY_APPROVAL: "dağıtım",
    },
    "en": {
        JobState.AWAITING_BACKLOG_APPROVAL: "backlog",
        JobState.AWAITING_ARCHITECTURE_APPROVAL: "architecture",
        JobState.AWAITING_DESIGN_APPROVAL: "design",
        JobState.AWAITING_REVIEW_APPROVAL: "standards review",
        JobState.AWAITING_DECISION: "decision",
        JobState.AWAITING_DEPLOY_APPROVAL: "deployment",
    },
}

AGENT_NAME: dict[str, dict[RoleName, str]] = {
    "tr": {
        RoleName.PO: "Ürün Sahibi",
        RoleName.ARCHITECT: "Yazılım Mimarı",
        RoleName.DESIGNER: "Tasarımcı",
        RoleName.QA: "QA",
        RoleName.DEVOPS: "DevOps",
        RoleName.SUPERVISOR: "Denetçi",
    },
    "en": {
        RoleName.PO: "Product Owner",
        RoleName.ARCHITECT: "Architect",
        RoleName.DESIGNER: "Designer",
        RoleName.QA: "QA",
        RoleName.DEVOPS: "DevOps",
        RoleName.SUPERVISOR: "Supervisor",
    },
}

#: The short words that appear on buttons and in the replies to a press.
WORDS: dict[str, dict[str, str]] = {
    "tr": {
        "approve": "✓ Devam",
        "reject": "✗ Reddet",
        "open": "Aç",
        "why": "Neden reddediyorsun? Yazdığın, ajana geri bildirim olarak gider.",
        "why_short": "Neden?",
        "approved_by": "✓ {name} onayladı",
        "rejected_by": "✗ {name} reddetti: {reason}",
        "decided_elsewhere": "Bu kapı artık beklemiyor; karar başka yerde verildi.",
        "not_yours": "Bu soru sana sorulmadı.",
        "not_linked": "Bu hesap Slipwright'a bağlı değil. Bildirimler sayfasındaki kodu gönder.",
        "not_allowed": "Bu kapıda karar verme yetkin yok.",
        "demo": "Bu örnek proje; okumak için orada, çalıştırmak için değil.",
        "failed": "Olmadı: {error}",
        "linked": "Bağlandı: {name}. Onay bekleyen kapılar artık buraya da gelecek.",
        "bad_code": "Bu kod geçersiz ya da süresi dolmuş. Bildirimler sayfasından yenisini al.",
        "hello": (
            "Merhaba! Hesabını bağlamak için Slipwright'ta Bildirimler sayfasındaki kodu "
            "buraya yaz."
        ),
        "chat_id": "Bu sohbetin kimliği: {id}",
        "test": "Slipwright deneme mesajı: bu kanal çalışıyor.",
        "empty_reason": "Reddetmek için bir neden yaz.",
        "retry": "↻ Yeniden dene",
        "retried_by": "↻ {name} yeniden başlattı",
        "moved_on": "Bu geliştirme artık durmuyor; başka yerden yeniden başlatıldı.",
        "owner_only": "Duran bir geliştirmeyi yeniden başlatmak yalnızca sahibinin işi.",
    },
    "en": {
        "approve": "✓ Continue",
        "reject": "✗ Reject",
        "open": "Open",
        "why": "Why are you rejecting it? What you write goes back to the agent as feedback.",
        "why_short": "Why?",
        "approved_by": "✓ Approved by {name}",
        "rejected_by": "✗ Rejected by {name}: {reason}",
        "decided_elsewhere": "This gate is no longer waiting; it was decided elsewhere.",
        "not_yours": "This question was not put to you.",
        "not_linked": "This account is not linked to Slipwright. Send the code from the "
        "Notifications page.",
        "not_allowed": "You may not decide at this gate.",
        "demo": "This is the example project: it is there to read, not to run.",
        "failed": "That did not work: {error}",
        "linked": "Linked: {name}. Gates waiting for you will arrive here too.",
        "bad_code": "That code is unknown or has run out. Get a new one on the Notifications page.",
        "hello": "Hello! To link your account, send the code from Slipwright's "
        "Notifications page here.",
        "chat_id": "This chat's id: {id}",
        "test": "Slipwright test message: this channel works.",
        "empty_reason": "Write a reason to reject.",
        "retry": "↻ Try again",
        "retried_by": "↻ Started again by {name}",
        "moved_on": "This development is no longer stopped; it was started again elsewhere.",
        "owner_only": "Starting a stopped development again is for its owner only.",
    },
}


def word(lang: str, key: str, **kw: Any) -> str:
    table = WORDS.get(lang, WORDS["en"])
    return table[key].format(**kw) if kw else table[key]


@dataclass
class Message:
    """One notification, before any channel has had its say about how it looks."""

    kind: str  # gate | failed | done | test
    headline: str
    lines: list[str] = field(default_factory=list)
    link: str | None = None
    #: a short one-line summary for places that show only one (a push preview, a card title)
    summary: str = ""

    def text(self, *, with_link: bool = True) -> str:
        parts = [self.headline, *self.lines]
        if with_link and self.link:
            parts.append(self.link)
        return "\n".join(p for p in parts if p)


def gate_name(job: Job, lang: str) -> str:
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        if lang == "tr":
            return "test vakaları" if job.data.qa_stage == 1 else "yazılan testler"
        return "test cases" if job.data.qa_stage == 1 else "written tests"
    return GATE_NAME.get(lang, GATE_NAME["en"]).get(job.state, job.state.value)


def agent_name(role: RoleName | None, lang: str) -> str:
    if role is None:
        return "Slipwright"
    return AGENT_NAME.get(lang, AGENT_NAME["en"]).get(role, role.value)


def _clip(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _supervision(job: Job, lang: str) -> list[str]:
    """The supervisor's view, when it has one on this gate: the reason a person opens the
    message at all is often the word "reject" next to a gate."""
    record: dict[str, Any] = job.data.supervision or {}
    if not record.get("decision") or record.get("acted") != "none":
        return []
    decision = str(record["decision"])
    confidence = float(record.get("confidence") or 0)
    risk = str(record.get("risk") or "")
    if lang == "tr":
        said = {"approve": "onay", "reject": "ret"}.get(decision, decision)
        risk_tr = {"low": "düşük", "medium": "orta", "high": "yüksek"}.get(risk, risk)
        out = [f"Denetçi {said} öneriyor · {confidence:.2f} · risk {risk_tr}"]
    else:
        out = [f"Supervisor recommends {decision} · {confidence:.2f} · risk {risk}"]
    out += [f"• {_clip(str(r), 200)}" for r in (record.get("reasons") or [])[:4]]
    return out


def gate_message(
    job: Job, *, role: RoleName | None, project: str, link: str | None, lang: str
) -> Message:
    gate = gate_name(job, lang)
    agent = agent_name(role, lang)
    where = f"{project} · " if project else ""
    if lang == "tr":
        headline = f"⏳ {where}{agent} onay bekliyor: {gate}"
    else:
        headline = f"⏳ {where}{agent} is waiting for approval: {gate}"
    return Message(
        kind="gate",
        headline=headline,
        lines=[f"“{_clip(job.request, 200)}”", *_supervision(job, lang)],
        link=link,
        summary=headline,
    )


def outcome_message(
    job: Job, kind: str, *, project: str, link: str | None, lang: str, error: str | None = None
) -> Message:
    where = f"{project} · " if project else ""
    lines = [f"“{_clip(job.request, 200)}”"]
    if kind == "cancelled":
        # somebody stopped it on purpose: not a failure, and the group is being told
        # rather than asked, because it is already done
        stopped = "geliştirme durduruldu" if lang == "tr" else "development was stopped"
        headline = f"⊘ {where}{stopped}"
        if error:
            lines.append(_clip(error, 200))
    elif kind == "failed":
        headline = f"✗ {where}" + ("geliştirme durdu" if lang == "tr" else "development stopped")
        if error:
            lines.append(_clip(error, 400))
    else:
        headline = f"✓ {where}" + ("geliştirme tamamlandı" if lang == "tr" else "development done")
        if job.data.pr_url:
            lines.append(("Pull request: " if lang == "en" else "Pull request: ") + job.data.pr_url)
    return Message(kind=kind, headline=headline, lines=lines, link=link, summary=headline)


def test_message(lang: str) -> Message:
    text = word(lang, "test")
    return Message(kind="test", headline=text, summary=text)


__all__ = [
    "Message",
    "agent_name",
    "gate_message",
    "gate_name",
    "outcome_message",
    "test_message",
    "word",
]
