// Where the agents reach people: Telegram, Slack, Discord and Teams, one tab each.
//
// Every tab has the same three parts, because every service does the same two jobs:
//   - the group: one place the team reads. It is told, never asked -- anybody in the room
//     could press a button there, and a gate is only its owner's and its agent's to decide.
//   - the bot: a conversation with one person, where "carry on / reject, because…" is
//     asked. Only the owner of the account sets these two up.
//   - linking: anybody on the account, member or owner, proves which chat account is
//     theirs by sending the bot a one-time code. That is what makes a press theirs.
import { useState, type ReactNode } from "react";
import { NavLink, useParams } from "react-router-dom";
import {
  describeError,
  type ChannelName,
  type NotifyChannel,
  type NotifyEvent,
  type NotifyLink,
  type NotifyLinkCode,
} from "../../api/client";
import { useLinkCode, useNotify, useSaveNotify, useTestNotify, useUnlink } from "../../api/hooks";
import { ChannelIcon } from "../../components/ChannelIcon";
import { Copyable } from "../../components/Copyable";
import { ErrorBox, Loading, PageHead, timeAgo } from "../../components/ui";
import { useT } from "../../i18n";

const TABS: ChannelName[] = ["telegram", "slack", "discord", "teams"];
const LABEL: Record<ChannelName, string> = {
  telegram: "Telegram",
  slack: "Slack",
  discord: "Discord",
  teams: "Microsoft Teams",
};
const EVENTS: NotifyEvent[] = ["gate", "failed", "done"];

const EVENT_LABEL: Record<NotifyEvent, string> = {
  gate: "An agent is waiting for approval",
  failed: "A development stopped",
  done: "A development finished",
};

/** One text input for a setting. A secret shows whether it is stored, never its value. */
interface Input {
  key: string;
  kind: "field" | "secret";
  label: string;
  placeholder?: string;
  hint?: string;
}

const GROUP_INPUTS: Record<ChannelName, Input[]> = {
  telegram: [
    {
      key: "group_chat_id",
      kind: "field",
      label: "Group id",
      placeholder: "-1001234567890",
      hint: "Add the bot to the group and send /chatid there; it answers with this number.",
    },
  ],
  slack: [
    {
      key: "webhook",
      kind: "secret",
      label: "Incoming webhook URL",
      placeholder: "https://hooks.slack.com/services/…",
    },
  ],
  discord: [
    {
      key: "webhook",
      kind: "secret",
      label: "Channel webhook URL",
      placeholder: "https://discord.com/api/webhooks/…",
    },
  ],
  teams: [
    {
      key: "webhook",
      kind: "secret",
      label: "Workflows webhook URL",
      placeholder: "https://…logic.azure.com/workflows/…",
    },
  ],
};

const BOT_INPUTS: Record<ChannelName, Input[]> = {
  telegram: [{ key: "token", kind: "secret", label: "Bot token", placeholder: "123456:ABC-DEF…" }],
  slack: [
    { key: "bot_token", kind: "secret", label: "Bot token", placeholder: "xoxb-…" },
    { key: "app_token", kind: "secret", label: "App-level token", placeholder: "xapp-…" },
  ],
  discord: [{ key: "bot_token", kind: "secret", label: "Bot token" }],
  teams: [
    {
      key: "app_id",
      kind: "field",
      label: "Microsoft app id",
      placeholder: "00000000-0000-0000-0000-000000000000",
    },
    { key: "app_password", kind: "secret", label: "Client secret" },
    {
      key: "tenant_id",
      kind: "field",
      label: "Tenant id",
      hint: "Only for a single-tenant bot; leave it empty otherwise.",
    },
  ],
};

/** How to get what the group card asks for, step by step. */
const GROUP_STEPS: Record<ChannelName, string[]> = {
  telegram: [
    "Create a bot with @BotFather (/newbot) and paste its token in the bot card below — the group uses the same bot.",
    "Add the bot to your team's group.",
    "Send /chatid in the group and paste the number here.",
  ],
  slack: [
    "At api.slack.com/apps, open your app (or create one) → Incoming Webhooks → turn it on.",
    "Add New Webhook to Workspace, pick the channel, and paste the URL here.",
  ],
  discord: [
    "In the channel's settings: Integrations → Webhooks → New Webhook.",
    "Copy Webhook URL and paste it here.",
  ],
  teams: [
    "In the channel: … → Workflows → “Post to a channel when a webhook request is received”.",
    "Finish the flow and paste the URL it gives you here.",
  ],
};

