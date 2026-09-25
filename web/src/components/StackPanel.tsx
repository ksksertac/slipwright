// What each part of the product is written in (T11.5). The Architect proposes it; at the
// architecture gate the person can change a language or a framework before a specialist
// writes a line, which is the last cheap moment to change one's mind.
import { useState } from "react";
import { type Job, type PlanEdit, type StackChoice } from "../api/client";
import { useSetPlan } from "../api/hooks";
import type { PlanShape } from "./Breakdown";
import { DomainBadge } from "./agents";
import { useToast } from "./Toast";
import { ErrorBox } from "./ui";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

const DOMAINS: StackChoice["domain"][] = ["backend", "web", "mobile", "infra"];

export function StackPanel({ job, editable }: { job: Job; editable: boolean }) {
  const tx = useT();
  const say = useSay();
  const toast = useToast();
  const savePlan = useSetPlan(job.id);
  const plan = (job.data.plan ?? null) as PlanShape | null;
  const proposed = plan?.stack ?? [];
  const [rows, setRows] = useState<StackChoice[]>(proposed);
  const [editing, setEditing] = useState(false);

  if (!plan || (proposed.length === 0 && !editing)) return null;

  const save = () => {
    const body: PlanEdit = {
      summary: plan.summary ?? null,
      stack: rows.filter((r) => r.language.trim() !== ""),
      decisions: plan.decisions ?? null,
      phases: plan.phases as unknown as PlanEdit["phases"],
      breakdown: (plan.breakdown ?? null) as unknown as PlanEdit["breakdown"],
    };
    savePlan.mutate(body, {
      onSuccess: () => {
        setEditing(false);
        toast.ok(tx("The stack was changed"));
      },
    });
  };

  return (
    <div style={{ marginTop: 12 }}>
      <div className="row spread">
        <h3 style={{ margin: 0 }}>{tx("What it is written in")}</h3>
        {editable && !editing && (
          <button className="btn ghost" onClick={() => setEditing(true)}>
            {tx("Change")}
          </button>
        )}
      </div>
      {!editing ? (
        <ul className="plain">
          {proposed.map((row, i) => (
            <li key={i} className="row" style={{ gap: 8, alignItems: "baseline" }}>
              <DomainBadge domain={row.domain} />
              <strong>{row.language}</strong>
              {row.framework && <span className="muted">{row.framework}</span>}
              {row.why && <span className="faint small">— {say(row.why)}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <div className="stack" style={{ marginTop: 8 }}>
          {rows.map((row, i) => (
            <div className="row" key={i} style={{ gap: 8, flexWrap: "wrap" }}>
              <select
                value={row.domain}
                onChange={(e) =>
                  setRows((old) =>
                    old.map((r, j) =>
                      j === i ? { ...r, domain: e.target.value as StackChoice["domain"] } : r,
                    ),
                  )
                }
              >
                {DOMAINS.map((d) => (
                  <option key={d} value={d}>
                    {tx(d)}
                  </option>
                ))}
              </select>
              <input
                type="text"
                aria-label={tx("Language")}
                placeholder={tx("Language")}
                value={row.language}
                onChange={(e) =>
                  setRows((old) =>
                    old.map((r, j) => (j === i ? { ...r, language: e.target.value } : r)),
                  )
                }
              />
              <input
                type="text"
                aria-label={tx("Framework")}
                placeholder={tx("Framework")}
                value={row.framework ?? ""}
                onChange={(e) =>
                  setRows((old) =>
                    old.map((r, j) => (j === i ? { ...r, framework: e.target.value } : r)),
                  )
                }
              />
              <button
                className="btn ghost danger"
                onClick={() => setRows((old) => old.filter((_, j) => j !== i))}
              >
                {tx("Remove")}
              </button>
            </div>
          ))}
          <div className="row">
            <button
              className="btn ghost"
              onClick={() =>
                setRows((old) => [...old, { domain: "backend", language: "", framework: "" }])
              }
            >
              {tx("Add a part")}
            </button>
            <button className="btn primary" disabled={savePlan.isPending} onClick={save}>
              {tx("Save")}
            </button>
            <button
              className="btn"
              onClick={() => {
                setRows(proposed);
                setEditing(false);
              }}
            >
              {tx("Cancel")}
            </button>
          </div>
          {savePlan.error && <ErrorBox error={savePlan.error} />}
        </div>
      )}
    </div>
  );
}
