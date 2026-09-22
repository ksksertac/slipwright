// A page kept open across a deploy is still running the bundle it loaded. The server
// says which build it serves; when that changes, the page offers to reload rather than
// quietly showing yesterday's UI.
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Version } from "../api/client";
import { useT } from "../i18n";

const EVERY_MS = 60_000;

export function BuildWatch() {
  const tx = useT();
  const loaded = useRef<string | null>(null);
  const [stale, setStale] = useState(false);
  const [build, setBuild] = useState("");

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const v = await api.get<Version>("/api/version");
        if (!alive) return;
        setBuild(v.build);
        if (loaded.current === null) loaded.current = v.build;
        else if (loaded.current !== v.build) setStale(true);
      } catch {
        /* offline or restarting: ask again on the next tick */
      }
    };
    void check();
    const id = window.setInterval(() => void check(), EVERY_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!stale)
    return <div className="faint tiny build-stamp">{tx("build {id}", { id: build })}</div>;
  return (
    <button className="btn small primary build-stale" onClick={() => window.location.reload()}>
      {tx("New version — reload")}
    </button>
  );
}
