import type { Permission, Profile, RoleConfig } from "../api/client";
import { useProviderModels, useProviders } from "../api/hooks";

const ROLES = [
  "po",
  "architect",
  "backend",
  "web_ui",
  "mobile_ui",
  "qa",
  "devops",
  "supervisor",
] as const;
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
  const providers = useProviders();
  const defaultProvider = providers.data?.find((p) => p.is_default)?.name ?? "anthropic";
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
            <th>Provider</th>
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
                  <select
                    value={cfg.provider ?? ""}
                    disabled={disabled}
                    onChange={(e) => setRole(role, { provider: e.target.value || null })}
                  >
                    <option value="">default ({defaultProvider})</option>
                    {(providers.data ?? []).map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.label}
                        {p.key_set ? "" : " — no key"}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <ModelInput
                    provider={cfg.provider ?? defaultProvider}
                    value={cfg.model}
                    disabled={disabled}
                    onChange={(model) => setRole(role, { model })}
                  />
                </td>
                <td>
                  <select
                    value={cfg.thinking_depth}
                    disabled={disabled}
                    style={{ minWidth: 110 }}
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

/** Free-text model id with the provider's model list as suggestions (when a key is set). */
function ModelInput({
  provider,
  value,
  disabled,
  onChange,
}: {
  provider: string;
  value: string;
  disabled: boolean;
  onChange: (model: string) => void;
}) {
  const models = useProviderModels(provider);
  const listId = `models-${provider}`;
  return (
    <>
      <input
        type="text"
        className="mono"
        list={listId}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="model id"
      />
      <datalist id={listId}>
        {(models.data?.models ?? []).map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
    </>
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