const BOT_STEPS: Record<ChannelName, string[]> = {
  telegram: [
    "Talk to @BotFather, send /newbot, and paste the token it gives you.",
    "That is all: the bot listens from this server, no public address needed.",
  ],
  slack: [
    "At api.slack.com/apps create an app; under Socket Mode turn it on and create an app-level token with connections:write (xapp-…).",
    "OAuth & Permissions → Bot Token Scopes: chat:write and im:history.",
    "Event Subscriptions → on, and subscribe to the bot event message.im. Interactivity → on.",
    "App Home → allow people to send messages in the Messages tab.",
    "Install the app to the workspace and paste the bot token (xoxb-…).",
  ],
  discord: [
    "At discord.com/developers create an application → Bot → Reset Token, and paste it here.",
    "OAuth2 → URL Generator: scope “bot”; open the URL and add the bot to a server your team is on.",
    "People write to the bot directly; no public address needed.",
  ],
  teams: [
    "In Azure create an Azure Bot; note its Microsoft app id and create a client secret.",
    "Set its messaging endpoint to the address below. It must be reachable from the internet over https.",
    "Channels → add Microsoft Teams, then open the bot in Teams (or install it with an app package).",
  ],
};

/** What a person does with the code, on each service. */
const LINK_STEP: Record<ChannelName, string> = {
  telegram: "Open the bot with the button, or send it: /start {code}",
  slack: "Write to the app in Slack (its Messages tab): link {code}",
  discord: "Send the bot a direct message: {code}",
  teams: "Write to the bot in Teams: link {code}",
};

export function NotificationsPage() {
  const tx = useT();
  const notify = useNotify();
  const { tab = "telegram" } = useParams();
  const current = (TABS as string[]).includes(tab) ? (tab as ChannelName) : "telegram";

  if (notify.isLoading) return <Loading />;
  if (notify.error) return <ErrorBox error={notify.error} />;
  const data = notify.data!;
  const channel = data.channels.find((c) => c.channel === current)!;

  return (
    <div className="settings-flow">
      <PageHead
        title={tx("Notifications")}
        subtitle={tx("Agents reach your team where it already talks.")}
      />
      <p className="muted">
        {tx(
          "A group is told when an agent is waiting, when a development stops and when one finishes. It is told, never asked: anybody in the room could press a button, and a gate is its owner's to decide. Deciding from a chat of your own is Remote control.",
        )}
      </p>

      <nav className="tabs dotted">
        {TABS.map((t) => {
          const c = data.channels.find((x) => x.channel === t)!;
          const state = c.group_ready ? "done" : "optional";
          return (
            <NavLink key={t} to={`/notifications/${t}`} className={t === current ? "active" : ""}>
              <ChannelIcon channel={t} state={state} />
              {LABEL[t]}
            </NavLink>
          );
        })}
      </nav>

      <div className="notify-cards">
        {data.may_configure ? (
          <GroupCard key={`g-${current}`} channel={channel} />
        ) : (
          <p className="muted">
            {tx("The owner of the account sets up where the team is told.")}
          </p>
        )}
      </div>
    </div>
  );
}

