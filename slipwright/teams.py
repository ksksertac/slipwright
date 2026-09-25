"""Teams: the people an account puts on its agents.

Whoever signs up owns everything -- the projects, the agents, the keys. A team is built
by handing one agent to one person: *Ayşe is the Architect*. That membership, and nothing
else, is what she may do. She sees the owner's projects and approves at the Architect's
gates; the Product Owner's gates are not hers, and neither are the settings.

Three rules hold the whole thing up:

* **A membership is (owner, agent, person).** Not per project: an agent belongs to the
  account, so whoever holds it holds it everywhere the account works.
* **A gate belongs to exactly one agent.** ``agent_for_gate`` is that map, and it decides
  both who may approve and who may edit what is being approved -- the backlog is the
  Product Owner's, the plan is the Architect's, the test list is QA's.
* **An invited address belongs to the organisation.** The account row is created when the
  invitation is sent, so the address is taken from that moment: the person accepts it by
  setting a password, and cannot instead open an account of their own with it later. The
  address is a company one; this is the property that makes it behave like one.

Leaving is as ordinary as joining. Declining an invitation, walking away from an agent
and being taken off one are the same transition seen from different sides, and the last
one out ends the person's access: their account is marked ``removed``, which is what the
login page tells them rather than pretending the password is wrong.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from slipwright.auth import EmailTokenKind, User, UserStatus, check_password, normalise_email
from slipwright.roles.specialists import LABEL as AGENT_LABEL
from slipwright.schemas.job import Job, JobState, new_job_id, utcnow
from slipwright.schemas.profile import RoleName

if TYPE_CHECKING:  # pragma: no cover - imported for types only, so the store may import us
    from slipwright.mail import MailSettings
    from slipwright.store import JobStore

log = logging.getLogger(__name__)


class MemberStatus(StrEnum):
    INVITED = "invited"  # the letter is out; nobody has answered it
    ACTIVE = "active"  # accepted, and working
    DECLINED = "declined"  # answered with "no"
    LEFT = "left"  # was working, and stepped off the agent
    REMOVED = "removed"  # was working, and the owner took the agent back

    @property
    def over(self) -> bool:
        return self is not MemberStatus.ACTIVE and self is not MemberStatus.INVITED


class Membership(BaseModel):
    """One person on one agent of one account."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    owner_id: str = Field(description="The account whose agent this is.")
    role: RoleName
    user_id: str
    email: str
    name: str = Field(default="", description="The person's display name, for the list.")
    status: MemberStatus = MemberStatus.INVITED
    invited_by: str | None = None
    invited_at: datetime = Field(default_factory=utcnow)
    #: when the invitation was answered, either way
    responded_at: datetime | None = None
    #: when it ended, and how it was worded to whoever reads the list
    ended_at: datetime | None = None

    @property
    def open(self) -> bool:
        """Counts as being on the team: working, or not having answered yet."""
        return not self.status.over


# -- which agent owns which gate ----------------------------------------------------------

#: A waiting state and the agent whose work is waiting there. Approving, rejecting and
#: editing the material all read this one map, so a member can never approve something
#: they may not edit or the other way round.
GATE_AGENT: dict[JobState, RoleName] = {
    JobState.AWAITING_BACKLOG_APPROVAL: RoleName.PO,
    JobState.AWAITING_ARCHITECTURE_APPROVAL: RoleName.ARCHITECT,
    JobState.AWAITING_DESIGN_APPROVAL: RoleName.DESIGNER,
    JobState.AWAITING_REVIEW_APPROVAL: RoleName.QA,
    JobState.AWAITING_TEST_APPROVAL: RoleName.QA,
    JobState.AWAITING_DEPLOY_APPROVAL: RoleName.DEVOPS,
    # a development that stopped itself: the supervisor's own gate
    JobState.AWAITING_DECISION: RoleName.SUPERVISOR,
}


def agent_for_gate(state: JobState) -> RoleName | None:
    """Whose gate this is, or ``None`` when the job is not waiting for anybody."""
    return GATE_AGENT.get(state)


