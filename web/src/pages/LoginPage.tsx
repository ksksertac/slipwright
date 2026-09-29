import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError, describeError, takeSignedOutReason } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { AuthLangPicker } from "../components/LangPicker";
import { useAuth } from "../auth/AuthProvider";
import { useT } from "../i18n";

export function LoginPage() {
  const tx = useT();
  const { user, login, noUsers } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // the second step, once the server has said the password was right and a code is
  // what is missing. The password stays in memory to be sent again with it: the server
  // keeps no half-signed-in state between the two.
  const [asking, setAsking] = useState(false);
  const [code, setCode] = useState("");
  // why the last session ended, when the server thought it worth saying. Read once, on
  // the way in, so a browser that was open when somebody was taken off a team is not left
  // wondering what happened.
  const [signedOut] = useState(takeSignedOutReason);
  // A server nobody has signed into yet starts with one account and says what it is, so
  // that starting it is the whole of the setup. The fields are filled in: the person is
  // one click from looking at the thing, and one banner from being told to change it.
  const [starting, setStarting] = useState<{ username: string; password: string } | null>(null);
  useEffect(() => {
    let watching = true;
    api
      .get<{ default_admin: boolean; username: string; password: string }>("/api/auth/first-run")
      .then((answer) => {
        if (!watching || !answer.default_admin) return;
        setStarting({ username: answer.username, password: answer.password });
        setUsername((typed) => typed || answer.username);
        setPassword((typed) => typed || answer.password);
      })
      .catch(() => undefined); // an older server has no such endpoint, which is fine
    return () => {
      watching = false;
    };
  }, []);

  const arrived = location.state as { from?: { pathname: string }; twoFactor?: boolean } | null;
  const from = arrived?.from?.pathname;
  // sent here from a letter's link that did its work but, for an account with two-step
  // sign-in, could not sign in by itself
  const afterLink = arrived?.twoFactor === true;
  if (user) return <Navigate to={from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password, asking ? code.trim() : undefined);
      navigate(from ?? "/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.twoFactor === "required" && !asking) {
        setAsking(true);
        return;
      }
      if (err instanceof ApiError && err.twoFactor === "invalid") setCode("");
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login card">
        <div className="brand">
          <BrandMark /> {tx("Slipwright")}
        </div>
        <h2 className="account-title">{asking ? tx("One more step") : tx("Welcome back")}</h2>
        <p className="muted small account-hint">
          {tx("Multi-agent delivery, with you at every gate.")}
        </p>
        {signedOut === "removed" && (
          <div className="callout error" style={{ display: "block" }}>
            {tx("You have been taken off this team's agents, so you are signed out.")}
          </div>
        )}
        {signedOut === "invited" && (
          <div className="callout hint" style={{ display: "block" }}>
            {tx("Accept your invitation first: the link is in the letter we sent you.")}
          </div>
        )}
        {afterLink && !asking && (
          <div className="callout notice" style={{ display: "block" }}>
            {tx("Done. Now sign in — your account asks for the code from your app as well.")}
          </div>
        )}
        {starting && (
          <div className="callout hint" style={{ display: "block" }}>
            {tx("Nobody has signed in here yet, so this server made you an account:")}
            <pre style={{ marginTop: 8 }}>
              {starting.username} / {starting.password}
            </pre>
            {tx("It is filled in below. Change it under Users once you are in.")}
          </div>
        )}
        {noUsers && !starting ? (
          /* A server that was told not to make a starting account. The first one anybody
             creates is the administrator's, and it happens here rather than in a terminal */
          <div className="callout hint" style={{ display: "block" }}>
            {tx("Nobody has an account here yet. The first one is the administrator's.")}
            <div className="row" style={{ marginTop: 10 }}>
              <Link className="btn primary" to="/signup">
                {tx("Create the first account")}
              </Link>
            </div>
            <details style={{ marginTop: 10 }}>
              <summary className="small muted">{tx("Or on the server itself")}</summary>
              <pre style={{ marginTop: 8 }}>slipwright user add &lt;name&gt;</pre>
            </details>
          </div>
        ) : (
          <form onSubmit={submit}>
            {asking ? (
              <div className="field">
                <label htmlFor="code">{tx("Code from your authenticator app")}</label>
                <input
                  id="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  autoFocus
                />
                <div className="muted small" style={{ marginTop: 6 }}>
                  {tx("Lost your phone? A recovery code works here too.")}
                </div>
              </div>
            ) : (
              <>
                <div className="field">
                  <label htmlFor="username">{tx("Email")}</label>
                  <input
                    id="username"
                    type="text"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="field">
                  <label htmlFor="password">{tx("Password")}</label>
                  <input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
              </>
            )}
            {error && <div className="callout error">{error}</div>}
            <button
              className="btn primary"
              type="submit"
              style={{ width: "100%" }}
              disabled={busy || !username || !password || (asking && !code.trim())}
            >
              {busy ? tx("Signing in…") : asking ? tx("Verify") : tx("Sign in")}
            </button>
            {asking && (
              <button
                className="text-btn tiny"
                type="button"
                style={{ display: "block", margin: "10px auto 0" }}
                onClick={() => {
                  setAsking(false);
                  setCode("");
                  setError(null);
                }}
              >
                {tx("Sign in as somebody else")}
              </button>
            )}
            <p className="muted small account-foot">
              <Link to="/forgot-password">{tx("Forgot your password?")}</Link>
              <span className="account-sep">·</span>
              <Link to="/signup">{tx("Create an account")}</Link>
            </p>
          </form>
        )}
      </div>
      <AuthLangPicker />
    </div>
  );
}
