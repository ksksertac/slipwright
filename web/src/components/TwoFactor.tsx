// Two-step sign-in, set up: scan a code, show one back, keep the recovery codes.
//
// One component for the two places it is offered -- the setup wizard, where "skip for
// now" sits beside it, and the Security page, where it waits for whenever somebody wants
// it. Nothing about signing in changes until a code from the app has come back, so
// closing this half way leaves the account exactly as it was.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { describeError, type TwoFactorSetup as Setup } from "../api/client";
import { useEnableTwoFactor, useStartTwoFactor, useTwoFactorChanged } from "../api/hooks";
import { useT } from "../i18n";
import { IconCheck } from "./icons";

export function TwoFactorSetup({ onDone }: { onDone?: () => void }) {
  const tx = useT();
  const start = useStartTwoFactor();
  const enable = useEnableTwoFactor();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);

  // a secret is asked for when this appears, not before: the wizard renders it only on
  // its own step, so passing through the wizard does not mint secrets nobody scans
  const begin = start.mutate;
  useEffect(() => {
    begin(undefined, { onSuccess: setSetup });
  }, [begin]);

  // the rest of the application hears that it is on once the codes are off the screen --
  // whichever way they leave it: "I have saved them", the wizard closed, a page changed
  const changed = useRef(useTwoFactorChanged());
  const on = recovery !== null;
  useEffect(() => {
    if (!on) return;
    const tell = changed.current;
    return () => tell();
  }, [on]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    enable.mutate(code.trim(), { onSuccess: (r) => setRecovery(r.recovery_codes) });
  };

  if (recovery) return <RecoveryCodes codes={recovery} onDone={onDone} />;
  if (start.error) return <div className="callout error">{describeError(start.error)}</div>;
  if (!setup) return <div className="muted small">{tx("Loading…")}</div>;

  return (
    <div className="twofa">
      <ol className="twofa-steps muted small">
        <li>
          {tx(
            "Open an authenticator app on your phone — Google Authenticator, Microsoft Authenticator, 1Password or any other.",
          )}
        </li>
        <li>{tx("Scan this code with it.")}</li>
        <li>{tx("Type the six digits it shows.")}</li>
      </ol>
      <img className="twofa-qr" src={setup.qr} alt={tx("QR code for your authenticator app")} />
      <details className="twofa-manual">
        <summary className="small muted">{tx("Cannot scan? Enter the key by hand")}</summary>
        <code className="twofa-secret">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
      </details>
      <form className="row twofa-confirm" onSubmit={submit}>
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          maxLength={8}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          aria-label={tx("Code from the app")}
        />
        <button
          className="btn primary"
          type="submit"
          disabled={code.trim().length < 6 || enable.isPending}
        >
          {tx("Turn on")}
        </button>
      </form>
      {enable.error && <div className="callout error">{describeError(enable.error)}</div>}
    </div>
  );
}

/** Shown once, the moment it is turned on: nobody, including the server, can show them
 *  again -- only their hashes are kept. */
function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone?: () => void }) {
  const tx = useT();
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // no clipboard on plain http: the codes are on screen to be written down
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([text + "\n"], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "slipwright-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="twofa">
      <div className="wizard-done">
        <IconCheck /> {tx("Two-step sign-in is on.")}
      </div>
      <p className="muted small">
        {tx(
          "Keep these recovery codes somewhere safe. Each one gets you in once if you lose your phone. They will not be shown again.",
        )}
      </p>
      <ul className="twofa-codes">
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ul>
      <div className="row" style={{ justifyContent: "center", gap: 8 }}>
        <button className="btn" type="button" onClick={() => void copy()}>
          {copied ? tx("Copied") : tx("Copy")}
        </button>
        <button className="btn" type="button" onClick={download}>
          {tx("Download")}
        </button>
        {onDone && (
          <button className="btn primary" type="button" onClick={onDone}>
            {tx("I have saved them")}
          </button>
        )}
      </div>
    </div>
  );
}
