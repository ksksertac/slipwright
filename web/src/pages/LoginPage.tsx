import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { describeError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function LoginPage() {
  const { user, login, noUsers } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
          <span className="brand-mark">⛵</span> Slipwright
        </div>
        <p className="muted small" style={{ textAlign: "center", marginBottom: 18 }}>
          Multi-agent delivery, with you at every gate.
        </p>
        {noUsers ? (
          <div className="callout hint" style={{ display: "block" }}>
            No login exists yet. Create the first (admin) user on the server:
            <pre style={{ marginTop: 8 }}>slipwright user add &lt;name&gt;</pre>
          </div>
        ) : (
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="username">Username</label>
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
              <label htmlFor="password">Password</label>
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
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
