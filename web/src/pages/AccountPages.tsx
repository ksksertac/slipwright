// The four pages a person meets before they have an account, or after they have lost the
// way back into one: sign up, confirm the address, ask for a reset link, set a new
// password. They share the login card's frame, so arriving from any of them feels like
// one place rather than four.
//
// Each of the last three is reached from a link in a letter, which carries the one-shot
// token as `?token=`. The token is read from the query string and never shown.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api, describeError, type InvitationView } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { AuthLangPicker } from "../components/LangPicker";
import { useAuth } from "../auth/AuthProvider";
import { currentLang, useT } from "../i18n";

/** The card every account page sits in. */
function Frame({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  const tx = useT();
  return (
    <div className="login-wrap">
      <div className="login card">
        <div className="brand">
          <BrandMark /> {tx("Slipwright")}
        </div>
        <h2 className="account-title">{title}</h2>
        {hint && <p className="muted small account-hint">{hint}</p>}
        {children}
      </div>
      <AuthLangPicker />
    </div>
  );
}

// -- signing up ---------------------------------------------------------------------------

export function SignupPage() {
  const tx = useT();
  const { user, signUp } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signUp(email, password, name);
      navigate("/verify", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame
      title={tx("Create an account")}
      hint={tx("You bring your own model keys; Slipwright runs the agents.")}
    >
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="email">{tx("Email")}</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="name">{tx("Your name")}</label>
          <input
            id="name"
            type="text"
            autoComplete="name"
            placeholder={tx("optional")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">{tx("Password")}</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="muted tiny">{tx("At least 8 characters.")}</span>
        </div>
        {error && <div className="callout error">{error}</div>}
        <button
          className="btn primary"
          type="submit"
          style={{ width: "100%" }}
          disabled={busy || !email || password.length < 8}
        >
          {busy ? tx("Creating…") : tx("Create account")}
        </button>
      </form>
      <p className="muted small account-foot">
        {tx("Already have an account?")} <Link to="/login">{tx("Sign in")}</Link>
      </p>
    </Frame>
  );
}

// -- confirming the address -----------------------------------------------------------------

export function VerifyEmailPage() {
  const tx = useT();
  const { user, unverified, verifyEmail } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  // arriving from the letter: redeem the token once, then go where the person was headed
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    verifyEmail(token)
      .then(() => {
        if (!cancelled) navigate("/", { replace: true });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token, verifyEmail, navigate]);

  if (user && !unverified && !token) return <Navigate to="/" replace />;

  const resend = async () => {
    if (!user?.email) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/resend-verification", {
        email: user.email,
        lang: currentLang(),
      });
      setSent(true);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (token && !error) {
    return <Frame title={tx("Confirming…")}>{null}</Frame>;
  }

  return (
    <Frame
      title={tx("Confirm your email")}
      hint={
        user?.email
          ? tx("We sent a link to {email}. Open it to finish setting up your account.", {
              email: user.email,
            })
          : tx("Open the link we sent you to finish setting up your account.")
      }
    >
      {error && <div className="callout error">{error}</div>}
      {sent && <div className="callout ok">{tx("Sent. Check your inbox.")}</div>}
      {user?.email && (
        <button
          className="btn"
          type="button"
          style={{ width: "100%" }}
          onClick={resend}
          disabled={busy}
        >
          {busy ? tx("Sending…") : tx("Send the link again")}
        </button>
      )}
      <p className="muted small account-foot">
        <Link to="/login">{tx("Back to sign in")}</Link>
      </p>
    </Frame>
  );
}

// -- forgetting the password ----------------------------------------------------------------

export function ForgotPasswordPage() {
  const tx = useT();
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/forgot-password", { email, lang: currentLang() });
      setDone(true);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  // the same words whether or not the address is known here: this page must not be a way
  // of finding out who has an account
  if (done) {
    return (
      <Frame
        title={tx("Check your inbox")}
        hint={tx("If that address has an account, a link is on its way.")}
      >
        <p className="muted small account-foot">
          <Link to="/login">{tx("Back to sign in")}</Link>
        </p>
      </Frame>
    );
  }

  return (
    <Frame
      title={tx("Forgot your password?")}
      hint={tx("We will mail you a link to set a new one.")}
    >
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="email">{tx("Email")}</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </div>
        {error && <div className="callout error">{error}</div>}
        <button
          className="btn primary"
          type="submit"
          style={{ width: "100%" }}
          disabled={busy || !email}
        >
          {busy ? tx("Sending…") : tx("Send the link")}
        </button>
      </form>
      <p className="muted small account-foot">
        <Link to="/login">{tx("Back to sign in")}</Link>
      </p>
    </Frame>
  );
}

// -- setting a new one ------------------------------------------------------------------------

export function ResetPasswordPage() {
  const tx = useT();
  const { resetPassword } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <Frame title={tx("This link is no longer valid")}>
        <p className="muted small account-foot">
          <Link to="/forgot-password">{tx("Ask for a new one")}</Link>
        </p>
      </Frame>
    );
  }

  return (
    <Frame
      title={tx("Set a new password")}
      hint={tx("Signing in everywhere else will need the new password.")}
    >
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="password">{tx("New password")}</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
          <span className="muted tiny">{tx("At least 8 characters.")}</span>
        </div>
        {error && <div className="callout error">{error}</div>}
        <button
          className="btn primary"
          type="submit"
          style={{ width: "100%" }}
          disabled={busy || password.length < 8}
        >
          {busy ? tx("Saving…") : tx("Save and sign in")}
        </button>
      </form>
    </Frame>
  );
}

