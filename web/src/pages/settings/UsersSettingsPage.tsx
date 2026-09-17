import { useState, type FormEvent } from "react";
import { describeError, type User } from "../../api/client";
import {
  useCreateUser,
  useDeleteUser,
  useIssueToken,
  useRevokeToken,
  useSetPassword,
  useTokens,
  useUsers,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, formatTime } from "../../components/ui";

export function UsersSettingsPage() {
  const { user: me } = useAuth();
  const users = useUsers();
  const create = useCreateUser();
  const remove = useDeleteUser();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  if (!me?.is_admin) return <div className="error">Admins only.</div>;
  if (users.isLoading) return <Loading />;
  if (users.error) return <ErrorBox error={users.error} />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { username: username.trim(), password, is_admin: isAdmin },
      {
        onSuccess: () => {
          setUsername("");
          setPassword("");
          setIsAdmin(false);
        },
      },
    );
  };

  return (
    <div>
      <h1>Users</h1>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.data!.map((u) => (
              <UserRow
                key={u.id}
                user={u}
                me={me}
                open={open === u.id}
                onToggle={() => setOpen(open === u.id ? null : u.id)}
                onDelete={() => remove.mutate(u.id)}
              />
            ))}
          </tbody>
        </table>
        {remove.error && <div className="error small">{describeError(remove.error)}</div>}
      </div>

      <form className="form card" onSubmit={submit} style={{ marginTop: 16 }}>
        <h3>Add user</h3>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="new-username">Username</label>
            <input
              id="new-username"
              type="text"
              autoComplete="off"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="new-password">Password</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>
        <label className="row" style={{ marginBottom: 10 }}>
          <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />{" "}
          admin
        </label>
        {create.error && <div className="error">{describeError(create.error)}</div>}
        <button
          className="btn primary"
          disabled={!username.trim() || !password || create.isPending}
        >
          Add user
        </button>
      </form>
    </div>
  );
}

function UserRow({
  user,
  me,
  open,
  onToggle,
  onDelete,
}: {
  user: User;
  me: User;
  open: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <tr className="clickable" onClick={onToggle}>
        <td>
          <strong>{user.username}</strong>
          {user.id === me.id && <span className="tag">you</span>}
        </td>
        <td>{user.is_admin ? "admin" : "member"}</td>
        <td className="muted small">{formatTime(user.created_at)}</td>
        <td style={{ textAlign: "right" }}>
          <button className="btn small" onClick={onToggle}>
            {open ? "close" : "manage"}
          </button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4}>
            <UserDetails user={user} me={me} onDelete={onDelete} />
          </td>
        </tr>
      )}
    </>
  );
}

function UserDetails({ user, me, onDelete }: { user: User; me: User; onDelete: () => void }) {
  const setPassword = useSetPassword();
  const tokens = useTokens(user.id);
  const issue = useIssueToken(user.id);
  const revoke = useRevokeToken(user.id);
  const [password, setPasswordValue] = useState("");
  const [label, setLabel] = useState("cli");
  const [secret, setSecret] = useState<string | null>(null);

  return (
    <div className="grid-2">
      <div>
        <h3>Reset password</h3>
        <p className="muted small">Ends every session and revokes every token of the user.</p>
        <div className="row">
          <input
            type="password"
            autoComplete="new-password"
            placeholder="new password"
            value={password}
            onChange={(e) => setPasswordValue(e.target.value)}
          />
          <button
            className="btn small"
            disabled={!password || setPassword.isPending}
            onClick={() =>
              setPassword.mutate(
                { id: user.id, password },
                { onSuccess: () => setPasswordValue("") },
              )
            }
          >
            Set
          </button>
        </div>
        {setPassword.isSuccess && <div className="notice small">Password changed.</div>}
        {setPassword.error && <div className="error small">{describeError(setPassword.error)}</div>}
        {user.id !== me.id && (
          <div style={{ marginTop: 16 }}>
            <button
              className="btn bad small"
              onClick={() => {
                if (window.confirm(`Delete user ${user.username}?`)) onDelete();
              }}
            >
              Delete user
            </button>
          </div>
        )}
      </div>
      <div>
        <h3>API tokens</h3>
        <p className="muted small">
          For the CLI: <code>slipwright --token … status</code> or <code>SLIPWRIGHT_TOKEN</code>.
        </p>
        {tokens.data && tokens.data.length > 0 && (
          <table>
            <tbody>
              {tokens.data.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td className="muted small">
                    {t.revoked_at
                      ? `revoked ${formatTime(t.revoked_at)}`
                      : t.last_used_at
                        ? `used ${formatTime(t.last_used_at)}`
                        : "never used"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {!t.revoked_at && (
                      <button className="btn small bad" onClick={() => revoke.mutate(t.id)}>
                        revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <input
            type="text"
            placeholder="label"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            style={{ width: 160 }}
          />
          <button
            className="btn small"
            disabled={issue.isPending}
            onClick={() =>
              issue.mutate(label.trim() || "cli", { onSuccess: (r) => setSecret(r.secret) })
            }
          >
            Issue token
          </button>
        </div>
        {secret && (
          <div className="notice small">
            Copy it now; it will not be shown again:
            <pre style={{ marginTop: 6 }}>{secret}</pre>
          </div>
        )}
        {(issue.error || revoke.error) && (
          <div className="error small">{describeError(issue.error ?? revoke.error)}</div>
        )}
      </div>
    </div>
  );
}
