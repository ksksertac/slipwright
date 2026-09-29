// The person's own sign-in: two-step, whoever they are -- owner, member or administrator.
//
// It is the one setting that belongs to a *person* rather than to the account, which is
// why it has a page of its own outside Settings: somebody on a team has no Settings, and
// still has a password worth protecting.
import { useState, type FormEvent } from "react";
import { describeError } from "../api/client";
import { useDisableTwoFactor, useTwoFactor } from "../api/hooks";
import { TwoFactorSetup } from "../components/TwoFactor";
import { IconCheck } from "../components/icons";
import { ErrorBox, Loading, PageHead } from "../components/ui";
import { useT } from "../i18n";

export function SecurityPage() {
  const tx = useT();
  const status = useTwoFactor();
  const [setting, setSetting] = useState(false);

  if (status.isLoading) return <Loading rows={2} />;
  if (status.error) return <ErrorBox error={status.error} />;
  const s = status.data!;

  return (
    <>
      <PageHead
        title={tx("Security")}
        subtitle={tx("How you sign in. Yours alone: nobody else on the account can see it.")}
      />
      <section className="card">
        <div className="card-head">
          <h3>{tx("Two-step sign-in")}</h3>
          <span className={`badge plain ${s.enabled ? "ok" : "idle"}`}>
            {s.enabled ? tx("on") : tx("off")}
          </span>
        </div>
        <div className="card-body">
          <p className="muted small">
            {tx(
              "After your password, a six-digit code from an app on your phone. Somebody who learns your password still cannot get in.",
            )}
          </p>
          {s.enabled ? (
            <TurnOff codesLeft={s.recovery_codes_left} />
          ) : setting ? (
            <TwoFactorSetup onDone={() => setSetting(false)} />
          ) : (
            <button className="btn primary" type="button" onClick={() => setSetting(true)}>
              {tx("Set up two-step sign-in")}
            </button>
          )}
        </div>
      </section>
    </>
  );
}

function TurnOff({ codesLeft }: { codesLeft: number }) {
  const tx = useT();
  const off = useDisableTwoFactor();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    off.mutate({ password, code: code.trim() });
  };
  return (
    <>
      <div className="wizard-done" style={{ marginBottom: 8 }}>
        <IconCheck /> {tx("Signing in asks for a code from your app.")}
      </div>
      <p className={`small ${codesLeft <= 2 ? "" : "muted"}`}>
        {tx("{n} recovery code(s) left.", { n: codesLeft })}
        {codesLeft <= 2 && " " + tx("Running low: turn it off and on again for a fresh set.")}
      </p>
      <details>
        <summary className="small muted">{tx("Turn two-step sign-in off")}</summary>
        <form className="row" style={{ marginTop: 10, flexWrap: "wrap" }} onSubmit={submit}>
          <input
            type="password"
            autoComplete="current-password"
            placeholder={tx("Password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder={tx("Code or recovery code")}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button
            className="btn bad"
            type="submit"
            disabled={!password || !code.trim() || off.isPending}
          >
            {tx("Turn off")}
          </button>
        </form>
        {off.error && <div className="callout error">{describeError(off.error)}</div>}
      </details>
    </>
  );
}
