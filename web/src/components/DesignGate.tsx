// The design gate: the screens the Designer drew, as pictures rather than as a description
// of pictures. Each one is its own little page, so it is rendered in a frame of its own --
// a document written by a model, served locked down and framed with no same-origin access,
// which is what `sandbox` here is for. Clicking a mock opens it at full size; from either
// place a screen is signed off or sent back with what should be different, and the
// development carries on as soon as the last one has a yes.
import { useEffect, useState } from "react";
import { describeError, type DesignScreen } from "../api/client";
import { useDesignReview, useReviewScreen } from "../api/hooks";
import { IconCheck, IconX } from "./icons";
import { Loading } from "./ui";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

/** The frame a mock is drawn in. `sandbox=""` is the whole point: no scripts, no forms, no
 * same-origin access, so the page cannot reach the session it is being shown inside. The
 * server sends a matching CSP; both are needed, neither is enough on its own. */
function Mock({
  jobId,
  screen,
  title,
  className,
  surface,
}: {
  jobId: string;
  screen: DesignScreen;
  title: string;
  className: string;
  /** Which drawing to ask for. A screen with one drawing answers the same either way. */
  surface?: string;
}) {
  if (!screen.has_mock) return <div className={`${className} mock-none`}>{title}</div>;
  const at = `/api/jobs/${jobId}/design/${encodeURIComponent(screen.id)}/mock`;
  return (
    <iframe
      className={className}
      src={surface ? `${at}?surface=${encodeURIComponent(surface)}` : at}
      sandbox=""
      referrerPolicy="no-referrer"
      loading="lazy"
      title={title}
    />
  );
}

/** What each surface is called on screen. A screen drawn for one platform has no tabs. */
const SURFACE_LABEL: Record<string, string> = { web: "Web", mobile: "Mobile" };

