// The build room: while a development's phases are being written and built, the lane opens
// a window that draws it the way it actually happens -- the machines writing on the left,
// Slipwright in the middle taking each answer in its turn, the branch on the right filling
// up with commits. It is the Building stage's own view, so it follows that stage: open
// while a phase runs, out of the way while a person is asked something (a review, a
// decision, a pause), back once they have answered, and gone for good when the phases are.
//
// Only an opened lane has one. The closed list of developments never pops anything up, and
// of several opened lanes only the last one to open holds the window.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { BuildRoom as Room, JobState, Lane, RoomMachine, RoomPhase } from "../api/client";
import { useBuildRoom } from "../api/hooks";
import { useT, type T } from "../i18n";
import { useSay } from "../i18n/said";
import { IconGit, IconX } from "./icons";
import { nameOf } from "./ui";

/** A phase is being written, built or reviewed: the room is open. The server's `LIVE`
 * (slipwright/building.py) -- every other state is a person's turn, or past the phases. */
const LIVE = new Set<JobState>(["developing", "build_gate", "review", "reconcile"]);
/** Past the phases: the room shows its last frame, every phase committed, and closes. */
const PAST = new Set<JobState>([
  "qa",
  "awaiting_test_approval",
  "devops",
  "awaiting_deploy_approval",
  "done",
]);
/** How long that last frame stays before the window closes by itself. */
const FINALE_MS = 4000;

// -- one window at a time ----------------------------------------------------------------
// Two lanes opened side by side, both building, would stack two full-screen windows. The
// last lane to want the window holds it; when it lets go, the one before it gets it back.

const holders: string[] = [];
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());
function claim(id: string) {
  const at = holders.indexOf(id);
  if (at >= 0) holders.splice(at, 1);
  holders.push(id);
  notify();
}
function release(id: string) {
  const at = holders.indexOf(id);
  if (at < 0) return;
  holders.splice(at, 1);
  notify();
}
function useHolder(): string | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => holders.at(-1) ?? null,
  );
}

/** Lets the Building stage's head offer "Watch live" without the flow passing it down. */
const Opener = createContext<(() => void) | null>(null);
export function useBuildRoomOpener(): (() => void) | null {
  return useContext(Opener);
}

/** Wraps an opened lane's detail: decides when the room is shown and gives the stage head
 * a way to open it by hand. */
export function BuildRoomHost({ lane, children }: Readonly<{ lane: Lane; children: ReactNode }>) {
  const live = LIVE.has(lane.state);
  // closed by hand: stays closed until the next time the phases carry on after a person's
  // turn -- otherwise the two-second poll would throw it back open at once
  const [dismissed, setDismissed] = useState(false);
  const [asked, setAsked] = useState(false);
  const [finale, setFinale] = useState(false);
  const was = useRef(live);
  useEffect(() => {
    if (live && !was.current) setDismissed(false); // a gate answered: the work carries on
    if (!live && was.current && PAST.has(lane.state)) setFinale(true);
    was.current = live;
  }, [live, lane.state]);
  useEffect(() => {
    if (!finale) return;
    const t = window.setTimeout(() => setFinale(false), FINALE_MS);
    return () => window.clearTimeout(t);
  }, [finale]);

  const open = asked || ((live || finale) && !dismissed);
  useEffect(() => {
    if (!open) return;
    claim(lane.job_id);
    return () => release(lane.job_id);
  }, [open, lane.job_id]);
  const holder = useHolder();
  const close = useCallback(() => {
    setDismissed(true);
    setAsked(false);
    setFinale(false);
  }, []);
  const ask = useCallback(() => setAsked(true), []);

  return (
    <Opener.Provider value={ask}>
      {children}
      {open && holder === lane.job_id && <BuildRoomWindow lane={lane} onClose={close} />}
    </Opener.Provider>
  );
}

// -- the window ---------------------------------------------------------------------------