// -- the invitation ---------------------------------------------------------------------------

/** What a link in an invitation letter opens onto.
 *
 * The person has no account to sign in with -- or rather, they have one already, made the
 * moment the letter went out, which is what has been holding their address. This page is
 * where they finish it: the agents they have been given are named, and they either choose
 * a password and start working, or say no. Reading the page does not spend the link, so a
 * letter opened on the wrong device is not lost.
 */
export function InvitationPage() {
  const tx = useT();
  const { user, acceptInvitation } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [invitation, setInvitation] = useState<InvitationView | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  // a link with no token at all is answered before anything is asked of the server
  const [error, setError] = useState<string | null>(
    token ? null : tx("This link is no longer valid."),
  );
  const [declined, setDeclined] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .post<InvitationView>("/api/auth/invitation", { token })
      .then((found) => {
        if (cancelled) return;
        setInvitation(found);
        setName(found.name);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (user) return <Navigate to="/" replace />;

  const accept = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await acceptInvitation(token, password, name);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const decline = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post<void>("/api/auth/decline-invitation", { token });
      setDeclined(true);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (declined) {
    return (
      <Frame title={tx("Declined")} hint={tx("Nothing has been shared with you.")}>
        <p className="muted small">
          {tx("We have told them. If you change your mind, ask them to invite you again.")}
        </p>
      </Frame>
    );
  }

  if (!invitation) {
    return (
      <Frame title={tx("Invitation")}>
        {error ? (
          <div className="callout error">{error}</div>
        ) : (
          <p className="muted">{tx("Loading…")}</p>
        )}
      </Frame>
    );
  }

  const agents = invitation.agents.join(", ");
  return (
    <Frame
      title={tx("You have been invited")}
      hint={tx("{inviter} would like you on the {agents} agent.", {
        inviter: invitation.inviter,
        agents,
      })}
    >
      <p className="muted small">
        {tx(
          "You will approve at that agent's gates, edit the work it proposes and see the team's projects. Nothing else on the account is yours to change.",
        )}
      </p>
      <form onSubmit={accept}>
        <div className="field">
          <label htmlFor="invited-email">{tx("Email")}</label>
          <input id="invited-email" type="email" value={invitation.email} readOnly disabled />
        </div>
        <div className="field">
          <label htmlFor="invited-name">{tx("Your name")}</label>
          <input
            id="invited-name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="invited-password">{tx("Choose a password")}</label>
          <input
            id="invited-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
          <span className="muted tiny">{tx("At least 8 characters.")}</span>
        </div>
        {error && <div className="callout error">{error}</div>}
        <button
          className="btn primary"
          type="submit"
          style={{ width: "100%" }}
          disabled={busy || password.length < 8}
        >
          {busy ? tx("Joining…") : tx("Accept and start")}
        </button>
      </form>
      <p className="muted small account-foot">
        <button className="btn ghost small" onClick={decline} disabled={busy}>
          {tx("Decline this invitation")}
        </button>
      </p>
    </Frame>
  );
}
