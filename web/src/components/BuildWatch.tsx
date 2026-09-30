// The version corner. Two different "new versions" meet here, and they are not the same:
//
// - the page is older than the server: a deploy happened under an open tab, and the tab
//   is still running the bundle it loaded. Reloading is the whole fix.
// - the server is older than the newest release: somebody has to install it. Anybody using
//   the screen may, with one press; the server pulls the release and restarts on it,
//   keeping every project, setting and development (slipwright/update.py).
import { useEffect, useRef, useState } from "react";
import { api, describeError } from "../api/client";
import type { UpdateStatus, Version } from "../api/client";
import { useT } from "../i18n";

const EVERY_MS = 60_000;
// while an install is under way the server goes away and comes back; asked often, so the
// page picks up the new version the moment it answers
const INSTALLING_MS = 3_000;

export function BuildWatch() {
  const tx = useT();
  const loaded = useRef<string | null>(null);
  const [stale, setStale] = useState(false);
  const [build, setBuild] = useState("");
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  // pressed on this page: from here on, the server answering with another version is
  // the install finishing, and the page reloads by itself
  const [installing, setInstalling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showHow, setShowHow] = useState(false);

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
        if (loaded.current === null) loaded.current = v.build;
        else if (loaded.current !== v.build) setStale(true);
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

  const install = async (u: UpdateStatus, version: string) => {
    const lines = [
      tx(
        "Install version {v}? The server restarts on it; projects, settings and history are kept.",
        { v: version },
      ),
    ];
    if (u.running_jobs > 0)
      lines.push(
        tx("{n} development(s) running now will carry on from the step they were on.", {
          n: u.running_jobs,
        }),
      );
    if (u.backup) lines.push(tx("A copy of the database is taken first."));
    if (!window.confirm(lines.join("\n\n"))) return;
    setError(null);
    try {
      setUpdate(await api.post<UpdateStatus>("/api/update", { version }));
      setInstalling(version);
    } catch (e) {
      setError(describeError(e));
    }
  };

  const stamp = (
    <div className="faint tiny build-stamp">
      {update ? tx("version {v} · build {id}", { v: update.current, id: build }) : null}
      {!update && build ? tx("build {id}", { id: build }) : null}
    </div>
  );
  const offer = update?.latest ? renderOffer(update, update.latest) : null;

  function renderOffer(u: UpdateStatus, version: string) {
    const busy = installing !== null || u.state === "pulling" || u.state === "restarting";
    const failed = error ?? (u.state === "failed" ? u.error : null);
    return (
      <div className="build-update">
        {busy ? (
          <button className="btn small build-stale" disabled>
            <span className="spinner" />
            {u.state === "pulling"
              ? tx("Downloading version {v}…", { v: version })
              : tx("Restarting on version {v}…", { v: version })}
          </button>
        ) : (
          <button
            className="btn small primary build-stale"
            onClick={() => (u.can_install ? void install(u, version) : setShowHow(!showHow))}
          >
            {tx("Install version {v}", { v: version })}
          </button>
        )}
        {u.notes_url ? (
          <a className="faint tiny build-notes" href={u.notes_url} target="_blank" rel="noreferrer">
            {tx("What's new")}
          </a>
        ) : null}
        {failed && !busy ? (
          <div className="tiny build-error">{tx("The update failed: {error}", { error: failed })}</div>
        ) : null}
        {showHow && !u.can_install ? (
          <div className="tiny build-how">
            {u.blocked === "source"
              ? tx("This server runs from source. Update it with:")
              : tx(
                  "This server cannot reach Docker, so it cannot install by itself. Mount /var/run/docker.sock into its container, or run:",
                )}
            <code>{u.command}</code>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <>
      {stamp}
      {stale && !installing ? (
        <button className="btn small primary build-stale" onClick={() => window.location.reload()}>
          {tx("New version — reload")}
        </button>
      ) : null}
      {offer}
    </>
  );
}