function BuildRoomWindow({ lane, onClose }: Readonly<{ lane: Lane; onClose: () => void }>) {
  const tx = useT();
  const room = useBuildRoom(lane.job_id, true);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="room-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="room" role="dialog" aria-modal="true" aria-label={tx("Building")}>
        <button className="room-close" onClick={onClose} aria-label={tx("Close")}>
          <IconX />
        </button>
        <p className="room-lead">
          <b>{tx("Machines write the phases side by side")}</b>
          <span className="room-dot"> · </span>
          <b>Slipwright</b> {tx("puts them together on one branch")}
        </p>
        {room.data ? (
          <RoomBody room={room.data} title={nameOf(lane)} />
        ) : (
          <div className="room-wait">{tx("Loading…")}</div>
        )}
      </div>
    </div>
  );
}

type Path = { key: string; d: string; active: boolean };

function RoomBody({ room, title }: Readonly<{ room: Room; title: string }>) {
  const tx = useT();
  const frame = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const branch = useRef<HTMLDivElement>(null);
  const [paths, setPaths] = useState<Path[]>([]);

  const writing = room.phases.filter((p) => p.writing);
  const serverWriting = room.server.writing.length > 0;
  const active = new Set([
    ...room.machines.filter((m) => m.phase != null).map((m) => m.id),
    ...(serverWriting ? ["server"] : []),
  ]);
  const activeKey = [...active].sort((a, b) => a.localeCompare(b)).join(",");

  // the dashed lines from each machine to Slipwright, and the one on to the branch: drawn
  // from where the cards actually are, again whenever the window or the cards resize
  useLayoutEffect(() => {
    const box = frame.current;
    if (!box) return;
    const draw = () => {
      const at = box.getBoundingClientRect();
      const mid = hub.current?.getBoundingClientRect();
      const out = branch.current?.getBoundingClientRect();
      if (!mid || !out || mid.width === 0) return setPaths([]);
      const next: Path[] = [];
      // the cards say which line is theirs; read off the page when drawing, not kept
      const entries = [...box.querySelectorAll<HTMLElement>("[data-room-key]")].map(
        (el) => [el.dataset.roomKey ?? "", el] as const,
      );
      entries.forEach(([key, el], i) => {
        const r = el.getBoundingClientRect();
        const x1 = r.right - at.left;
        const y1 = r.top + r.height / 2 - at.top;
        const x2 = mid.left - at.left;
        // the lines arrive spread over the middle of the hub, not on one point
        const spread = Math.min(mid.height * 0.5, entries.length * 14);
        const y2 =
          mid.top -
          at.top +
          mid.height / 2 -
          spread / 2 +
          (spread * i) / Math.max(1, entries.length - 1 || 1);
        const bend = (x2 - x1) / 2;
        next.push({
          key,
          d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
          active: active.has(key),
        });
      });
      const y = mid.top - at.top + mid.height / 2;
      next.push({
        key: "branch",
        d: `M ${mid.right - at.left} ${y} L ${out.left - at.left} ${y}`,
        active: room.live,
      });
      setPaths(next);
    };
    draw();
    const seen = new ResizeObserver(draw);
    seen.observe(box);
    return () => seen.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `active` is read through its key
  }, [room.machines.length, activeKey, room.live]);

  const numbers = room.phases.map((p) => p.number);
  const done = room.phases.filter((p) => p.status === "done").length;
  let turn: ReactNode;
  if (room.in_turn != null) {
    turn = (
      <>
        {tx("Phase {n}", { n: room.in_turn })}
        <span className="room-step"> · {stepLabel(tx, room.step)}</span>
      </>
    );
  } else if (done === room.phases.length && done > 0) {
    turn = tx("all {n} committed", { n: done });
  } else {
    turn = tx("{done} of {total} committed", { done, total: room.phases.length });
  }

  return (
    <div className="room-frame" ref={frame}>
      <svg className="room-lines" aria-hidden="true">
        {paths.map((p) => (
          <path key={p.key} d={p.d} className={p.active ? "on" : ""} />
        ))}
      </svg>

      <section className="room-col room-machines">
        <h4 className="room-cap">{tx("Writing")}</h4>
        <ServerCard room={room} />
        {room.machines.map((m) => (
          <MachineCard key={m.id} machine={m} />
        ))}
        {room.machines.length === 0 && (
          <p className="room-none">
            {tx("No machine is lent to this account: the server writes every phase.")}
          </p>
        )}
      </section>

      <section className="room-col room-mid">
        <div className={`room-hub ${room.live ? "live" : ""}`} ref={hub}>
          <img className="room-logo" src="/logo.png" alt="" width={56} height={56} />
          <div className="room-name">Slipwright</div>
          <div className="room-sub">
            {title}
            {numbers.length > 0 && (
              <>
                {" · "}
                {tx("phases {a}–{b}", { a: numbers[0]!, b: numbers.at(-1)! })}
              </>
            )}
          </div>
          <div className="room-label">{tx("Writing at once")}</div>
          <div className="room-slots">
            {Array.from({ length: Math.max(room.slots, writing.length) }, (_, i) => {
              const p = writing[i];
              return (
                <div key={i} className={`room-slot ${p ? "full" : ""}`}>
                  {p ? (
                    <>
                      <b>{tx("P{n}", { n: p.number })}</b>
                      <span>{p.writer ?? tx("the server")}</span>
                    </>
                  ) : (
                    "·"
                  )}
                </div>
              );
            })}
          </div>
          <div className="room-label">{tx("In its turn")}</div>
          <div className="room-turn">{turn}</div>
          {room.pr_url && (
            <a className="room-pr-chip" href={room.pr_url} target="_blank" rel="noreferrer">
              {tx("pull request opened")}
            </a>
          )}
        </div>
      </section>

      <section className="room-col room-branch" ref={branch}>
        <h4 className="room-cap">{tx("One branch, one pull request")}</h4>
        <div className="room-branch-card">
          <div className="room-branch-name">
            <IconGit /> <code>{room.branch}</code>
          </div>
          <div className="room-branch-note">
            {tx("no second checkout · no merge · no conflicts")}
          </div>
          <ol className="room-phases">
            {room.phases.map((p) => (
              <PhaseRow key={p.number} phase={p} room={room} />
            ))}
          </ol>
          <div className={`room-pr ${room.pr_url ? "open" : ""}`}>
            {room.pr_url ? (
              <a href={room.pr_url} target="_blank" rel="noreferrer">
                ✓ {tx("Pull request open")}
              </a>
            ) : (
              <span>{tx("The pull request opens with the first push")}</span>
            )}
            <small>
              {tx("{done} of {total} phases committed", { done, total: room.phases.length })}
            </small>
          </div>
        </div>
      </section>
    </div>
  );
}