function Card({
  title,
  why,
  badge,
  children,
}: {
  title: string;
  why: string;
  badge: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card setup-panel">
      <div className="row spread" style={{ alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        {badge}
      </div>
      <p className="muted small" style={{ margin: "4px 0 14px" }}>
        {why}
      </p>
      {children}
    </section>
  );
}

function Steps({ steps }: { steps: string[] }) {
  const tx = useT();
  return (
    <details className="notify-steps">
      <summary>{tx("How to set it up")}</summary>
      <ol>
        {steps.map((s) => (
          <li key={s}>{tx(s)}</li>
        ))}
      </ol>
    </details>
  );
}

/** The inputs of one card, the save and the test. Only what was typed is sent: an empty
 * secret field keeps what is stored. */
function SettingsForm({
  channel,
  inputs,
  withEvents,
}: {
  channel: NotifyChannel;
  inputs: Input[];
  withEvents?: boolean;
}) {
  const tx = useT();
  const save = useSaveNotify(channel.channel);
  const test = useTestNotify(channel.channel);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [events, setEvents] = useState<NotifyEvent[] | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const chosen = events ?? channel.events;
  const dirty = Object.values(draft).some((v) => v.trim()) || events !== null;

  const submit = (clear: string[] = []) => {
    const fields: Record<string, string> = {};
    const secrets: Record<string, string> = {};
    for (const input of inputs) {
      const value = draft[input.key];
      if (value === undefined) continue;
      if (input.kind === "field") fields[input.key] = value;
      else if (value.trim()) secrets[input.key] = value;
    }
    setSaved(null);
    save.mutate(
      { fields, secrets, clear, ...(events !== null ? { events } : {}) },
      {
        onSuccess: (view) => {
          setDraft({});
          setEvents(null);
          setSaved(view.warning ?? tx("Saved."));
        },
      },
    );
  };

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid-2">
        {inputs.map((input) => {
          const secret = channel.secrets[input.key];
          const id = `${channel.channel}-${input.key}`;
          return (
            <div className="field" key={input.key}>
              <label htmlFor={id}>{tx(input.label)}</label>
              <input
                id={id}
                type={input.kind === "secret" ? "password" : "text"}
                autoComplete="off"
                value={
                  draft[input.key] ??
                  (input.kind === "field" ? (channel.fields[input.key] ?? "") : "")
                }
                onChange={(e) => setDraft({ ...draft, [input.key]: e.target.value })}
                placeholder={
                  input.kind === "secret" && secret?.set
                    ? secret.hint
                      ? tx("set, ends with {hint}", { hint: secret.hint })
                      : tx("set")
                    : input.placeholder
                }
              />
              {input.hint && <div className="muted small">{tx(input.hint)}</div>}
              {input.kind === "secret" && secret?.set && (
                <button
                  type="button"
                  className="btn ghost small notify-clear"
                  onClick={() => submit([input.key])}
                >
                  {tx("Remove")}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {withEvents && (
        <fieldset className="notify-events">
          <legend className="small muted">{tx("Tell the group when")}</legend>
          {EVENTS.map((ev) => (
            <label key={ev} className="check">
              <input
                type="checkbox"
                checked={chosen.includes(ev)}
                onChange={(e) =>
                  setEvents(e.target.checked ? [...chosen, ev] : chosen.filter((x) => x !== ev))
                }
              />
              {tx(EVENT_LABEL[ev])}
            </label>
          ))}
        </fieldset>
      )}
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {saved && <div className="callout notice">{saved}</div>}
      {test.data && (
        <div className="callout notice">
          {tx("Test message sent: {where}", {
            where: test.data.sent
              .map((s) => tx(s === "group" ? "to the group" : "to you"))
              .join(", "),
          })}
        </div>
      )}
      {test.error && <div className="callout error">{describeError(test.error)}</div>}
      <div className="row">
        <button className="btn primary" disabled={!dirty || save.isPending}>
          {save.isPending ? tx("Saving…") : tx("Save")}
        </button>
        <button
          type="button"
          className="btn"
          disabled={test.isPending || !(channel.group_ready || channel.bot_ready)}
          onClick={() => test.mutate()}
        >
          {test.isPending ? tx("Sending…") : tx("Send a test message")}
        </button>
      </div>
    </form>
  );
}

function GroupCard({ channel }: { channel: NotifyChannel }) {
  const tx = useT();
  // Telegram's group is posted to by the bot, so its token lives in the bot card
  const needsBot = channel.channel === "telegram" && !channel.secrets.token?.set;
  return (
    <Card
      title={tx("The team's group")}
      why={tx(
        "Everybody reads it; nobody decides in it. A message says what is waiting and links to it.",
      )}
      badge={
        <span className={`badge ${channel.group_ready ? "ok" : "idle"}`}>
          {channel.group_ready ? tx("ready") : tx("not set up")}
        </span>
      }
    >
      <Steps steps={GROUP_STEPS[channel.channel]} />
      {needsBot && (
        <div className="callout notice small">
          {tx(
            "Telegram posts to the group through the bot: set its token under Remote control first.",
          )}
        </div>
      )}
      <SettingsForm channel={channel} inputs={GROUP_INPUTS[channel.channel]} withEvents />
    </Card>
  );
}

export function BotCard({ channel }: { channel: NotifyChannel }) {
  const tx = useT();
  const live = channel.bot_ready && channel.listening;
  const badge = !channel.bot_ready ? (
    <span className="badge idle">{tx("not set up")}</span>
  ) : live ? (
    <span className="badge ok">{channel.channel === "teams" ? tx("set up") : tx("listening")}</span>
  ) : (
    <span className="badge wait">{tx("connecting…")}</span>
  );
  return (
    <Card
      title={tx("Asking people personally")}
      why={tx(
        "A bot writes to each linked person at the gates that are theirs, with two buttons: carry on, or reject and say why. What they write goes back to the agent.",
      )}
      badge={badge}
    >
      <Steps steps={BOT_STEPS[channel.channel]} />
      {channel.bot_name && (
        <p className="small">
          {tx("The bot:")} <code>@{channel.bot_name}</code>
        </p>
      )}
      {channel.inbound_url && (
        <div className="field">
          <label>{tx("Messaging endpoint")}</label>
          <Copyable text={channel.inbound_url}>
            <code className="notify-endpoint">{channel.inbound_url}</code>
          </Copyable>
          {!channel.inbound_url.startsWith("https://") && (
            <div className="callout error small">
              {tx(
                "Teams needs this server's public https address. Set it as the link base on the Email page.",
              )}
            </div>
          )}
        </div>
      )}
      <SettingsForm channel={channel} inputs={BOT_INPUTS[channel.channel]} />
    </Card>
  );
}

export function LinkCard({
  channel,
  links,
  owner,
}: {
  channel: NotifyChannel;
  links: NotifyLink[];
  owner: boolean;
}) {
  const tx = useT();
  const codes = useLinkCode();
  const unlink = useUnlink();
  const [code, setCode] = useState<NotifyLinkCode | null>(null);
  const mine = links.find((l) => l.mine);
  const others = links.filter((l) => !l.mine);

  return (
    <Card
      title={tx("Your {service} account", { service: LABEL[channel.channel] })}
      why={tx(
        "Link it once and the gates that are yours arrive there too. The code proves the account is yours; a button pressed by anybody else does nothing.",
      )}
      badge={
        <span className={`badge ${mine ? "ok" : "idle"}`}>
          {mine ? tx("linked") : tx("not linked")}
        </span>
      }
    >
      {!channel.bot_ready ? (
        <p className="muted small">
          {owner
            ? tx("Set up the bot above first; then you and your team can link.")
            : tx("The owner of the account has not set up a bot here yet.")}
        </p>
      ) : mine ? (
        <div className="row">
          <span>
            {tx("Linked as")} <strong>{mine.label || mine.username}</strong>{" "}
            <span className="faint small">{timeAgo(mine.linked_at)}</span>
          </span>
          <button
            className="btn ghost small"
            disabled={unlink.isPending}
            onClick={() => unlink.mutate({ channel: channel.channel })}
          >
            {tx("Unlink")}
          </button>
        </div>
      ) : code ? (
        <div className="notify-code">
          <div className="notify-code-value">
            <Copyable text={code.code}>
              <code>{code.code}</code>
            </Copyable>
          </div>
          <p className="small">{tx(LINK_STEP[channel.channel], { code: code.code })}</p>
          <div className="row">
            {channel.channel === "telegram" && code.telegram_url && (
              <a className="btn primary" href={code.telegram_url} target="_blank" rel="noreferrer">
                {tx("Open in Telegram")}
              </a>
            )}
            <span className="faint small">{tx("Works once, for 30 minutes.")}</span>
          </div>
        </div>
      ) : (
        <button
          className="btn primary"
          disabled={codes.isPending}
          onClick={() => codes.mutate(undefined, { onSuccess: setCode })}
        >
          {tx("Get a link code")}
        </button>
      )}
      {codes.error && <div className="callout error">{describeError(codes.error)}</div>}
      {unlink.error && <div className="callout error">{describeError(unlink.error)}</div>}

      {owner && others.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="small muted" style={{ marginBottom: 6 }}>
            {tx("Others on the account who linked {service}", { service: LABEL[channel.channel] })}
          </div>
          <table>
            <tbody>
              {others.map((l) => (
                <tr key={l.user_id}>
                  <td>{l.username}</td>
                  <td className="muted small">{l.label}</td>
                  <td className="faint small">{timeAgo(l.linked_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn ghost small"
                      onClick={() => unlink.mutate({ channel: channel.channel, userId: l.user_id })}
                    >
                      {tx("Unlink")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
