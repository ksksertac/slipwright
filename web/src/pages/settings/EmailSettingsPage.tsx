// How mail leaves this installation, and where the support page writes. Admin-only: one
// sender serves everybody, unlike the model keys and Git tokens each account brings.
//
// Four tabs, in the order somebody sets them up: the sender (SMTP), where support requests
// land, what has actually come in, and the letters that never left. Each tab carries a dot
// for its state, so what is still missing shows without opening it.
import { useState, type FormEvent, type ReactNode } from "react";
import { NavLink, useParams } from "react-router-dom";
import { describeError, type MailSettings, type SupportRequest } from "../../api/client";
import {
  useAllSupportRequests,
  useMailOutbox,
  useMailSettings,
  useSaveMailSettings,
  useSetSupportStatus,
  useTestMailSettings,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { IconCheck, IconLifebuoy } from "../../components/icons";
import { Empty, ErrorBox, Loading, PageHead, formatTime } from "../../components/ui";
import { useLang, useT } from "../../i18n";

const TABS = ["sending", "support", "inbox", "outbox"] as const;
type Tab = (typeof TABS)[number];

/** "done" is settled, "todo" still wants a decision, "optional" is fine left alone. */
type StepState = "done" | "todo" | "optional";

/** The one tab on screen: its full title, the line saying what it is for, and its state. */
function Panel({
  title,
  why,
  state,
  stateText,
  children,
}: {
  title: string;
  why: string;
  state: StepState;
  stateText: string;
  children: ReactNode;
}) {
  const badge = state === "done" ? "ok" : state === "todo" ? "wait" : "idle";
  return (
    <section className="card setup-panel">
      <div className="row spread" style={{ alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span className={`badge ${badge}`}>{stateText}</span>
      </div>
      <p className="muted small" style={{ margin: "4px 0 14px" }}>
        {why}
      </p>
      {children}
    </section>
  );
}

export function EmailSettingsPage() {
  const tx = useT();
  const { user } = useAuth();
  const admin = !!user?.is_admin;
  const mail = useMailSettings(admin);
  const requests = useAllSupportRequests(admin);
  const outbox = useMailOutbox(admin);
  const { tab = "sending" } = useParams();
  const current: Tab = (TABS as readonly string[]).includes(tab) ? (tab as Tab) : "sending";

  if (!admin) return <div className="callout error">{tx("Admins only.")}</div>;
  if (mail.isLoading) return <Loading />;
  if (mail.error) return <ErrorBox error={mail.error} />;
  const s = mail.data!;

  const open = (requests.data ?? []).filter((r) => r.status === "open").length;
  const waiting = outbox.data?.length ?? 0;

  // The dots, so an unfinished tab says so from the tab strip.
  const state: Record<Tab, StepState> = {
    sending: s.configured ? "done" : "todo",
    support: (s.support_recipients ?? []).length > 0 ? "done" : "todo",
    inbox: open > 0 ? "todo" : "optional",
    outbox: waiting > 0 ? "todo" : "optional",
  };
  const label: Record<Tab, string> = {
    sending: tx("Sending"),
    support: tx("Support address"),
    inbox: tx("Requests"),
    outbox: tx("The outbox"),
  };
  // A count on the tab beats a number nobody sees until they open it.
  const count: Partial<Record<Tab, number>> = { inbox: open, outbox: waiting };

  return (
    <div className="settings-flow">
      <PageHead
        title={tx("Email")}
        subtitle={tx("The sender every letter goes out from, and where support requests land.")}
      />

      <nav className="tabs dotted">
        {TABS.map((t) => (
          <NavLink key={t} to={`/settings/email/${t}`} className={t === current ? "active" : ""}>
            <span className={`tab-dot ${state[t]}`} />
            {label[t]}
            {(count[t] ?? 0) > 0 && <span className="count">{count[t]}</span>}
          </NavLink>
        ))}
      </nav>

      {current === "sending" && (
        <Panel
          title={tx("How letters leave")}
          why={tx(
            "The mail server every letter goes out from: verification links, password resets and support requests alike.",
          )}
          state={state.sending}
          stateText={s.configured ? tx("letters go out over SMTP") : tx("nothing is sent yet")}
        >
          <SenderForm settings={s} />
        </Panel>
      )}

      {current === "support" && (
        <Panel
          title={tx("Where support requests land")}
          why={tx(
            "The inbox that receives what people write on the support page. Left empty, it falls back to the administrators.",
          )}
          state={state.support}
          stateText={
            (s.support_recipients ?? []).length > 0
              ? tx("someone gets them")
              : tx("nobody gets them")
          }
        >
          <SupportForm settings={s} />
        </Panel>
      )}

      {current === "inbox" && (
        <Panel
          title={tx("What people have written")}
          why={tx(
            "Every request, kept here whatever the mail server did, so an unanswered question is never only an email.",
          )}
          state={state.inbox}
          stateText={open > 0 ? tx("{n} waiting", { n: open }) : tx("nothing waiting")}
        >
          <SupportInbox />
        </Panel>
      )}

      {current === "outbox" && (
        <Panel
          title={tx("The outbox")}
          why={tx(
            "Letters written but never sent, verification links included. An installation with no mail server keeps them here.",
          )}
          state={state.outbox}
          stateText={waiting > 0 ? tx("{n} waiting", { n: waiting }) : tx("empty")}
        >
          <OutboxList />
        </Panel>
      )}
    </div>
  );
}

// -- the sender -------------------------------------------------------------------------

function SenderForm({ settings }: { settings: MailSettings }) {
  const tx = useT();
  const { lang } = useLang();
  const save = useSaveMailSettings();
  const test = useTestMailSettings();
  const { user } = useAuth();

  const [transport, setTransport] = useState(settings.transport);
  const [host, setHost] = useState(settings.host ?? "");
  const [port, setPort] = useState(String(settings.port ?? 587));
  const [security, setSecurity] = useState(settings.security ?? "starttls");
  const [username, setUsername] = useState(settings.username ?? "");
  const [password, setPassword] = useState("");
  const [fromAddress, setFromAddress] = useState(settings.from_address ?? "");
  const [fromName, setFromName] = useState(settings.from_name ?? "Slipwright");
  const [baseUrl, setBaseUrl] = useState(settings.base_url ?? "");
  const [testTo, setTestTo] = useState(user?.email ?? "");
  const [saved, setSaved] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      {
        transport,
        host: host.trim(),
        port: Number(port) || 587,
        security,
        username: username.trim(),
        password: password.trim() || null,
        from_address: fromAddress.trim(),
        from_name: fromName.trim(),
        base_url: baseUrl.trim(),
      },
      {
        onSuccess: () => {
          setPassword("");
          setSaved(true);
        },
      },
    );
  };

  return (
    <form className="stack" onSubmit={submit}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {tx(
          "Until a mail server is set here, verification links, password resets and support requests are written to the outbox instead of being sent. Nothing is lost either way.",
        )}
      </p>

      <div className="grid-2">
        <div className="field">
          <label htmlFor="mail-transport">{tx("Transport")}</label>
          <select
            id="mail-transport"
            value={transport}
            onChange={(e) => setTransport(e.target.value as MailSettings["transport"])}
          >
            <option value="smtp">{tx("SMTP server")}</option>
            <option value="outbox">{tx("Outbox only (send nothing)")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="mail-security">{tx("Security")}</label>
          <select
            id="mail-security"
            value={security}
            onChange={(e) => setSecurity(e.target.value as MailSettings["security"])}
          >
            <option value="starttls">{tx("STARTTLS (usually port 587)")}</option>
            <option value="ssl">{tx("SSL/TLS (usually port 465)")}</option>
            <option value="none">{tx("None (port 25)")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="mail-host">{tx("Server")}</label>
          <input
            id="mail-host"
            type="text"
            className="mono"
            value={host}
            placeholder="smtp.example.com"
            onChange={(e) => setHost(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="mail-port">{tx("Port")}</label>
          <input
            id="mail-port"
            type="number"
            min={1}
            max={65535}
            className="mono"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="mail-username">{tx("Username")}</label>
          <input
            id="mail-username"
            type="text"
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <div className="muted small">{tx("Leave empty for a server that needs no login.")}</div>
        </div>
        <div className="field">
          <label htmlFor="mail-password">{tx("Password")}</label>
          <input
            id="mail-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={
              settings.password_set
                ? tx("set, ends with {hint}", { hint: settings.password_hint ?? "" })
                : tx("paste a password")
            }
          />
          <div className="muted small">
            {tx("Stored encrypted and never shown again. Empty keeps the stored one.")}
          </div>
        </div>
        <div className="field">
          <label htmlFor="mail-from">{tx("Sender address")}</label>
          <input
            id="mail-from"
            type="email"
            className="mono"
            value={fromAddress}
            placeholder="no-reply@example.com"
            onChange={(e) => setFromAddress(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="mail-from-name">{tx("Sender name")}</label>
          <input
            id="mail-from-name"
            type="text"
            value={fromName}
            onChange={(e) => setFromName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="mail-base-url">{tx("Address of this installation")}</label>
          <input
            id="mail-base-url"
            type="url"
            className="mono"
            value={baseUrl}
            placeholder="https://slipwright.example.com"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <div className="muted small">
            {tx("What the links in the letters point at — verification and password resets.")}
          </div>
        </div>
      </div>

      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {saved && <div className="callout notice">{tx("Saved.")}</div>}

      <div className="row">
        <button className="btn primary small" disabled={save.isPending}>
          {tx("Save")}
        </button>
        {settings.password_set && (
          <button
            type="button"
            className="btn bad small"
            onClick={() => save.mutate({ clear_password: true })}
          >
            {tx("Forget the password")}
          </button>
        )}
      </div>

      <div className="row" style={{ alignItems: "flex-end", gap: 8 }}>
        <div className="field" style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor="mail-test-to">{tx("Send a test message to")}</label>
          <input
            id="mail-test-to"
            type="email"
            className="mono"
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn small"
          disabled={!testTo.trim() || test.isPending}
          onClick={() => test.mutate({ to: testTo.trim(), lang })}
        >
          {test.isPending ? tx("Sending…") : tx("Send a test message")}
        </button>
      </div>
      {test.data && (
        <div className="callout notice">
          {test.data.transport === "smtp"
            ? tx("Sent to {email}. If it arrives, the settings are right.", {
                email: test.data.sent_to,
              })
            : tx("Written to the outbox for {email}: no mail server is configured yet.", {
                email: test.data.sent_to,
              })}
        </div>
      )}
      {test.error && <div className="callout error">{describeError(test.error)}</div>}
    </form>
  );
}

// -- where support requests go ------------------------------------------------------------

function SupportForm({ settings }: { settings: MailSettings }) {
  const tx = useT();
  const save = useSaveMailSettings();
  const [supportEmail, setSupportEmail] = useState(settings.support_email ?? "");
  const [saved, setSaved] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate({ support_email: supportEmail.trim() }, { onSuccess: () => setSaved(true) });
  };

  const reaches = settings.support_recipients ?? [];

  return (
    <form className="stack" onSubmit={submit}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {tx("Several addresses may be given, separated by commas.")}
      </p>
      <div className="field">
        <label htmlFor="mail-support">{tx("Support address")}</label>
        <input
          id="mail-support"
          type="text"
          className="mono"
          value={supportEmail}
          placeholder={tx("support@example.com")}
          onChange={(e) => setSupportEmail(e.target.value)}
        />
      </div>
      <div className="callout notice">
        {reaches.length > 0 ? (
          <>
            {tx("As things stand a request reaches:")} <strong>{reaches.join(", ")}</strong>
          </>
        ) : (
          tx(
            "A request would reach nobody: no support address is set and no administrator has a confirmed address. Requests are still kept, under Requests.",
          )
        )}
      </div>
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {saved && <div className="callout notice">{tx("Saved.")}</div>}
      <div className="row">
        <button className="btn primary small" disabled={save.isPending}>
          {tx("Save")}
        </button>
      </div>
    </form>
  );
}

// -- what has come in ---------------------------------------------------------------------

function SupportInbox() {
  const tx = useT();
  const requests = useAllSupportRequests();
  const setStatus = useSetSupportStatus();
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="stack">
      {requests.isLoading ? (
        <Loading rows={2} />
      ) : requests.error ? (
        <ErrorBox error={requests.error} />
      ) : requests.data!.length === 0 ? (
        <Empty title={tx("Nothing yet.")} icon={<IconLifebuoy />}>
          {tx("Requests written on the support page are kept here as well as emailed.")}
        </Empty>
      ) : (
        <div className="stack tight">
          {requests.data!.map((r) => (
            <RequestRow
              key={r.id}
              request={r}
              open={open === r.id}
              onToggle={() => setOpen(open === r.id ? null : r.id)}
              onStatus={(status) => setStatus.mutate({ id: r.id, status })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function RequestRow({
  request: r,
  open,
  onToggle,
  onStatus,
}: {
  request: SupportRequest;
  open: boolean;
  onToggle: () => void;
  onStatus: (status: "open" | "closed") => void;
}) {
  const tx = useT();
  return (
    <details className="card acc" open={open}>
      <summary onClick={(e) => (e.preventDefault(), onToggle())}>
        <span className="acc-title">
          <span className="acc-name">
            {r.subject}
            {r.status === "closed" && <span className="tag">{tx("answered")}</span>}
          </span>
          <span className="acc-sub">
            {r.name || r.email} · {formatTime(r.created_at)}
          </span>
        </span>
        <span className="acc-right">
          <DeliveryBadge request={r} />
        </span>
      </summary>
      <div className="acc-body stack">
        <div className="muted small">
          {tx("Reply to")} <a href={`mailto:${r.email}?subject=Re: ${r.subject}`}>{r.email}</a>
        </div>
        {r.delivery_error && (
          <div className="callout warn">
            {tx("The email did not go out:")} {r.delivery_error}
          </div>
        )}
        <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
          {r.message}
        </pre>
        <div className="row">
          {r.status === "open" ? (
            <button className="btn small" onClick={() => onStatus("closed")}>
              <IconCheck /> {tx("Mark answered")}
            </button>
          ) : (
            <button className="btn small" onClick={() => onStatus("open")}>
              {tx("Reopen")}
            </button>
          )}
        </div>
      </div>
    </details>
  );
}

function DeliveryBadge({ request }: { request: SupportRequest }) {
  const tx = useT();
  if (request.delivery === "sent") {
    return (
      <span className="badge ok plain">
        <IconCheck /> {tx("emailed")}
      </span>
    );
  }
  if (request.delivery === "outbox")
    return <span className="badge idle">{tx("in the outbox")}</span>;
  return <span className="badge warn">{tx("not sent")}</span>;
}

// -- the outbox ---------------------------------------------------------------------------

function OutboxList() {
  const tx = useT();
  const outbox = useMailOutbox();

  if (outbox.isLoading) return <Loading rows={2} />;
  if (outbox.error) return <ErrorBox error={outbox.error} />;
  if (outbox.data!.length === 0) {
    return (
      <Empty title={tx("Empty.")} icon={<IconLifebuoy />}>
        {tx("Nothing is waiting: every letter has gone out.")}
      </Empty>
    );
  }
  return (
    <div className="stack tight">
      {outbox.data!.map((letter) => (
        <div key={letter.id} className="card">
          <div className="row spread">
            <strong>{letter.subject}</strong>
            <span className="muted small">{formatTime(letter.at)}</span>
          </div>
          <div className="muted small mono">{letter.to_address}</div>
          <pre className="mono" style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
            {letter.body}
          </pre>
        </div>
      ))}
    </div>
  );
}
