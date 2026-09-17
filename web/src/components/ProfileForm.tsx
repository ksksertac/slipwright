import type { Permission, Profile, RoleConfig } from "../api/client";

const ROLES = ["analyst", "planner", "developer", "qa", "devops"] as const;
const DEPTHS = ["off", "low", "medium", "high", "max"] as const;
const PERMISSIONS: Permission[] = [
  "read_files",
  "write_files",
  "run_commands",
  "network",
  "git_push",
  "jira",
];

/**
 * Editable project profile: build/test/run commands and, per role, model, thinking depth
 * and permissions. Used for a job's proposed profile and for a project's seed profile.
 */
export function ProfileForm({
  value,
  onChange,
  disabled = false,
}: {
  value: Profile;
  onChange: (next: Profile) => void;
  disabled?: boolean;
}) {
  const set = (patch: Partial<Profile>) => onChange({ ...value, ...patch });
  const roleOf = (role: (typeof ROLES)[number]): RoleConfig =>
    value.roles[role] ?? { model: "", thinking_depth: "medium", permissions: [] };
  const setRole = (role: (typeof ROLES)[number], patch: Partial<RoleConfig>) =>
    onChange({ ...value, roles: { ...value.roles, [role]: { ...roleOf(role), ...patch } } });

  return (
    <div className="stack">
      <div className="grid-2">
        <Field label="Language">
          <input
            type="text"
            value={value.language}
            disabled={disabled}
            onChange={(e) => set({ language: e.target.value })}
          />
        </Field>
        <Field label="Package manager">
          <input
            type="text"
            value={value.package_manager}
            disabled={disabled}
            onChange={(e) => set({ package_manager: e.target.value })}
          />
        </Field>
      </div>
      <Field label="Build command">
        <input
          type="text"
          className="mono"
          value={value.build_cmd}
          disabled={disabled}
          onChange={(e) => set({ build_cmd: e.target.value })}
        />
      </Field>
      <Field label="Test command">
        <input
          type="text"
          className="mono"
          value={value.test_cmd}
          disabled={disabled}
          onChange={(e) => set({ test_cmd: e.target.value })}
        />
      </Field>
      <div className="grid-2">
        <Field label="Run command (must contain {port})">
          <input
            type="text"
            className="mono"
            value={value.run_cmd}
            disabled={disabled}
            onChange={(e) => set({ run_cmd: e.target.value })}
          />
        </Field>
        <Field label="Default port">
          <input
            type="number"
            value={value.port}
            disabled={disabled}
            onChange={(e) => set({ port: Number(e.target.value) })}
          />
        </Field>
      </div>

      <h3 style={{ marginTop: 8 }}>Roles</h3>
      <table>
        <thead>
          <tr>
            <th>Role</th>
            <th>Model</th>
            <th>Thinking</th>
            <th>Permissions</th>
          </tr>
        </thead>
        <tbody>
          {ROLES.map((role) => {
            const cfg = roleOf(role);
            return (
              <tr key={role}>
                <td>
                  <strong>{role}</strong>
                </td>
                <td>
                  <input
                    type="text"
                    className="mono"
                    value={cfg.model}
                    disabled={disabled}
                    onChange={(e) => setRole(role, { model: e.target.value })}
                  />
                </td>
                <td>
                  <select
                    value={cfg.thinking_depth}
                    disabled={disabled}
                    onChange={(e) =>
                      setRole(role, {
                        thinking_depth: e.target.value as RoleConfig["thinking_depth"],
                      })
                    }
                  >
                    {DEPTHS.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    {PERMISSIONS.map((perm) => {
                      const on = (cfg.permissions ?? []).includes(perm);
                      return (
                        <label key={perm} className="row small" style={{ gap: 3, marginBottom: 0 }}>
                          <input
                            type="checkbox"
                            checked={on}
                            disabled={disabled}
                            onChange={(e) => {
                              const current = cfg.permissions ?? [];
                              setRole(role, {
                                permissions: e.target.checked
                                  ? [...current, perm]
                                  : current.filter((p) => p !== perm),
                              });
                            }}
                          />
                          {perm}
                        </label>
                      );
                    })}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}
