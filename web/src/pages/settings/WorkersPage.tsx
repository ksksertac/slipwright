// The machines the people on this account lend its developments (T14.5, T17.2). Two kinds
// of help, one list: a computer with the Slipwright Agent app writes phases on its owner's
// own model subscription, and a Mac builds what no container can -- iOS with Xcode. The
// page is a code to carry to the machine, and the machines already paired: whose each is,
// whether it is there, and what it is writing right now. The owner sees all of them; a
// member sees the ones they lent.
import { useEffect, useState } from "react";
import { describeError, type ConnectionCode, type Worker } from "../../api/client";
import {
  useConnectionCode,
  useRelay,
  useRevokeWorker,
  useSetRelay,
  useWorkers,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { Copyable } from "../../components/Copyable";
import { Modal } from "../../components/Modal";
import { ErrorBox, Loading, PageHead, timeAgo } from "../../components/ui";
import { useT } from "../../i18n";

const NAMES: Record<string, string> = { ios: "iOS", android: "Android" };
// what a machine writes, as the agents are called everywhere else
const WRITES: Record<string, string> = {
  backend: "Backend",
  web: "Web",
  mobile: "Mobile",
  infra: "DevOps",
  docs: "Docs",
  general: "General",
};

export function WorkersPage() {
  const tx = useT();
  const workers = useWorkers();
  return (
    <div>
      <PageHead
        title={tx("Machines")}
        subtitle={tx(
          "Your team's computers: they write phases on their own model subscriptions, and a Mac builds the mobile apps this server cannot.",
        )}
      />
      <p className="muted">
        {tx(
          "Install the Slipwright Agent app on a computer, paste a code from here, and choose which agents it runs and on which model -- its own Claude Code or Codex, or its own key. Phases of those agents are then written there, side by side with the others, and the server checks, builds and commits them as always. A machine that goes away costs nothing: its phase is written here instead.",
        )}
      </p>
      <p className="muted">
        {tx(
          "Slipwright runs in Docker, and Docker is Linux even on a Mac: it cannot reach Xcode or the Mac's Android Studio. The Mobile Builder is a small helper that runs on the Mac itself, outside Docker, and does the mobile builds: iOS with Xcode, and Android with Android Studio when this server cannot build it. The server may be on the same Mac or another machine; the helper finds it by itself, nothing is opened on the Mac, and it builds only this account's apps.",
        )}
      </p>
      <RelaySwitch />
      <h3 style={{ marginTop: 24 }}>{tx("Connected machines")}</h3>
      {workers.isLoading && <Loading />}
      {workers.error && <ErrorBox error={workers.error} />}
      {/* connecting one more is a card among the Macs, not a form above them: the page is
          the machines, and the way to add one sits where the next one will appear */}
      <div className="mac-grid">
        {(workers.data ?? []).map((w) => (
          <MacCard key={w.id} worker={w} />
        ))}
        <ConnectCard />
      </div>
    </div>
  );
}

// Whether a machine has to be on this network. Off, a code carries this server's own
// address; on, it carries the installation's room on the relay, and a machine anywhere
// comes in through it -- sealed end to end, the relay reading none of it. The installation's
// to decide, since it opens a connection out of this machine; everybody sees which it is.
function RelaySwitch() {
  const tx = useT();
  const relay = useRelay();
  const set = useSetRelay();
  const { user } = useAuth();
  const state = relay.data;
  if (!state?.available) return null;
  // the anonymous user of a server without logins is its administrator too
  const mayChange = !user || (!!user.is_admin && !user.owner_id);
  return (
    <div className="card relay-card" style={{ marginTop: 16, padding: 16 }}>
      <div className="row spread" style={{ gap: 12, alignItems: "flex-start" }}>
        <div>
          <strong>{tx("Reach machines on other networks")}</strong>
          <div className="muted small">
            {tx(
              "Machines at home, in another office or on the road connect through {relay}. Everything they send is sealed end to end: the relay passes it on and can read none of it.",
              { relay: state.url?.replace(/^wss?:\/\//, "") ?? "" },
            )}
          </div>
          {state.enabled && (
            <div className="small" style={{ marginTop: 6 }}>
              <span className={`dot ${state.connected ? "good" : "warn"}`} />{" "}
              {state.connected ? tx("Connected to the relay") : tx("Connecting to the relay…")}
            </div>
          )}
        </div>
        <label className="switch-row">
          <input
            type="checkbox"
            role="switch"
            checked={state.enabled}
            disabled={!mayChange || set.isPending}
            onChange={(e) => set.mutate(e.target.checked)}
          />
        </label>
      </div>
      {set.error && (
        <div className="callout error" style={{ marginTop: 8 }}>
          {describeError(set.error)}
        </div>
      )}
    </div>
  );
}

function ConnectCard() {
  const tx = useT();
  const make = useConnectionCode();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="card mac-card mac-connect"
        onClick={() => {
          setOpen(true);
          // the code is what the person came for: made on the press, not one more click on
          if (!make.data && !make.isPending) make.mutate(window.location.origin);
        }}
      >
        <span className="mac-plug">
          <IconPlug />
        </span>
        <strong>{tx("Connect a machine")}</strong>
        <span className="faint small">{tx("Make a code and paste it into the app")}</span>
      </button>
      {open && (
        <Modal title={tx("Connect a machine")} onClose={() => setOpen(false)} wide>
          <ConnectMac make={make} />
        </Modal>
      )}
    </>
  );
}

function IconPlug() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="28"
      height="28"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 2v5M15 2v5" />
      <path d="M6 7h12v4a6 6 0 0 1-12 0V7Z" />
      <path d="M12 17v5" />
    </svg>
  );
}

