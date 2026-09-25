import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { describeError, takeSignedOutReason } from "../api/client";
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
  // why the last session ended, when the server thought it worth saying. Read once, on
  // the way in, so a browser that was open when somebody was taken off a team is not left
  // wondering what happened.
  const [signedOut] = useState(takeSignedOutReason);

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;
  if (user) return <Navigate to={from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from ?? "/", { replace: true });
    } catch (err) {
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
        <p className="muted small" style={{ textAlign: "center", marginBottom: 18 }}>
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
        {noUsers ? (
          <div className="callout hint" style={{ display: "block" }}>
            {tx("No login exists yet. Create the first (admin) user on the server:")}
            <pre style={{ marginTop: 8 }}>slipwright user add &lt;name&gt;</pre>
          </div>
        ) : (
          <form onSubmit={submit}>
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
            {error && <div className="callout error">{error}</div>}
            <button
              className="btn primary"
              type="submit"
              style={{ width: "100%" }}
              disabled={busy || !username || !password}
            >
              {busy ? tx("Signing in…") : tx("Sign in")}
            </button>
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