def may_act_at(user: User, job: Job, roles: set[RoleName]) -> bool:
    """Whether this person may approve, reject or edit what ``job`` is waiting on.

    The owner of the account may act at every gate; a member only at their agents'. A job
    that is not at a gate answers ``False`` for a member: there is nothing of theirs to do
    on it, and the actions that move a stopped development are the owner's.
    """
    if not user.is_member:
        return True
    agent = agent_for_gate(job.state)
    return agent is not None and agent in roles


# -- the letters ---------------------------------------------------------------------------


class Letter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    body: str


def _and(lang: str, names: Sequence[str]) -> str:
    """A list as a person would say it: "a, b ve c" -- because the letter is a sentence."""
    items = list(names)
    if len(items) < 2:
        return items[0] if items else ""
    joiner = " ve " if lang == "tr" else " and "
    return joiner.join([", ".join(items[:-1]), items[-1]])


def invite_letter(lang: str, *, link: str, agent: str, inviter: str, name: str) -> Letter:
    if lang == "tr":
        return Letter(
            subject=f"Slipwright: {agent} olarak ekibe davet edildin",
            body=(
                f"Merhaba {name},\n\n"
                f"{inviter} seni Slipwright'ta {agent} ajanına atadı. Kabul edersen bu "
                "ajanın kapılarında onay verir, işini düzenler ve ekibin projelerini "
                "görürsün.\n\n"
                f"{link}\n\n"
                "Bağlantıyı açtığında daveti kabul edip bir şifre belirleyebilir ya da "
                "reddedebilirsin. Bağlantı 7 gün geçerli.\n"
            ),
        )
    return Letter(
        subject=f"Slipwright: you have been invited as the {agent}",
        body=(
            f"Hello {name},\n\n"
            f"{inviter} has put you on the {agent} agent in Slipwright. If you accept, you "
            "approve at that agent's gates, edit its work and see the team's projects.\n\n"
            f"{link}\n\n"
            "The link lets you accept and choose a password, or decline. It is good for "
            "seven days.\n"
        ),
    )


def waiting_letter(
    lang: str, *, link: str, agent: str, gate: str, request: str, project: str, name: str
) -> Letter:
    if lang == "tr":
        return Letter(
            subject=f"Slipwright: {agent} onayın bekleniyor",
            body=(
                f"Merhaba {name},\n\n"
                f"“{request}” geliştirmesi {gate} kapısında seni bekliyor"
                + (f" ({project}).\n\n" if project else ".\n\n")
                + f"{link}\n"
            ),
        )
    return Letter(
        subject=f"Slipwright: the {agent} is waiting for you",
        body=(
            f"Hello {name},\n\n"
            f"“{request}” is waiting at the {gate} gate for your approval"
            + (f" ({project}).\n\n" if project else ".\n\n")
            + f"{link}\n"
        ),
    )


def added_letter(lang: str, *, link: str, agent: str, owner: str, name: str) -> Letter:
    """For somebody who is already on the team and has just been given another agent.

    They accepted this organisation once; asking them to accept it again, with a password
    they already have, would be a form to fill in and nothing else. So the agent is simply
    theirs, and the letter says so.
    """
    if lang == "tr":
        return Letter(
            subject=f"Slipwright: {agent} ajanı da sende",
            body=(
                f"Merhaba {name},\n\n"
                f"{owner} seni {agent} ajanına da ekledi. Bu ajanın kapıları artık sana "
                "geliyor.\n\n"
                f"{link}\n"
            ),
        )
    return Letter(
        subject=f"Slipwright: the {agent} is yours too",
        body=(
            f"Hello {name},\n\n"
            f"{owner} has also put you on the {agent} agent; its gates now come to you.\n\n"
            f"{link}\n"
        ),
    )


def removed_letter(lang: str, *, agent: str, owner: str, name: str) -> Letter:
    if lang == "tr":
        return Letter(
            subject=f"Slipwright: {agent} ajanından çıkarıldın",
            body=(
                f"Merhaba {name},\n\n"
                f"{owner} seni {agent} ajanından çıkardı. Bu ajanın kapılarında artık "
                "onay veremezsin.\n"
            ),
        )
    return Letter(
        subject=f"Slipwright: you are no longer on the {agent}",
        body=(f"Hello {name},\n\n{owner} has taken you off the {agent} agent.\n"),
    )


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class InviteRefused(ValueError):
    """The address cannot be invited onto this agent."""


