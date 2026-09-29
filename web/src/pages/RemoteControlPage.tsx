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

export function RemoteControlPage() {
  const tx = useT();
  const notify = useNotify();

  if (notify.isLoading) return <Loading />;
  if (notify.error) return <ErrorBox error={notify.error} />;
  const data = notify.data!;
  const channel = data.channels.find((c) => c.channel === "telegram")!;
  const links = data.links.filter((l) => l.channel === "telegram");

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

      <div className="notify-cards">
        {data.may_configure && <BotCard channel={channel} />}
        <LinkCard channel={channel} links={links} owner={data.may_configure} />

        <section className="card">
          <h3>{tx("What you can ask it")}</h3>
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
          <h4>{tx("Starting work")}</h4>
          <p className="muted small">
            {tx(
              "Say what you want built and it asks you to confirm before anything runs — reading a sentence is a guess, and a wrong guess would spend your own model credit. /yeni walks through it a question at a time; /proje opens a new project.",
            )}
          </p>
        </section>
      </div>
    </div>
  );
}