function ConnectMac({ make }: { make: ReturnType<typeof useConnectionCode> }) {
  const tx = useT();
  const code = make.data;
  // the page's own address is all the server needs: at localhost the code carries only
  // the port, and the Mac finds the server on its own network
  return (
    <div>
      <div className="row spread">
        <span className="muted small">{make.isPending ? tx("Making a code…") : null}</span>
        <button
          className="btn ghost small"
          disabled={make.isPending}
          onClick={() => make.mutate(window.location.origin)}
        >
          {code ? tx("New code") : tx("Make a code")}
        </button>
      </div>
      {make.error && (
        <div className="callout error" style={{ marginTop: 8 }}>
          {describeError(make.error)}
        </div>
      )}
      {code && <CodeSteps code={code} />}
    </div>
  );
}

function CodeSteps({ code }: { code: ConnectionCode }) {
  const tx = useT();
  const left = useSecondsLeft(code.expires_at);
  // the server says how: it knows where its own source is published
  const install = code.install.join("\n");
  const m = String(Math.floor(left / 60));
  const sec = String(left % 60).padStart(2, "0");
  // a code made at localhost carries no address, only the port
  const where = new URL(code.address);
  const nearby = where.hostname === "localhost";
  const port = where.port || "80";
  return (
    <div className="stack" style={{ marginTop: 12 }}>
      <div>
        <strong>{tx("With the Slipwright Agent app")}</strong>
        <div className="muted small">
          {tx("Open the app, go to Slipwright team and paste this code:")}
        </div>
        <Copyable text={code.code}>
          <pre>{code.code}</pre>
        </Copyable>
      </div>
      <strong>{tx("Or without the app, in a terminal")}</strong>
    <ol className="stack tight" style={{ paddingLeft: 18 }}>
      <li>
        {tx("Install Slipwright (once):")}
        <Copyable text={install}>
          <pre>{install}</pre>
        </Copyable>
      </li>
      <li>
        {tx("Then run:")}
        <Copyable text={code.command}>
          <pre>{code.command}</pre>
        </Copyable>
        <div className="muted small">
          {left > 0
            ? nearby
              ? tx(
                  "The code works once, for {m}:{s} more. The Mac looks for this server on its own network, on port {port}.",
                  { m, s: sec, port },
                )
              : tx("The code works once, for {m}:{s} more. It calls {address}.", {
                  m,
                  s: sec,
                  address: code.address,
                })
            : tx("This code has run out: make a new one.")}
        </div>
      </li>
      <li>
        {tx("To have it start at login:")}
        <Copyable text="slipwright worker service install">
          <pre>slipwright worker service install</pre>
        </Copyable>
      </li>
    </ol>
    </div>
  );
}

