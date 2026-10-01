// The Macs this account lends its developments (T14.5). An iOS app is built by Xcode, and
// Xcode runs only on macOS -- which no container can hold -- so a development with an iOS
// app waits for one of these. The page is two things: a code to carry to the Mac, and the
// Macs already paired, with whether each is there right now.
import { useEffect, useState } from "react";
import { describeError, type ConnectionCode, type Worker } from "../../api/client";
import { useConnectionCode, useRevokeWorker, useWorkers } from "../../api/hooks";
import { Copyable } from "../../components/Copyable";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { useT } from "../../i18n";

const NAMES: Record<string, string> = { ios: "iOS", android: "Android" };

export function WorkersPage() {
  const tx = useT();
  const workers = useWorkers();
  return (
    <div>
      <PageHead
        title={tx("Mac Connect")}
        subtitle={tx(
          "Machines that build what this server cannot: iOS apps, and Android on Apple Silicon.",
        )}
      />
      <p className="muted">
        {tx(
          "Docker runs Linux, and an iOS app is built with Xcode, which runs only on macOS. So a Mac connects here with Mac Connect and does that build in Xcode. A development with an iOS app builds everything else here, then waits for a Mac; connect one and it carries on by itself. The Mac calls this server -- nothing is opened on it -- and builds only this account's apps.",
        )}
      </p>
      <ConnectMac />
      <h3 style={{ marginTop: 24 }}>{tx("Connected Macs")}</h3>
      {workers.isLoading && <Loading />}
      {workers.error && <ErrorBox error={workers.error} />}
      {workers.data && workers.data.length === 0 && <p className="muted">{tx("None yet.")}</p>}
      <div className="stack tight">
        {(workers.data ?? []).map((w) => (
          <WorkerRow key={w.id} worker={w} />
        ))}
      </div>
    </div>
  );
}

function ConnectMac() {
  const tx = useT();
  const make = useConnectionCode();
  const code = make.data;
  // the page's own address is all the server needs: at localhost the code carries only
  // the port, and the Mac finds the server on its own network
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="row spread">
        <strong>{tx("Connect a Mac")}</strong>
        <button
          className="btn primary small"
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
    <ol className="stack tight" style={{ marginTop: 12, paddingLeft: 18 }}>
      <li>
        {tx("On the Mac, install Slipwright (once):")}
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

function WorkerRow({ worker: w }: { worker: Worker }) {
  const tx = useT();
  const revoke = useRevokeWorker();
  return (
    <div className="card row spread" style={{ padding: "10px 14px" }}>
      <span className="row" style={{ gap: 8 }}>
        <strong>{w.name}</strong>
        {w.capabilities.length === 0 && (
          <span className="tag" title={tx("It found no Xcode and no Android SDK")}>
            {tx("builds nothing yet")}
          </span>
        )}
        {w.capabilities.map((c) => (
          <span key={c} className="tag">
            {NAMES[c] ?? c}
          </span>
        ))}
      </span>
      <span className="row" style={{ gap: 8 }}>
        <span className={`badge ${w.online ? "ok" : "idle"} plain`}>
          {w.online ? tx("online") : tx("offline")}
        </span>
        <button
          className="btn bad small"
          disabled={revoke.isPending}
          onClick={() => {
            if (window.confirm(tx("Remove this Mac? It stops building for this account."))) {
              revoke.mutate(w.id);
            }
          }}
        >
          {tx("Remove")}
        </button>
      </span>
    </div>
  );
}