function stepLabel(tx: T, step: string | null | undefined): string {
  switch (step) {
    case "writing":
      return tx("being written");
    case "building":
      return tx("building");
    case "reviewing":
      return tx("being reviewed");
    case "reconciling":
      return tx("reading the work done by hand");
    default:
      return "";
  }
}

// -- the left: who writes ----------------------------------------------------------------

const HOST_LABEL: Record<string, string> = {
  "aws-ec2": "AWS EC2",
  "ec2-mac": "EC2 Mac",
  "azure-vm": "Azure VM",
  gcp: "GCP",
};

/** The badge on a machine's card: its cloud when it said one, else its kind of computer. */
function badgeOf(m: RoomMachine): { text: string; tone: string } {
  const host = m.about?.host;
  if (host && HOST_LABEL[host]) return { text: HOST_LABEL[host]!, tone: host };
  const os = (m.about?.os ?? "").toLowerCase();
  if (os.includes("mac") || m.builds.includes("ios")) return { text: "Mac", tone: "mac" };
  if (os.includes("windows")) return { text: "Windows", tone: "plain" };
  if (os) return { text: "Linux", tone: "plain" };
  return { text: "PC", tone: "plain" };
}

/** The pill on a machine's card. */
function machineStatus(tx: T, m: RoomMachine): string {
  if (m.phase != null) return tx("phase {n}", { n: m.phase });
  if (m.elsewhere) return tx("busy");
  return m.online ? tx("idle") : tx("offline");
}

/** The line at the foot of a machine's card: what it last said, else what it is at. */
function machineDoing(tx: T, m: RoomMachine): string {
  if (m.doing) return m.doing;
  if (m.phase != null) return tx("writing phase {n}", { n: m.phase });
  if (m.elsewhere) return tx("writing another development");
  return m.online ? tx("asking for a phase it can do …") : tx("not connected");
}