class Teams:
    """Invitations, acceptance, leaving and being taken off an agent.

    Everything that changes who is on a team goes through here, because each of those
    changes is two writes -- the membership and the account's own standing -- and doing
    one without the other is how somebody ends up locked out while still listed, or
    listed while still able to approve.
    """

    def __init__(self, store: JobStore, mailer: Mailer, settings: MailSettings) -> None:
        self.store = store
        self.mailer = mailer
        self.settings = settings

    # -- inviting -------------------------------------------------------------------------

    def invite(
        self, owner: User, role: RoleName, email: str, *, lang: str = "tr", label: str = ""
    ) -> tuple[Membership, str]:
        """Put an address on one of the owner's agents and mail it the invitation.

        The account row is created here, before anybody has answered, which is what takes
        the address: from now on it can only ever be this team's. Returns the membership
        and the secret in the link, so a caller with no mail server can still hand it over.
        """
        memberships, secret = self.invite_many(owner, [role], email, lang=lang, label=label)
        return memberships[0], secret

    def invite_many(
        self,
        owner: User,
        roles: Sequence[RoleName],
        email: str,
        *,
        lang: str = "tr",
        label: str = "",
    ) -> tuple[list[Membership], str]:
        """The same, for several agents at once, and still one letter.

        Somebody put on three agents is one person being asked one question; sending them
        three letters, each with its own link, would make them answer it three times and
        leave two of the links spent for nothing. So the memberships are made first and the
        letter names them all.
        """
        if not roles:
            raise InviteRefused("choose at least one agent")
        address = normalise_email(email)
        if owner.is_member:
            raise InviteRefused("only the owner of an agent may put somebody on it")
        if owner.email and address == owner.email:
            raise InviteRefused("you already own this agent")
        wanted: list[RoleName] = []
        for role in roles:
            existing = self.store.find_membership(owner.id, role, address)
            if existing is None or not existing.open:
                wanted.append(role)
        if not wanted:
            already = _and(lang, [AGENT_LABEL[role] for role in roles])
            raise InviteRefused(f"{address} is already on {already}")
        user = self.store.find_by_email(address)
        if user is not None and user.tenant_id != owner.id:
            # somebody else's account, or an owner in their own right: an invitation must
            # not quietly move an account between organisations
            raise InviteRefused(f"there is already an account for {address}")
        if user is None:
            user = self.store.create_invited_user(address, owner_id=owner.id, name=label)
        # somebody already working on this team is simply handed the agent; everybody
        # else -- new, or invited back after being taken off -- gets a link to answer
        joining = user.status is not UserStatus.ACTIVE
        memberships = [
            self.store.add_membership(
                Membership(
                    owner_id=owner.id,
                    role=role,
                    user_id=user.id,
                    email=address,
                    name=user.username,
                    status=MemberStatus.INVITED if joining else MemberStatus.ACTIVE,
                    invited_by=owner.id,
                )
            )
            for role in wanted
        ]
        named = _and(lang, [role.value for role in wanted])
        if not joining:
            self._deliver(
                address,
                added_letter(
                    lang,
                    link=self._link("/agents/" + wanted[0].value, None),
                    agent=named,
                    owner=owner.username,
                    name=user.username,
                ),
            )
            return memberships, ""
        if user.status is UserStatus.REMOVED:
            # they were taken off the last of their agents once; the door opens again
            self.store.set_status(user.id, UserStatus.INVITED)
        secret = self.store.issue_email_token(user.id, EmailTokenKind.INVITE, address)
        letter = invite_letter(
            lang,
            link=self._link("/invitation", secret),
            agent=named,
            inviter=owner.username,
            name=user.username,
        )
        self._deliver(address, letter)
        return memberships, secret

    def invitation(self, secret: str) -> tuple[User, list[Membership]] | None:
        """What a link opens onto: who it is for and which agents are waiting.

        Reading it does not spend it -- the page shows the agent and the inviter before
        anybody types a password.
        """
        user = self.store.peek_email_token(secret, EmailTokenKind.INVITE)
        if user is None:
            return None
        pending = [m for m in self.store.memberships_of(user.id) if m.open]
        if not pending:
            return None
        return user, pending

    def accept(self, secret: str, password: str, *, name: str = "") -> User | None:
        """Take the invitation: set a password, prove the address, start working."""
        check_password(password)
        user = self.store.spend_email_token(secret, EmailTokenKind.INVITE)
        if user is None:
            return None
        for membership in self.store.memberships_of(user.id):
            if membership.status is MemberStatus.INVITED:
                self.store.set_membership_status(membership.id, MemberStatus.ACTIVE)
        if name.strip():
            self.store.rename_user(user.id, name.strip())
        self.store.set_password(user.id, password)
        self.store.set_status(user.id, UserStatus.ACTIVE)
        self.store.mark_email_verified(user.id)
        return self.store.get_user(user.id)

    def decline(self, secret: str) -> User | None:
        """Answer "no". The account row stays -- the address was given to the team when
        the letter went out -- but nothing is open and there is no password to log in
        with."""
        user = self.store.spend_email_token(secret, EmailTokenKind.INVITE)
        if user is None:
            return None
        for membership in self.store.memberships_of(user.id):
            if membership.status is MemberStatus.INVITED:
                self.store.set_membership_status(membership.id, MemberStatus.DECLINED)
        return self._settle(user.id)

    # -- ending it ------------------------------------------------------------------------

    def remove(self, membership: Membership, *, by: User, lang: str = "tr") -> Membership:
        """The owner takes an agent back."""
        ended = self.store.set_membership_status(membership.id, MemberStatus.REMOVED)
        user = self._settle(membership.user_id)
        if user is not None and user.email:
            self._deliver(
                user.email,
                removed_letter(
                    lang, agent=membership.role.value, owner=by.username, name=user.username
                ),
            )
        return ended

    def leave(self, membership: Membership) -> Membership:
        """The person steps off an agent themselves."""
        ended = self.store.set_membership_status(membership.id, MemberStatus.LEFT)
        self._settle(membership.user_id)
        return ended

    def _settle(self, user_id: str) -> User | None:
        """Bring the account's standing in line with what is left of its memberships.

        Nobody is deleted: an account with nothing open is marked ``removed``, which drops
        its sessions (so a browser that is open right now is put back on the login page)
        and is what the login page says when they try again. Being invited back turns it
        round again.
        """
        try:
            user = self.store.get_user(user_id)
        except KeyError:
            return None
        if not user.is_member:
            return user
        if any(m.open for m in self.store.memberships_of(user_id)):
            return user
        return self.store.set_status(user_id, UserStatus.REMOVED)

    # -- work arriving ---------------------------------------------------------------------

    def notify_gate(self, job: Job, *, project_name: str = "", lang: str = "tr") -> list[str]:
        """Mail the people whose agent is waiting at this job's gate. Returns who was told.

        Only the members are written to: the owner is looking at their own dashboard, and
        an account that mails itself about its own work is noise. The engine calls this
        once per gate (see ``Job.data.notified``), so a development that stops twice at
        QA's two stages writes two letters and a restart writes none.
        """
        role = agent_for_gate(job.state)
        if role is None or job.owner_id is None:
            return []
        told: list[str] = []
        for membership in self.store.list_members(job.owner_id, role=role):
            if membership.status is not MemberStatus.ACTIVE:
                continue
            letter = waiting_letter(
                lang,
                link=self._link(f"/jobs/{job.id}", None),
                agent=role.value,
                gate=job.state.value.removeprefix("awaiting_").removesuffix("_approval"),
                request=job.request,
                project=project_name,
                name=membership.name or membership.email,
            )
            self._deliver(membership.email, letter)
            told.append(membership.email)
        return told

    # -- helpers ---------------------------------------------------------------------------

    def _link(self, path: str, secret: str | None) -> str:
        root = (self.settings.base_url or "").rstrip("/")
        return f"{root}{path}" + (f"?token={secret}" if secret else "")

    def _deliver(self, to: str, letter: Letter) -> None:
        try:
            self.mailer.send(to, letter.subject, letter.body)
        except Exception as exc:  # noqa: BLE001 - a lost letter must not undo the change
            log.warning("could not deliver to %s: %s", to, exc)


__all__ = [
    "GATE_AGENT",
    "added_letter",
    "InviteRefused",
    "Letter",
    "MemberStatus",
    "Membership",
    "Teams",
    "agent_for_gate",
    "invite_letter",
    "may_act_at",
    "removed_letter",
    "waiting_letter",
]
