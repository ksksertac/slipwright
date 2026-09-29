// Running Slipwright from a chat: one bot, one linked account, and the things you can
// ask it.
//
// This used to be the "Personal" half of the Notifications page, which put two unlike
// jobs behind one word. A group is *told* -- it never decides anything. A linked chat is
// where somebody *works*: asks where a development is, starts one, says yes at a gate.
// That is not a notification setting, so it has a page of its own.
//
// Telegram only, deliberately. It is the one service whose bot pulls its own updates, so
// a server on somebody's laptop answers without a public address, and the account behind
// a press is proven by a code rather than assumed from a webhook.
import { NavLink, useParams } from "react-router-dom";
import { useNotify } from "../api/hooks";
import { BotCard, LinkCard } from "./settings/NotificationsPage";
import { ErrorBox, Loading, PageHead } from "../components/ui";
import { useT } from "../i18n";

/** What the bot answers, shown as the examples they are: somebody reading this wants to
 *  know what to type, not what the feature is called. */
const ASKS: string[] = [
  "which projects do I have",
  "how is NoteApp doing",
  "what is waiting for me",
  "what did NoteApp cost",
  "why did the maths one stop",
];

/** Connecting it, and what to say to it once it is connected. Two tabs rather than one
 *  long page: the setup is read once and the phrasebook is read every time after that,
 *  and it was below two cards where nobody would scroll to it. */
const TABS = ["setup", "ask"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { setup: "Connecting", ask: "What you can ask it" };

export function RemoteControlPage() {
  const tx = useT();
  const notify = useNotify();
  const { tab } = useParams();
  const current: Tab = tab === "ask" ? "ask" : "setup";

  if (notify.isLoading) return <Loading />;
  if (notify.error) return <ErrorBox error={notify.error} />;
  const data = notify.data!;
  const channel = data.channels.find((c) => c.channel === "telegram")!;
  const links = data.links.filter((l) => l.channel === "telegram");
  const linked = links.some((l) => l.mine);

  return (
    <div className="settings-flow">
      <PageHead
        title={tx("Remote control")}
        subtitle={tx("Run it from Telegram, without opening this page.")}
      />
      <p className="muted">
        {tx(
          "Link your Telegram account once and the bot answers where things stand, starts a development when you ask it to, and brings your own gates to you with two buttons. It reads your account and nobody else's.",
        )}
      </p>

      <nav className="tabs dotted">
        {TABS.map((t) => (
          <NavLink key={t} to={`/remote/${t}`} className={t === current ? "active" : ""}>
            {tx(TAB_LABEL[t])}
            {t === "setup" && linked && <span className="notify-part-ready" />}
          </NavLink>
        ))}
      </nav>

      {current === "setup" ? (
        <div className="notify-cards">
          {data.may_configure && <BotCard channel={channel} />}
          <LinkCard channel={channel} links={links} owner={data.may_configure} />
        </div>
      ) : (
        <Phrasebook />
      )}
    </div>
  );
}

function Phrasebook() {
  const tx = useT();
  return (
    <div className="notify-cards">
      <section className="card">
        <h3>{tx("Asking where things are")}</h3>
        <p className="muted small">
          {tx(
            "In your own words, or with a command. A command costs nothing — no model is asked what it meant.",
          )}
        </p>
        <ul className="small">
          {ASKS.map((ask) => (
            <li key={ask}>{tx(ask)}</li>
          ))}
        </ul>
        <p className="small">
          <code>/projeler</code> <code>/durum</code> <code>/bekleyen</code> <code>/calisan</code>{" "}
          <code>/maliyet</code>
        </p>
      </section>

      <section className="card">
        <h3>{tx("Starting work")}</h3>
        <p className="muted small">
          {tx(
            "Say what you want built and it asks you to confirm before anything runs — reading a sentence is a guess, and a wrong guess would spend your own model credit. /yeni walks through it a question at a time; /proje opens a new project.",
          )}
        </p>
        <p className="small">
          <code>/yeni</code> <code>/proje</code> <code>/iptal</code>
        </p>
      </section>
    </div>
  );
}
