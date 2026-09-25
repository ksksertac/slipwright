import { useState, type FormEvent } from "react";
import { describeError, type AgentSummary, type Membership } from "../api/client";
import { useAgentMembers, useEndMembership, useInviteToAgent, useMyTeam } from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { Empty, ErrorBox, Loading, formatTime } from "../components/ui";
import { currentLang, useT } from "../i18n";

/** The people on one agent.
 *
 * An agent is a job, and this is who holds it. The owner invites an address, sees who has
 * answered and can take the agent back; whoever holds it sees the same list and can step
 * off it. Nothing here is per project: the agent belongs to the account, so its gates come
 * to these people wherever the account works.
 */
export function AgentTeamTab({ agent }: { agent: AgentSummary }) {
  const tx = useT();
  const { user } = useAuth();
  const team = useMyTeam();
  const owner = !team.data?.is_member;
  const members = useAgentMembers(agent.role);
  const invite = useInviteToAgent(agent.role);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate(
      { email: email.trim(), name: name.trim(), lang: currentLang() },
      {
        onSuccess: () => {
          setEmail("");
          setName("");
        },
      },
    );
  };

  if (members.isLoading) return <Loading />;
  if (members.error) return <ErrorBox error={members.error} />;
  const rows = members.data ?? [];
  const open = rows.filter((m) => m.status === "active" || m.status === "invited");
  const past = rows.filter((m) => !open.includes(m));

  return (
    <div>
      <p className="muted small" style={{ marginTop: 0 }}>
        {tx(
          "Whoever is on this agent approves at its gates, edits what it proposes and sees this team's projects — and nothing else. Work that arrives here is mailed to them.",
        )}
      </p>

      {open.length === 0 ? (
        <Empty>{tx("Nobody but you holds this agent.")}</Empty>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>{tx("Person")}</th>
                <th>{tx("State")}</th>
                <th>{tx("Since")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {open.map((m) => (
                <MemberRow
                  key={m.id}
                  member={m}
                  role={agent.role}
                  canEnd={owner || m.user_id === user?.id}
                  itsMe={m.user_id === user?.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {owner && (
        <form className="form card" onSubmit={submit} style={{ marginTop: 16 }}>
          <h3>{tx("Put somebody on this agent")}</h3>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="member-email">{tx("Work email")}</label>
              <input
                id="member-email"
                type="email"
                autoComplete="off"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="member-name">{tx("Name (optional)")}</label>
              <input
                id="member-name"
                type="text"
                autoComplete="off"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </div>
          <p className="faint small" style={{ marginTop: 0 }}>
            {tx(
              "They get a letter with a link: they accept it by choosing a password, or decline. The address becomes part of this team and cannot open an account of its own afterwards.",
            )}
          </p>
          {invite.error && <div className="callout error">{describeError(invite.error)}</div>}
          <button className="btn primary" disabled={!email.trim() || invite.isPending}>
            {invite.isPending ? tx("Sending…") : tx("Send the invitation")}
          </button>
        </form>
      )}

      {past.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <h3 className="faint small">{tx("No longer on this agent")}</h3>
          <div className="card" style={{ padding: 0 }}>
            <table>
              <tbody>
                {past.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.name || m.email} <span className="faint tiny">{m.email}</span>
                    </td>
                    <td className="muted small">{tx(m.status)}</td>
                    <td className="faint tiny">{m.ended_at ? formatTime(m.ended_at) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function MemberRow({
  member,
  role,
  canEnd,
  itsMe,
}: {
  member: Membership;
  role: string;
  canEnd: boolean;
  itsMe: boolean;
}) {
  const tx = useT();
  const end = useEndMembership(role);
  const [confirming, setConfirming] = useState(false);
  return (
    <tr>
      <td>
        <div>{member.name || member.email}</div>
        <div className="faint tiny">{member.email}</div>
      </td>
      <td>
        <span className={`badge plain ${member.status === "active" ? "ok" : "idle"}`}>
          {tx(member.status)}
        </span>
      </td>
      <td className="faint tiny">{formatTime(member.invited_at)}</td>
      <td style={{ textAlign: "right" }}>
        {end.error && <span className="error small">{describeError(end.error)}</span>}
        {canEnd &&
          (confirming ? (
            <span className="row" style={{ justifyContent: "flex-end" }}>
              <button
                className="btn bad small"
                disabled={end.isPending}
                onClick={() => end.mutate(member.id)}
              >
                {itsMe ? tx("Step off this agent") : tx("Take the agent back")}
              </button>
              <button className="btn small" onClick={() => setConfirming(false)}>
                {tx("Cancel")}
              </button>
            </span>
          ) : (
            <button className="btn small" onClick={() => setConfirming(true)}>
              {itsMe ? tx("Leave…") : tx("Remove…")}
            </button>
          ))}
      </td>
    </tr>
  );
}
