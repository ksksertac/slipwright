// What a new account still has to connect before an agent can run for them.
//
// The list is *derived on the server* from what is actually configured, not stored: a
// stored checklist drifts the moment somebody removes a key, and then the dashboard is
// telling them something untrue. The only thing kept is whether they have dismissed it.
//
// It sits above the dashboard until the required steps are done, because the alternative
// is finding out at the moment of starting work that there is no model key — which is
// both later and ruder than saying so here.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Onboarding as Steps } from "../api/client";
import { keys } from "../api/hooks";
import { useT } from "../i18n";
import { IconCheck, IconCpu, IconFolder, IconGit, IconTicket } from "./icons";

/** Where each step is done, and what to call it. */
const WHERE: Record<string, { to: string; label: string; hint: string; icon: React.ReactNode }> = {
  model: {
    to: "/settings/models",
    label: "Add a model key",
    hint: "Your own key, from any provider. Nothing runs without one.",
    icon: <IconCpu />,
  },
  source: {
    to: "/settings/sources",
    label: "Connect GitHub or Bitbucket",
    hint: "So a finished development can be pushed and opened as a pull request.",
    icon: <IconGit />,
  },
  jira: {
    to: "/settings/jira",
    label: "Connect Jira",
    hint: "Optional. The backlog is mirrored there when you do.",
    icon: <IconTicket />,
  },
  project: {
    to: "/projects/new",
    label: "Start your first project",
    hint: "Pick a repository, or let Slipwright open a new one.",
    icon: <IconFolder />,
  },
};

export function OnboardingChecklist() {
  const tx = useT();
  const qc = useQueryClient();
  const state = useQuery({
    queryKey: keys.onboarding,
    queryFn: () => api.get<Steps>("/api/onboarding"),
    staleTime: 10_000,
  });
  const dismiss = useMutation({
    mutationFn: () => api.put<Steps>("/api/onboarding", { dismissed: true }),
    onSuccess: (next) => qc.setQueryData(keys.onboarding, next),
  });

  const data = state.data;
  if (!data || data.done || data.dismissed) return null;

  return (
    <section className="card onboarding">
      <div className="card-head">
        <h3>{tx("Getting set up")}</h3>
        <button className="text-btn tiny" type="button" onClick={() => dismiss.mutate()}>
          {tx("Hide this")}
        </button>
      </div>
      <p className="muted small onboarding-lead">
        {tx(
          "Slipwright runs the agents; the model keys stay yours. Two things to connect and you are ready.",
        )}
      </p>
      <ul className="onboarding-steps">
        {data.steps.map((step) => {
          const where = WHERE[step.key];
          if (!where) return null;
          return (
            <li key={step.key} className={step.done ? "done" : ""}>
              <span className="onboarding-mark">{step.done ? <IconCheck /> : where.icon}</span>
              <span style={{ minWidth: 0 }}>
                <Link to={where.to} className="onboarding-label">
                  {tx(where.label)}
                </Link>
                {!step.required && <span className="badge plain idle">{tx("optional")}</span>}
                <div className="muted small">{tx(where.hint)}</div>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