/** What the machine is -- size, system, what writes on it -- else what it can do. */
function machineLine(m: RoomMachine): string {
  const what = [m.about?.size, m.about?.os, ...(m.about?.writers ?? [])].filter(Boolean);
  if (what.length > 0) return what.join(" · ");
  return m.writes.join(" · ") || m.builds.join(" · ");
}

function MachineCard({ machine: m }: Readonly<{ machine: RoomMachine }>) {
  const tx = useT();
  const badge = badgeOf(m);
  const line = machineLine(m);
  const status = machineStatus(tx, m);
  const doing = machineDoing(tx, m);
  return (
    <article
      data-room-key={m.id}
      className={`room-card ${m.phase != null ? "on" : ""} ${m.online ? "" : "off"}`}
    >
      <header>
        <span className={`room-badge ${badge.tone}`}>{badge.text}</span>
        <b className="room-card-name">{m.name}</b>
        <span className={`room-state ${m.phase != null ? "on" : ""}`}>{status}</span>
      </header>
      {line && <div className="room-card-sub">{line}</div>}
      <div className="room-card-doing">{doing}</div>
    </article>
  );
}

function ServerCard({ room }: Readonly<{ room: Room }>) {
  const tx = useT();
  const writing = room.server.writing;
  return (
    <article data-room-key="server" className={`room-card server ${writing.length ? "on" : ""}`}>
      <header>
        <span className="room-badge server">Slipwright</span>
        <b className="room-card-name">{tx("this server")}</b>
        <span className={`room-state ${writing.length ? "on" : ""}`}>
          {writing.length ? tx("{n} writing", { n: writing.length }) : tx("idle")}
        </span>
      </header>
      {room.server.models.length > 0 && (
        <div className="room-card-sub">{room.server.models.join(" · ")}</div>
      )}
      <div className="room-card-doing">
        {writing.length
          ? tx("writing phase(s) {list}", { list: writing.join(", ") })
          : tx("writes what no machine takes")}
      </div>
    </article>
  );
}

// -- the right: the branch ---------------------------------------------------------------

type Tone = "done" | "failed" | "turn" | "writing" | "parked" | "pending";

function toneOf(p: RoomPhase, turn: boolean): Tone {
  if (p.status === "done") return "done";
  if (p.status === "failed") return "failed";
  if (turn) return "turn";
  if (p.writing) return "writing";
  return p.parked ? "parked" : "pending";
}

/** The line under a finished phase: its commit, linked where the host shows it. */
function Committed({ phase: p }: Readonly<{ phase: RoomPhase }>) {
  const tx = useT();
  const sha = p.commit ? <code>{p.commit.slice(0, 7)}</code> : null;
  return (
    <>
      {sha && p.commit_url ? (
        <a href={p.commit_url} target="_blank" rel="noreferrer">
          {sha}
        </a>
      ) : (
        sha
      )}
      {sha && " · "}
      {p.by_hand ? tx("done by hand") : tx("built ✓ reviewed ✓")}
    </>
  );
}

function phaseMeta(tx: T, p: RoomPhase, tone: Tone, step: string | null | undefined): string {
  switch (tone) {
    case "failed":
      return tx("failed");
    case "turn":
      return stepLabel(tx, step);
    case "writing": {
      const who = p.writer ? [p.writer, p.doing] : [tx("the server")];
      return [tx("being written"), ...who].filter(Boolean).join(" · ");
    }
    case "parked":
      return tx("set aside");
    default:
      return tx("waiting its turn");
  }
}

function PhaseRow({ phase: p, room }: Readonly<{ phase: RoomPhase; room: Room }>) {
  const tx = useT();
  const say = useSay();
  const tone = toneOf(p, room.in_turn === p.number);
  return (
    <li className={`room-phase ${tone}`}>
      <span className="room-pin" aria-hidden="true" />
      <div>
        <div className="room-phase-title">
          {tx("Phase {n}", { n: p.number })} · {say(p.title)}
        </div>
        <div className="room-phase-meta">
          {tone === "done" ? <Committed phase={p} /> : phaseMeta(tx, p, tone, room.step)}
        </div>
      </div>
    </li>
  );
}
