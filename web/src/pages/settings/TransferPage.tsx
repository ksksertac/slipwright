// Moving this account to another Slipwright on the same network (slipwright/transfer).
// The page is the machines, as Mac Connect's is: this one, the others found on the
// network, and -- where the next one would appear -- a card that turns this machine into
// the receiving end and shows the code. Sending is a press on the other machine's card
// and the code typed into it; both screens then follow the same steps.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  describeError,
  type TransferHere,
  type TransferPeer,
  type TransferStatus,
} from "../../api/client";
import {
  useIncomingTransfer,
  useNearby,
  useSendTransfer,
  useSendingStatus,
  useStopReceiving,
  useTransferCode,
  useTransferHere,
} from "../../api/hooks";
import { Modal } from "../../components/Modal";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { useT } from "../../i18n";

type Picked = { peer: TransferPeer | null };

export function TransferPage() {
  const tx = useT();
  const here = useTransferHere();
  const on = here.data?.enabled ?? false;
  const nearby = useNearby(on);
  const [picked, setPicked] = useState<Picked | null>(null);
  // the look finds this installation too, at the address the others would use: that is
  // its card's address, and the rest are the others
  const self = (nearby.data ?? []).find((p) => p.this_one);
  const others = (nearby.data ?? []).filter((p) => !p.this_one);
  return (
    <div>
      <PageHead
        title={tx("Move")}
        subtitle={tx(
          "Move this account to another Slipwright on the same network in one go: projects, developments, settings, model keys and attachments.",
        )}
      />
      <p className="muted">
        {tx(
          "On the receiving computer press Receive here: a code appears for 30 seconds. On the sending computer press that installation's card and type the code. Accounts and sessions do not move; everything goes to the account signed in on the receiving side.",
        )}
      </p>
      {here.isLoading && <Loading />}
      {here.error && <ErrorBox error={here.error} />}
      {here.data && !on && (
        <div className="callout">{tx("Moving to another computer is off on this server.")}</div>
      )}
      {here.data && on && (
        <>
          <h3 className="move-head">
            {tx("Slipwrights on this network")}
            <span className="move-scan faint small">
              {nearby.isFetching ? (
                <>
                  <span className="move-spin" aria-hidden="true" />
                  {here.data.networks.length > 0
                    ? tx("Looking at {nets}…", { nets: here.data.networks.join(", ") })
                    : tx("Looking around the network…")}
                </>
              ) : nearby.error ? (
                describeError(nearby.error)
              ) : (
                tx("{n} found", { n: String(others.length) })
              )}
              {!nearby.isFetching && (
                <>
                  {" · "}
                  <button className="linkish" onClick={() => void nearby.refetch()}>
                    {tx("look again")}
                  </button>
                  {" · "}
                  <button className="linkish" onClick={() => setPicked({ peer: null })}>
                    {tx("connect by address")}
                  </button>
                </>
              )}
            </span>
          </h3>
          <div className="mac-grid">
            <HereCard here={here.data} seen={self} />
            {others.map((peer) => (
              <PeerCard key={peer.instance} peer={peer} onPick={() => setPicked({ peer })} />
            ))}
            <ReceiveCard here={here.data} />
          </div>
          <div className="move-pills">
            <Pill title={tx("Sealed end to end")} icon="🔐">
              {tx(
                "The code sets up a key between the two machines; somebody listening on the network sees neither the code nor the keys.",
              )}
            </Pill>
            <Pill title={tx("Keys arrive working")} icon="🔑">
              {tx(
                "Model, Git and Jira keys are sealed again with the receiving installation's own key.",
              )}
            </Pill>
            <Pill title={tx("All or nothing")} icon="↺">
              {tx("A transfer that stops half-way leaves nothing behind on the receiving side.")}
            </Pill>
          </div>
        </>
      )}
      {picked && here.data && (
        <SendModal here={here.data} peer={picked.peer} onClose={() => setPicked(null)} />
      )}
    </div>
  );
}

