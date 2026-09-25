// Where this project gets deployed, before anything is written (T11.6). DevOps reads the
// architecture and proposes a target with the files it would write into `deployment/`;
// this is the person's chance to change the cloud, drop a file or add one. Approving is
// what makes DevOps write them into the branch that becomes the pull request.
import { useState } from "react";
import { type DeployEdit, type DeployPlan, type Job } from "../api/client";
import { useSetDeploy } from "../api/hooks";
import { useToast } from "./Toast";
import { ErrorBox } from "./ui";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

const TARGETS: DeployEdit["target"][] = ["aws", "azure", "none"];

export function DeploymentGate({ job }: { job: Job }) {
  const tx = useT();
  const say = useSay();
  const toast = useToast();
  const saveDeploy = useSetDeploy(job.id);
  const plan = (job.data.deploy ?? null) as DeployPlan | null;
  const [editing, setEditing] = useState(false);
  type Draft = Required<Pick<DeployEdit, "target" | "services" | "scripts" | "notes">>;
  const [draft, setDraft] = useState<Draft>({
    target: plan?.target ?? "none",
    services: plan?.services ?? [],
    scripts: plan?.scripts ?? [],
    notes: plan?.notes ?? [],
  });

  if (!plan) return null;

  const save = () =>
    saveDeploy.mutate(
      { ...draft, scripts: draft.scripts.filter((s) => s.path.trim() !== "") },
      {
        onSuccess: () => {
          setEditing(false);
          toast.ok(tx("The deployment plan was changed"));
        },
      },
    );

  return (
    <div style={{ marginTop: 12 }}>
      {plan.summary && <p>{say(plan.summary)}</p>}
      <div className="row spread">
        <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
          <strong>{tx("Target")}</strong>
          <span className={`badge ${plan.target === "none" ? "" : "ok"}`}>{tx(plan.target)}</span>
          {plan.services && plan.services.length > 0 && (
            <span className="muted small">{plan.services.join(", ")}</span>
          )}
        </div>
        {!editing && (
          <button className="btn ghost" onClick={() => setEditing(true)}>
            {tx("Change")}
          </button>
        )}
      </div>

      {!editing ? (
        <>
          <h3>{tx("Files it will write")}</h3>
          <ul className="plain">
            {(plan.scripts ?? []).map((s, i) => (
              <li key={i}>
                <code>{s.path}</code> <span className="muted small">— {say(s.purpose)}</span>
              </li>
            ))}
          </ul>
          {plan.notes && plan.notes.length > 0 && (
            <>
              <h3>{tx("What you have to supply")}</h3>
              <ul>
                {plan.notes.map((n, i) => (
                  <li key={i}>{say(n)}</li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <div className="stack" style={{ marginTop: 8 }}>
          <div className="field">
            <label htmlFor="deploy-target">{tx("Target")}</label>
            <select
              id="deploy-target"
              value={draft.target}
              onChange={(e) =>
                setDraft((d) => ({ ...d, target: e.target.value as DeployEdit["target"] }))
              }
            >
              {TARGETS.map((t) => (
                <option key={t} value={t}>
                  {tx(t)}
                </option>
              ))}
            </select>
          </div>
          {draft.scripts.map((s, i) => (
            <div className="row" key={i} style={{ gap: 8, flexWrap: "wrap" }}>
              <input
                type="text"
                aria-label={tx("Path")}
                value={s.path}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    scripts: d.scripts.map((x, j) =>
                      j === i ? { ...x, path: e.target.value } : x,
                    ),
                  }))
                }
              />
              <input
                type="text"
                aria-label={tx("What it does")}
                value={s.purpose}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    scripts: d.scripts.map((x, j) =>
                      j === i ? { ...x, purpose: e.target.value } : x,
                    ),
                  }))
                }
              />
              <button
                className="btn ghost danger"
                onClick={() =>
                  setDraft((d) => ({ ...d, scripts: d.scripts.filter((_, j) => j !== i) }))
                }
              >
                {tx("Remove")}
              </button>
            </div>
          ))}
          <div className="row">
            <button
              className="btn ghost"
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  scripts: [...d.scripts, { path: "deployment/", purpose: "" }],
                }))
              }
            >
              {tx("Add a file")}
            </button>
            <button className="btn primary" disabled={saveDeploy.isPending} onClick={save}>
              {tx("Save")}
            </button>
            <button
              className="btn"
              onClick={() => {
                setDraft({
                  target: plan.target,
                  services: plan.services ?? [],
                  scripts: plan.scripts ?? [],
                  notes: plan.notes ?? [],
                });
                setEditing(false);
              }}
            >
              {tx("Cancel")}
            </button>
          </div>
          <p className="faint small">
            {tx(
              "Every file lives under deployment/ — DevOps opens pull requests, it does not edit the product.",
            )}
          </p>
          {saveDeploy.error && <ErrorBox error={saveDeploy.error} />}
        </div>
      )}
    </div>
  );
}