export function DesignGate({ jobId, readOnly = false }: { jobId: string; readOnly?: boolean }) {
  const tx = useT();
  const say = useSay();
  const review = useDesignReview(jobId);
  const [open, setOpen] = useState<string | null>(null);

  if (review.isLoading) return <Loading rows={3} />;
  if (!review.data || review.data.screens.length === 0) return null;
  const screens = review.data.screens;
  const left = screens.filter((s) => !s.approved).length;
  const shown = screens.find((s) => s.id === open) ?? null;

  return (
    <div className="design-gate">
      <div className="design-head">
        <div>
          <strong>{tx("The screens")}</strong>{" "}
          <span className="muted small">
            {left === 0
              ? tx("all {n} approved", { n: screens.length })
              : tx("{done} of {total} approved", {
                  done: screens.length - left,
                  total: screens.length,
                })}
          </span>
        </div>
        {!readOnly && left > 0 && (
          <span className="faint small">
            {tx(
              "The web and mobile phases start when every screen has a yes; the backend ones do not wait.",
            )}
          </span>
        )}
      </div>

      <ul className="mock-grid">
        {screens.map((screen) => (
          <li key={screen.id} className={`mock-card ${screen.approved ? "approved" : ""}`}>
            <button
              type="button"
              className="mock-open"
              onClick={() => setOpen(screen.id)}
              title={tx("Open the screen")}
            >
              <Mock jobId={jobId} screen={screen} title={say(screen.name)} className="mock-thumb" />
            </button>
            <div className="mock-id">
              <span className="mock-name">{say(screen.name)}</span>
              <span className={`badge plain ${screen.approved ? "ok" : "wait"}`}>
                {screen.approved ? tx("approved") : tx("waiting")}
              </span>
              <span className="chip idle">{screen.platform}</span>
            </div>
            {screen.feedback && (
              <div className="mock-asked">
                {tx("You asked for:")} {screen.feedback}
              </div>
            )}
            {!readOnly && !screen.approved && (
              <ScreenActions jobId={jobId} screen={screen} compact />
            )}
          </li>
        ))}
      </ul>

      {shown && (
        <MockModal jobId={jobId} screen={shown} readOnly={readOnly} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

/** Yes, or no with a reason. A screen sent back goes to the Designer on its own: the ones
 * already approved keep their yes and are not drawn (or paid for) again. */
function ScreenActions({
  jobId,
  screen,
  compact = false,
  onDone,
}: {
  jobId: string;
  screen: DesignScreen;
  compact?: boolean;
  onDone?: () => void;
}) {
  const tx = useT();
  const review = useReviewScreen(jobId);
  const [asking, setAsking] = useState(false);
  const [text, setText] = useState("");
  const size = compact ? "small" : "";

  return (
    <div className="mock-actions">
      {!asking ? (
        <>
          <button
            className={`btn ok ${size}`}
            disabled={review.isPending}
            onClick={() =>
              review.mutate({ id: screen.id, ok: true }, { onSuccess: () => onDone?.() })
            }
          >
            <IconCheck /> {tx("Approve")}
          </button>
          <button className={`btn bad ${size}`} onClick={() => setAsking(true)}>
            {tx("Not this — draw it again…")}
          </button>
        </>
      ) : (
        <>
          <input
            type="text"
            autoFocus
            placeholder={tx("what should be different?")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button
            className={`btn bad ${size}`}
            disabled={!text.trim() || review.isPending}
            onClick={() =>
              review.mutate(
                { id: screen.id, ok: false, feedback: text.trim() },
                {
                  onSuccess: () => {
                    setAsking(false);
                    setText("");
                    onDone?.();
                  },
                },
              )
            }
          >
            {tx("Send it back")}
          </button>
          <button className={`btn ghost ${size}`} onClick={() => setAsking(false)}>
            {tx("Cancel")}
          </button>
        </>
      )}
      {review.error && <span className="small bad-text">{describeError(review.error)}</span>}
    </div>
  );
}

/** The screen at full size, with the words that go with it: what it is for, and what is
 * still only written down -- the states and the controls the picture cannot show. */
function MockModal({
  jobId,
  screen,
  readOnly,
  onClose,
}: {
  jobId: string;
  screen: DesignScreen;
  readOnly: boolean;
  onClose: () => void;
}) {
  const tx = useT();
  const say = useSay();
  const surfaces = screen.surfaces ?? [];
  const [surface, setSurface] = useState(surfaces[0] ?? "");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="mock-backdrop" onClick={onClose} role="presentation">
      <div
        className="mock-modal"
        role="dialog"
        aria-label={say(screen.name)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mock-modal-head">
          <div style={{ minWidth: 0 }}>
            <h3 className="truncate">{say(screen.name)}</h3>
            {screen.purpose && <div className="muted small">{say(screen.purpose)}</div>}
          </div>
          <span className="chip idle">{screen.platform}</span>
          <button className="btn ghost icon" onClick={onClose} aria-label={tx("Close")}>
            <IconX />
          </button>
        </div>
        {/* one drawing per surface: the tabs appear only for a screen that has more than
            one, so a screen on a single platform looks exactly as it did */}
        {surfaces.length > 1 && (
          <div className="mock-surfaces" role="tablist" aria-label={tx("Surface")}>
            {surfaces.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={name === surface}
                className={name === surface ? "on" : ""}
                onClick={() => setSurface(name)}
              >
                {tx(SURFACE_LABEL[name] ?? name)}
              </button>
            ))}
          </div>
        )}
        <div className="mock-modal-body">
          <Mock
            jobId={jobId}
            screen={screen}
            title={say(screen.name)}
            className="mock-full"
            surface={surfaces.length > 1 ? surface : undefined}
          />
        </div>
        {!readOnly && !screen.approved && (
          <div className="mock-modal-foot">
            <span className="mock-ask">{tx("Is this the screen?")}</span>
            <ScreenActions jobId={jobId} screen={screen} onDone={onClose} />
          </div>
        )}
      </div>
    </div>
  );
}