function Pill({ title, icon, children }: { title: string; icon: string; children: string }) {
  return (
    <div className="move-pill">
      <span className="move-pill-icon" aria-hidden="true">
        {icon}
      </span>
      <div>
        <strong>{title}</strong>
        <div>{children}</div>
      </div>
    </div>
  );
}

// -- the cards ---------------------------------------------------------------------------

const DATABASES: Record<string, string> = { sqlite: "SQLite", postgresql: "PostgreSQL" };

function HereCard({ here, seen }: { here: TransferHere; seen: TransferPeer | undefined }) {
  const tx = useT();
  return (
    <div className="card mac-card" data-online="yes">
      <div className="mac-stage">
        <span className="move-here">{tx("this computer")}</span>
        <Desktop />
        <span className="mac-status">
          <span className="mac-dot" />
          {tx("online")}
        </span>
      </div>
      <div className="mac-body">
        <div className="mac-name" title={here.name}>
          {here.name}
        </div>
        <div className="faint small">
          {[
            hostOf(seen?.address ?? here.addresses[0]),
            tx("{n} projects", { n: String(here.projects) }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <div className="row mac-foot">
          <span className="row" style={{ gap: 6 }}>
            <span className="tag">v{here.version}</span>
            <span className="tag">{DATABASES[here.database] ?? here.database}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function PeerCard({ peer, onPick }: { peer: TransferPeer; onPick: () => void }) {
  const tx = useT();
  return (
    <button type="button" className="card mac-card move-peer" data-online="yes" onClick={onPick}>
      <div className="mac-stage">
        <Desktop />
        <span className="mac-status">
          <span className="mac-dot" />
          {tx("online")}
        </span>
      </div>
      <div className="mac-body">
        <div className="mac-name" title={peer.name}>
          {peer.name}
        </div>
        <div className="faint small">
          {[
            hostOf(peer.address),
            peer.projects == null
              ? ""
              : peer.projects === 0
                ? tx("empty installation")
                : tx("{n} projects", { n: String(peer.projects) }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <div className="row mac-foot">
          <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <span className={`tag ${peer.compatible ? "" : "move-old"}`}>
              {peer.legacy ? tx("older version") : `v${peer.version}`}
            </span>
            {peer.database && (
              <span className="tag">{DATABASES[peer.database] ?? peer.database}</span>
            )}
          </span>
          {peer.compatible ? (
            <span className="btn small primary">{tx("Move here →")}</span>
          ) : (
            <span className="faint small move-update">{tx("Update needed")}</span>
          )}
        </div>
      </div>
    </button>
  );
}

// The receiving end: pressed, it shows a code that changes every thirty seconds -- the
// one before keeps working a while, for whoever is half-way through typing it -- and
// watches for a transfer to arrive, which then takes over the screen.
function ReceiveCard({ here }: { here: TransferHere }) {
  const tx = useT();
  const make = useTransferCode();
  const stop = useStopReceiving();
  const [live, setLive] = useState(false);
  const [left, setLeft] = useState(0);
  const [watching, setWatching] = useState<string | null>(null);
  const incoming = useIncomingTransfer(live || watching !== null);
  // whatever arrived before this showing is not news
  const before = useRef<string | null | undefined>(undefined);
  const code = make.data;

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setLeft((s) => s - 1), 1000);
    return () => window.clearInterval(id);
  }, [live]);
  useEffect(() => {
    if (live && left <= 0 && !make.isPending) {
      make.mutate(undefined, { onSuccess: (c) => setLeft(c.shown_s) });
    }
  }, [live, left, make]);
  useEffect(() => {
    const arrived = incoming.data;
    if (!live || arrived === undefined) return;
    if (before.current === undefined) {
      before.current = arrived?.id ?? null;
      return;
    }
    if (arrived && arrived.id !== before.current) {
      setWatching(arrived.id);
      setLive(false);
    }
  }, [incoming.data, live]);

  const start = () => {
    before.current = incoming.data === undefined ? undefined : (incoming.data?.id ?? null);
    setLeft(0);
    setLive(true);
  };
  const cancel = () => {
    setLive(false);
    stop.mutate();
  };

  const shown = code?.shown_s ?? 30;
  const ring = 2 * Math.PI * 42;
  const status = watching && incoming.data?.id === watching ? incoming.data : null;
  return (
    <>
      {!live ? (
        <button type="button" className="card mac-card mac-connect" onClick={start}>
          <span className="mac-plug">
            <IconReceive />
          </span>
          <strong>{tx("Receive here")}</strong>
          <span className="faint small">{tx("Make a code, type it on the sending computer")}</span>
        </button>
      ) : (
        <div className="card mac-card mac-connect move-live">
          <div className="move-ring" aria-label={tx("{s} seconds", { s: String(left) })}>
            <svg width="96" height="96" viewBox="0 0 96 96">
              <circle cx="48" cy="48" r="42" className="move-ring-track" />
              <circle
                cx="48"
                cy="48"
                r="42"
                className={`move-ring-arc ${left <= 8 ? "late" : ""}`}
                strokeDasharray={ring}
                strokeDashoffset={ring * (1 - Math.max(left, 0) / shown)}
              />
            </svg>
            <span className="move-ring-num">
              {Math.max(left, 0)}
              <small>{tx("sec")}</small>
            </span>
          </div>
          <CodeChip code={code?.code} />
          {make.error ? (
            <div className="callout error">{describeError(make.error)}</div>
          ) : (
            <span className="faint small move-hint">
              {tx("On the sending computer, press this installation's card and type the code.")}
            </span>
          )}
          <span className="faint small move-hint">
            {here.addresses.length > 0
              ? tx("Not found there? Its address: {a}", { a: here.addresses[0] ?? "" })
              : tx(
                  "Not found there? Its address is this computer's IPv4 address (ipconfig), port {port}.",
                  { port: window.location.port || "80" },
                )}
          </span>
          <button className="btn ghost small" onClick={cancel}>
            {tx("Cancel")}
          </button>
        </div>
      )}
      {watching && (
        <Modal
          title={tx("Arriving from {name}", { name: status?.peer ?? "…" })}
          onClose={() => {
            if (!status || status.state === "done" || status.state === "failed") {
              setWatching(null);
            }
          }}
          wide
        >
          {status ? <Progress status={status} receiving /> : <Loading rows={2} />}
        </Modal>
      )}
    </>
  );
}

// a new code flashes as it replaces the last: keyed on the code, so the button is drawn
// afresh and its animation plays again
function CodeChip({ code }: { code: string | undefined }) {
  const tx = useT();
  return (
    <button
      key={code}
      type="button"
      className={`move-code ${code ? "flash" : ""}`}
      title={tx("Copy")}
      onClick={() => code && void navigator.clipboard?.writeText(code)}
    >
      {code ?? "SW-····-····-····"}
    </button>
  );
}

// -- sending -----------------------------------------------------------------------------

function SendModal({
  here,
  peer,
  onClose,
}: {
  here: TransferHere;
  peer: TransferPeer | null;
  onClose: () => void;
}) {
  const tx = useT();
  const send = useSendTransfer();
  const [address, setAddress] = useState(peer?.address ?? "");
  const [code, setCode] = useState("");
  const [deleteAfter, setDeleteAfter] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const status = useSendingStatus(sendingId);
  const running =
    sendingId !== null && status.data?.state !== "done" && status.data?.state !== "failed";
  const name = peer?.name ?? (hostOf(address) || tx("another computer"));
  const ready = code.replace(/[^0-9a-z]/gi, "").length >= 12 && address.trim().length > 3;

  const go = () => {
    send.mutate(
      { address: address.trim(), code: code.trim(), delete_after: deleteAfter },
      { onSuccess: (s) => setSendingId(s.id) },
    );
  };

  if (peer && !peer.compatible) {
    return (
      <Modal title={tx("Move to {name}", { name })} onClose={onClose}>
        <div className="callout">
          {tx(
            "{name} runs another version of Slipwright (v{v}, this one v{mine}). Their databases differ, so nothing can move yet: update the older one from the corner of its screen, then try again.",
            { name, v: peer.version || "?", mine: here.version },
          )}
        </div>
      </Modal>
    );
  }
  return (
    <Modal
      title={tx("Move to {name}", { name })}
      onClose={() => !running && onClose()}
      wide
      footer={
        sendingId === null ? (
          <>
            <button className="btn ghost" onClick={onClose}>
              {tx("Cancel")}
            </button>
            <button className="btn primary" disabled={!ready || send.isPending} onClick={go}>
              {send.isPending ? tx("Starting…") : tx("Move it")}
            </button>
          </>
        ) : status.data?.state === "failed" ? (
          <>
            <button className="btn ghost" onClick={onClose}>
              {tx("Close")}
            </button>
            <button
              className="btn primary"
              onClick={() => {
                setSendingId(null);
                setCode("");
                send.reset();
              }}
            >
              {tx("Try again")}
            </button>
          </>
        ) : status.data?.state === "done" ? (
          <>
            <button className="btn ghost" onClick={onClose}>
              {tx("Close")}
            </button>
            <a
              className="btn primary"
              href={`${address.replace(/\/$/, "")}/projects`}
              target="_blank"
              rel="noreferrer"
            >
              {tx("Open on {name} ↗", { name })}
            </a>
          </>
        ) : (
          <button className="btn ghost" disabled>
            {tx("Moving…")}
          </button>
        )
      }
    >
      <div className="move-route">
        <div className="move-node">
          <strong>{here.name}</strong>
          <span>{hostOf(here.addresses[0]) || tx("this computer")}</span>
        </div>
        <div className={`move-arrow ${running ? "run" : ""}`} />
        <div className="move-node">
          <strong>{name}</strong>
          <span>{hostOf(address) || "—"}</span>
        </div>
      </div>
      {sendingId === null ? (
        <>
          {!peer && (
            <div className="field">
              <label htmlFor="move-address">{tx("Its address")}</label>
              <input
                id="move-address"
                type="url"
                placeholder="http://192.168.1.24:8500"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </div>
          )}
          <div className="field">
            <label htmlFor="move-code">{tx("The code on {name}'s screen", { name })}</label>
            <input
              id="move-code"
              type="text"
              className="move-code-in"
              placeholder="SW-XXXX-XXXX-XXXX"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && ready && go()}
            />
          </div>
          {send.error && <div className="callout error">{describeError(send.error)}</div>}
          <div className="move-goes">
            <Goes yes>{tx("Projects and developments, with their history")}</Goes>
            <Goes yes>{tx("Checkouts, branches and uncommitted work")}</Goes>
            <Goes yes>{tx("Model, Git and Jira keys")}</Goes>
            <Goes yes>{tx("Attachments and standards")}</Goes>
            <Goes yes={here.admin}>{tx("This installation's settings (mail, prices)")}</Goes>
            <Goes yes={false}>{tx("Accounts and sessions")}</Goes>
          </div>
          <label className="move-delete">
            <input
              type="checkbox"
              checked={deleteAfter}
              onChange={(e) => setDeleteAfter(e.target.checked)}
            />
            {tx("Delete them from this computer once they are there")}
          </label>
          <p className="faint small">
            {tx(
              "Connected Macs do not move: pair the Mac again with the new computer. A development that is running must finish or stop at a gate first.",
            )}
          </p>
        </>
      ) : status.data ? (
        <Progress status={status.data} />
      ) : (
        <Loading rows={2} />
      )}
    </Modal>
  );
}

function Goes({ yes, children }: { yes: boolean; children: string }) {
  return (
    <div className={`move-go ${yes ? "" : "no"}`}>
      <span aria-hidden="true">{yes ? "✓" : "—"}</span>
      {children}
    </div>
  );
}

// -- both screens ------------------------------------------------------------------------

const STEP_LABELS: Record<string, string> = {
  pair: "Pairing and a sealed channel",
  projects: "Projects",
  jobs: "Developments and their history",
  settings: "Settings and keys",
  attachments: "Attachments",
  standards: "Standards",
  repos: "Checkouts and branches",
  finish: "Writing and checking",
  delete: "Deleting from this computer",
};

function Progress({ status, receiving = false }: { status: TransferStatus; receiving?: boolean }) {
  const tx = useT();
  const steps = status.steps;
  const done = steps.filter((s) => s.state === "done").length;
  const pct = Math.round((done / Math.max(steps.length, 1)) * 100);
  if (status.state === "done") {
    const c = status.counts;
    return (
      <div className="move-done">
        <div className="move-ok" aria-hidden="true">
          ✓
        </div>
        <h3>{tx("Moved")}</h3>
        <p className="muted">
          {status.moved.length > 0
            ? tx("{names} {verb}.", {
                names: status.moved.join(", "),
                verb: receiving ? tx("arrived here") : tx("are there now"),
              })
            : tx("Nothing new: everything was already there.")}
        </p>
        <div className="move-sum">
          <Sum n={c.projects ?? 0} label={tx("projects")} />
          <Sum n={c.jobs ?? 0} label={tx("developments")} />
          <Sum n={c.settings ?? 0} label={tx("settings")} />
          <Sum n={c.attachments ?? 0} label={tx("attachments")} />
        </div>
        {status.skipped > 0 && (
          <div className="callout">
            {tx("{n} project(s) were already there and were left as they were.", {
              n: String(status.skipped),
            })}
          </div>
        )}
        {receiving && (
          <Link className="btn primary" to="/projects">
            {tx("Go to projects")}
          </Link>
        )}
      </div>
    );
  }
  return (
    <div>
      {status.state === "failed" && (
        <div className="callout error" style={{ marginBottom: 12 }}>
          {status.error ?? tx("The transfer failed.")}
          <div className="small">{tx("Nothing was changed on either computer.")}</div>
        </div>
      )}
      <ul className="move-steps">
        {steps.map((s) => (
          <li key={s.key} className={s.state}>
            <span className="move-step-dot">{s.state === "done" ? "✓" : ""}</span>
            {tx(STEP_LABELS[s.key] ?? s.key)}
            {s.total > 0 && s.key !== "pair" && s.key !== "finish" && (
              <span className="move-step-count">
                {Math.min(s.done, s.total)} / {s.total}
              </span>
            )}
          </li>
        ))}
      </ul>
      <div className="move-bar">
        <i style={{ width: `${pct}%` }} />
      </div>
      <div className="faint small" style={{ textAlign: "right" }}>
        %{pct}
      </div>
    </div>
  );
}

function Sum({ n, label }: { n: number; label: string }) {
  return (
    <div>
      <strong>{n}</strong>
      <span>{label}</span>
    </div>
  );
}

// -- drawing -----------------------------------------------------------------------------

function hostOf(address: string | undefined): string {
  if (!address) return "";
  try {
    return new URL(address).host;
  } catch {
    return address;
  }
}

// a desktop drawn in the page's own colours, beside the Mac Connect page's MacBook: the
// same classes, so it lights up and goes dark the same way
function Desktop() {
  return (
    <svg className="macbook" viewBox="0 0 220 150" aria-hidden="true">
      <defs>
        <linearGradient id="pc-screen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" className="mac-screen-a" />
          <stop offset="1" className="mac-screen-b" />
        </linearGradient>
      </defs>
      <rect className="mac-lid" x="20" y="6" width="180" height="110" rx="9" />
      <rect x="28" y="14" width="164" height="94" rx="3" fill="url(#pc-screen)" />
      <g className="mac-glyph">
        <rect x="96" y="44" width="13" height="13" rx="1.5" />
        <rect x="111" y="44" width="13" height="13" rx="1.5" />
        <rect x="96" y="59" width="13" height="13" rx="1.5" />
        <rect x="111" y="59" width="13" height="13" rx="1.5" />
      </g>
      <path className="mac-base" d="M98 116h24l5 22H93z" />
      <rect className="mac-base" x="72" y="136" width="76" height="7" rx="3.5" />
    </svg>
  );
}

function IconReceive() {
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
      <path d="M12 3v12M7 10l5 5 5-5" />
      <path d="M5 19h14" />
    </svg>
  );
}
