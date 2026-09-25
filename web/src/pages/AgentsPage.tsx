import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { AgentSummary } from "../api/client";
import { useAgents, useInviteToTeam, useMyTeam } from "../api/hooks";
import { AgentAvatar } from "../components/AgentAvatar";
import { Modal } from "../components/Modal";
import { IconPlus, IconUsers } from "../components/icons";
import { ErrorBox, Loading, PageHead, timeAgo } from "../components/ui";
import { currentLang, useT } from "../i18n";

export function AgentsPage() {
  const tx = useT();
  const agents = useAgents();
  const team = useMyTeam();
  const owner = team.data ? !team.data.is_member : false;
  const [inviting, setInviting] = useState(false);
  return (
    <div>
      <PageHead
        title={tx("Agents")}
        subtitle={tx(
          "Each card shows the provider and model the agent runs on right now; open one for its setup, standards and activity.",
        )}
        actions={
          owner ? (
            <button className="btn primary" onClick={() => setInviting(true)}>
              <IconPlus /> {tx("Add someone to the team")}
            </button>
          ) : undefined
        }
      />
      <ErrorBox error={agents.error} />
      {agents.isLoading && <Loading />}
      {agents.data && (
        <div className="grid-3">
          {agents.data.map((a) => (
            <AgentCard key={a.role} agent={a} />
          ))}
        </div>
      )}
      {inviting && agents.data && (
        <InviteModal agents={agents.data} onClose={() => setInviting(false)} />
      )}
    </div>
  );
}

/** One person, several agents, one letter.
 *
 * Which agents is asked here rather than assumed, because an agent is what somebody is
 * put on -- there is no membership of "the team" on its own. Asking for all of them at
 * once is also what keeps it to a single invitation for them to answer.
 */
function InviteModal({ agents, onClose }: { agents: AgentSummary[]; onClose: () => void }) {
  const tx = useT();
  const invite = useInviteToTeam();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState<string[]>([]);

  const toggle = (role: string) =>
    setRoles((on) => (on.includes(role) ? on.filter((r) => r !== role) : [...on, role]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate(
      { email: email.trim(), name: name.trim(), lang: currentLang(), roles },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal title={tx("Add someone to the team")} onClose={onClose}>
      <form onSubmit={submit}>
        <p className="muted small" style={{ marginTop: 0 }}>
          {tx(
            "They approve at the gates of the agents you pick, edit what those agents propose and see this team's projects - nothing else.",
          )}
        </p>
        <div className="field">
          <label htmlFor="invite-email">{tx("Work email")}</label>
          <input
            id="invite-email"
            type="email"
            required
            autoFocus
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="invite-name">{tx("Name (optional)")}</label>
          <input
            id="invite-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label>{tx("Which agents")}</label>
          <div className="pick-agents">
            {agents.map((a) => (
              <label key={a.role} className="pick-agent" data-agent={a.role}>
                <input
                  type="checkbox"
                  checked={roles.includes(a.role)}
                  onChange={() => toggle(a.role)}
                />
                <AgentAvatar role={a.role} className="sm" />
                <span className="truncate">{tx(a.label)}</span>
              </label>
            ))}
          </div>
        </div>
        {invite.error && <ErrorBox error={invite.error} />}
        <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
          <button type="button" className="btn ghost" onClick={onClose}>
            {tx("Cancel")}
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={!email.trim() || roles.length === 0 || invite.isPending}
            title={roles.length === 0 ? tx("Pick at least one agent") : undefined}
          >
            {tx("Send the invitation")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/**
 * One agent, at a glance. The card carries the role's own hue — the same
 * --agent-h/--agent-s the drawn character uses — as a wash behind it and as the border it
 * lifts to, so the set reads as a family and a card is recognised before it is read. What
 * the agent *is* sits at the top, how it is *configured* in the panel below, and how much
 * it has *run* on the footer strip.
 */
function AgentCard({ agent: a }: { agent: AgentSummary }) {
  const tx = useT();
  return (
    <Link
      to={`/agents/${a.role}`}
      className="card pcard acard"
      data-agent={a.role}
      style={{ color: "inherit" }}
    >
      <div className="acard-head">
        <AgentAvatar role={a.role} />
        <div className="acard-who">
          <div className="acard-name">{tx(a.label)}</div>
          <div className="faint tiny mono">{a.role}</div>
        </div>
        {a.permissions.includes("jira") && <span className="badge ok plain">jira</span>}
      </div>

      <div className="acard-scope muted small">{tx(a.scope)}</div>

      <dl className="acard-spec">
        <div>
          <dt>{tx("Model")}</dt>
          <dd
            className="mono truncate"
            title={
              a.assigned_provider
                ? tx("assigned — every project")
                : a.provider
                  ? "pinned in the profile"
                  : "follows Settings → Models"
            }
          >
            {a.effective_model}
            <span className="faint">
              {" "}
              · {a.effective_provider}
              {a.assigned_provider ? ` (${tx("assigned")})` : a.provider ? "" : " (default)"}
            </span>
          </dd>
        </div>
        <div>
          <dt>{tx("Thinking")}</dt>
          <dd>{tx(a.thinking_depth)}</dd>
        </div>
        <div>
          <dt>{tx("Standards")}</dt>
          <dd>{a.standards_domain === "*" ? tx("all domains") : tx(a.standards_domain)}</dd>
        </div>
      </dl>

      <div className="acard-perms">
        {a.permissions.map((p) => (
          <span key={p} className="perm">
            {p}
          </span>
        ))}
      </div>

      {/* Who holds this agent, on the card itself. A page of counts never says that an
          agent can be held by a person at all -- which is the first thing somebody looking
          for where to add one needs to know. */}
      <div className="acard-team">
        <IconUsers />
        {a.holders.length > 0 ? (
          <>
            <span className="acard-faces">
              {a.holders.slice(0, 4).map((who) => (
                <span key={who} className="face" title={who}>
                  {initials(who)}
                </span>
              ))}
            </span>
            <span className="truncate">
              {a.holders.length > 4
                ? tx("{n} person/people", { n: a.holders.length })
                : a.holders.join(", ")}
              {a.mine ? ` · ${tx("yours")}` : ""}
            </span>
          </>
        ) : (
          <span className="faint">{tx("nobody holds it yet")}</span>
        )}
      </div>

      <div className="pcard-foot faint tiny">
        <span>{tx("{n} invocation(s)", { n: a.invocations })}</span>
        <span>
          {a.last_used ? tx("used {ago}", { ago: timeAgo(a.last_used) }) : tx("never used")}
        </span>
      </div>
    </Link>
  );
}

/** Two letters for a face: a name gives its first two words, an address its own start. */
function initials(who: string): string {
  const name = who.includes("@") ? who.split("@")[0]! : who;
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0]![0]! + parts[1]![0]! : name.slice(0, 2);
  return letters.toLocaleUpperCase(currentLang() === "tr" ? "tr-TR" : "en-GB");
}