function useSecondsLeft(until: string): number {
  const end = new Date(until).getTime();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return Math.max(0, Math.round((end - now) / 1000));
}

// A Mac as a person recognises it: the machine, its name, whether it is there. The name
// is the one the Mac goes by in its own System Settings, sent at every poll; a Mac paired
// by an older worker shows its network address until that worker is updated.
function MacCard({ worker: w }: { worker: Worker }) {
  const tx = useT();
  const revoke = useRevokeWorker();
  return (
    <div className="card mac-card" data-online={w.online ? "yes" : "no"}>
      <div className="mac-stage">
        <MacBook />
        <span className="mac-status">
          <span className="mac-dot" />
          {w.online ? tx("online") : tx("offline")}
        </span>
      </div>
      <div className="mac-body">
        <div className="mac-name" title={w.name}>
          {w.name}
        </div>
        <div className="faint small">
          {w.lent_by_name ? tx("lent by {name}", { name: w.lent_by_name }) + " · " : ""}
          {w.online
            ? tx("paired {ago}", { ago: timeAgo(w.paired_at) })
            : tx("last seen {ago}", { ago: timeAgo(w.last_seen_at) })}
        </div>
        {w.writing && (
          <div className="small mac-doing" title={w.doing ?? undefined}>
            {w.doing_phase != null
              ? tx("Writing phase {n}", { n: w.doing_phase })
              : tx("Writing a phase")}
            {w.doing ? ` · ${w.doing}` : ""}
          </div>
        )}
        <div className="row mac-foot">
          <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {w.capabilities.length === 0 && (
              <span className="tag" title={tx("It found no Xcode and no Android SDK")}>
                {tx("builds nothing yet")}
              </span>
            )}
            {w.capabilities.map((c) =>
              c.startsWith("write:") ? (
                <span key={c} className="tag" data-kind="writes">
                  {tx("writes {agent}", { agent: tx(WRITES[c.slice(6)] ?? c.slice(6)) })}
                </span>
              ) : (
                <span key={c} className="tag">
                  {tx("builds {platform}", { platform: NAMES[c] ?? c })}
                </span>
              ),
            )}
          </span>
          <button
            className="btn ghost small mac-remove"
            disabled={revoke.isPending}
            onClick={() => {
              if (
                window.confirm(tx("Remove this machine? It stops working for this account."))
              ) {
                revoke.mutate(w.id);
              }
            }}
          >
            {tx("Remove")}
          </button>
        </div>
      </div>
    </div>
  );
}

// a MacBook drawn in the page's own colours, so it sits right in either theme; the screen
// lights up while the Mac is there and goes dark when it is not (CSS, on data-online)
function MacBook() {
  return (
    <svg className="macbook" viewBox="0 0 220 132" aria-hidden="true">
      <defs>
        <linearGradient id="mac-screen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" className="mac-screen-a" />
          <stop offset="1" className="mac-screen-b" />
        </linearGradient>
      </defs>
      <rect className="mac-lid" x="34" y="6" width="152" height="104" rx="9" />
      <rect x="41" y="13" width="138" height="88" rx="3" fill="url(#mac-screen)" />
      <rect className="mac-notch" x="102" y="13" width="16" height="4" rx="2" />
      <g className="mac-glyph">
        <path d="M104 50c0-5 4-7 6-7-1-3-4-4-6-4-3 0-4 2-6 2s-3-2-6-2c-3 0-7 3-7 9 0 7 5 14 8 14 2 0 3-1 5-1s3 1 5 1c2 0 4-3 5-5-3-1-4-4-4-7Z" />
        <path d="M101 37c1-2 3-3 4-3 0 2-1 4-3 5-1 0-2 0-1-2Z" />
      </g>
      <path className="mac-base" d="M8 112h204l-6 10c-2 3-5 4-9 4H23c-4 0-7-1-9-4Z" />
      <rect className="mac-lip" x="94" y="112" width="32" height="4" rx="2" />
    </svg>
  );
}
