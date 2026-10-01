// The version corner: the server is older than the newest release and somebody has to
// install it. (A tab older than the server -- a rebuild under an open page -- once had a
// "reload" button of its own here; sitting beside this one it read as a second, duplicate
// offer, so it went. A reload is a keypress away.) The corner
//   says so in two words; the dialog behind it says what the release is, what changes
//   and what happens on "Update now" -- the server pulls it and restarts on it, keeping
//   every project, setting and development (slipwright/update.py). Anybody using the
//   screen may press it.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, describeError } from "../api/client";
import type { UpdateStatus, Version } from "../api/client";
import { useT } from "../i18n";
import { Markdown } from "../pages/AgentStandardsTab";
import { Copyable } from "./Copyable";
import { IconExternal } from "./icons";
import { Modal } from "./Modal";
import { timeAgo } from "./ui";

const EVERY_MS = 60_000;
// while an install is under way the server goes away and comes back; asked often, so the
// page picks up the new version the moment it answers
const INSTALLING_MS = 3_000;

export function BuildWatch() {
  const tx = useT();
  const [build, setBuild] = useState("");
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [open, setOpen] = useState(false);
  // pressed on this page: from here on, the server answering with another version is
  // the install finishing, and the page reloads by itself
  const [installing, setInstalling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const [v, u] = await Promise.all([
          api.get<Version>("/api/version"),
          api.get<UpdateStatus>("/api/update"),
        ]);
        if (!alive) return;
        setBuild(v.build);
        setUpdate(u);
      } catch {
        /* offline or restarting: ask again on the next tick */
      }
    };
    void check();
    const id = window.setInterval(() => void check(), installing ? INSTALLING_MS : EVERY_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [installing]);

  useEffect(() => {
    if (!installing || !update) return;
    if (update.current === installing) window.location.reload();
    // the new version never came up and the old one is back, saying why
    else if (update.state === "failed") {
      setInstalling(null);
      setError(update.error ?? null);
    }
  }, [installing, update]);

  const busy = installing !== null || update?.state === "pulling" || update?.state === "restarting";

  const install = async (version: string) => {
    setError(null);
    try {
      setUpdate(await api.post<UpdateStatus>("/api/update", { version }));
      setInstalling(version);
    } catch (e) {
      setError(describeError(e));
    }
  };

  return (
    <>
      {/* one child of the sidebar, not three: each child is spaced like a section, and the
          version with its buttons is one small thing -- spaced apart, the button arriving
          with a new release pushed the menu into a scrollbar */}
      <div className="build-corner">
        {/* the version is what a person reads; the build id only tells two builds of it
            apart, so it waits under the pointer rather than taking a line of the corner */}
        <div
          className="faint tiny build-stamp"
          title={update && build ? tx("build {id}", { id: build }) : undefined}
        >
          {update
            ? tx("version {v}", { v: update.current })
            : build
              ? tx("build {id}", { id: build })
              : null}
        </div>
        {update?.latest ? (
          <button className="btn small build-stale build-offer" onClick={() => setOpen(true)}>
            <span className="build-dot" />
            {busy ? tx("Updating…") : tx("New version · {v}", { v: update.latest })}
          </button>
        ) : null}
      </div>
      {/* into the body, not the sidebar: a sticky sidebar is a stacking context of its
          own, and the page beside it painted over a dialog kept inside it */}
      {open && update?.latest
        ? createPortal(
            <UpdateDialog
              update={update}
              version={update.latest}
              busy={busy}
              error={error ?? (update.state === "failed" ? update.error : null) ?? null}
              onInstall={() => void install(update.latest as string)}
              onClose={() => setOpen(false)}
            />,
            document.body,
          )
        : null}
    </>
  );
}

function UpdateDialog({
  update,
  version,
  busy,
  error,
  onInstall,
  onClose,
}: {
  update: UpdateStatus;
  version: string;
  busy: boolean;
  error: string | null;
  onInstall: () => void;
  onClose: () => void;
}) {
  const tx = useT();
  return (
    <Modal
      title={tx("New version")}
      onClose={onClose}
      footer={
        update.can_install ? (
          <>
            <button className="btn" onClick={onClose}>
              {busy ? tx("Close") : tx("Later")}
            </button>
            <button className="btn primary" disabled={busy} onClick={onInstall}>
              {busy ? tx("Updating…") : tx("Update now")}
            </button>
          </>
        ) : (
          <button className="btn" onClick={onClose}>
            {tx("Close")}
          </button>
        )
      }
    >
      <div className="update-versions">
        <div>
          <div className="faint tiny">{tx("Installed")}</div>
          <div className="update-version">{update.current}</div>
        </div>
        <div className="update-arrow faint">→</div>
        <div>
          <div className="faint tiny">{tx("New version")}</div>
          <div className="update-version new">{version}</div>
          {update.published_at ? (
            <div className="faint tiny">
              {tx("released {when}", { when: timeAgo(update.published_at) })}
            </div>
          ) : null}
        </div>
      </div>

      <div className="update-notes-head">
        <h4>{tx("What's new")}</h4>
        {update.notes_url ? (
          <a className="tiny" href={update.notes_url} target="_blank" rel="noreferrer">
            {tx("On GitHub")} <IconExternal />
          </a>
        ) : null}
      </div>
      <div className="update-notes">
        {update.notes ? (
          <Markdown text={update.notes} />
        ) : (
          <div className="faint small">{tx("No notes were written for this release.")}</div>
        )}
      </div>

      {busy ? (
        <div className="callout notice update-progress">
          <span className="build-dot" />
          <div>
            {update.state === "pulling"
              ? tx("Downloading version {v}…", { v: version })
              : tx("Restarting on version {v}…", { v: version })}{" "}
            {tx("The page reloads by itself when it is ready.")}
          </div>
        </div>
      ) : update.can_install ? (
        <ul className="update-facts small">
          <li>
            {tx(
              "The server restarts on the new version; it takes a minute or two. Projects, settings and history are kept.",
            )}
          </li>
          {update.running_jobs > 0 ? (
            <li>
              {tx("{n} development(s) running now will carry on from the step they were on.", {
                n: update.running_jobs,
              })}
            </li>
          ) : null}
          {update.backup ? <li>{tx("A copy of the database is taken first.")}</li> : null}
          <li>{tx("If the new version does not start, the old one is put back by itself.")}</li>
        </ul>
      ) : (
        <div className="callout hint update-how">
          <div>
            {update.blocked === "source"
              ? tx("This server runs from source. Update it with:")
              : tx(
                  "This server cannot reach Docker, so it cannot install by itself. Mount /var/run/docker.sock into its container, or run:",
                )}
            <Copyable text={update.command}>
              <pre>{update.command}</pre>
            </Copyable>
          </div>
        </div>
      )}

      {error && !busy ? (
        <div className="callout error">{tx("The update failed: {error}", { error })}</div>
      ) : null}
    </Modal>
  );
}
