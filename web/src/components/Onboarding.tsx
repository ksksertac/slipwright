// What a new account still has to connect before an agent can run for them.
//
// The list is *derived on the server* from what is actually configured, not stored: a
// stored checklist drifts the moment somebody removes a key, and then the dashboard is
// telling them something untrue. The only thing kept is whether they have dismissed it.
//
// It is said twice. A new account is met by a wizard, one step at a time, because a list
// of four links on a busy dashboard is easy to read past and the first of them is the one
// without which nothing runs. Closed for now, it folds back into the checklist above the
// dashboard, which stays until the required steps are done -- the alternative is finding
// out at the moment of starting work that there is no model key, which is both later and
// ruder than saying so here.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, type Onboarding as Steps } from "../api/client";
import { keys } from "../api/hooks";
import { useT } from "../i18n";
import {
  IconCheck,
  IconChevron,
  IconCpu,
  IconFolder,
  IconGit,
  IconShield,
  IconTicket,
  IconX,
} from "./icons";
import { TwoFactorSetup } from "./TwoFactor";

type Where = { to: string; label: string; hint: string; icon: React.ReactNode };
type Step = Steps["steps"][number] & { where: Where };

/** Where each step is done, and what to call it. */
const WHERE: Record<string, Where> = {
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
  // done right here in the wizard rather than on another page: it is a QR code and six
  // digits, and "skip for now" beside it is what keeps it from being in anybody's way
  two_factor: {
    to: "/security",
    label: "Turn on two-step sign-in",
    hint: "A code from your phone after your password. You can also do it later, under Security.",
    icon: <IconShield />,
  },
  project: {
    to: "/projects/new",
    label: "Start your first project",
    hint: "Pick a repository, or let Slipwright open a new one.",
    icon: <IconFolder />,
  },
};

// The wizard's own memory is the browser tab's, not the server's. "Later" means later in
// this sitting: the next sign-in meets the wizard again, until the steps are done or the
// person says to stop showing it -- and *that* is the server's dismissal, shared with the
// checklist. A step done elsewhere needs nothing here: the list is re-derived on return.
const LATER = "slipwright.setup.later";
// set while the person is away doing a step, so every page can offer the way back
const AWAY = "slipwright.setup.away";

function remembered(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // a browser that keeps nothing gets the wizard on every visit to the dashboard, which
    // is noisier but never wrong
  }
}

function useOnboarding() {
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
  // a step the interface has no words for is left out rather than shown blank
  const steps: Step[] = (data?.steps ?? []).flatMap((s) => {
    const where = WHERE[s.key];
    return where ? [{ ...s, where }] : [];
  });
  const pending = !!data && !data.done && !data.dismissed;
  return { data, steps, pending, dismiss };
}

export function OnboardingChecklist() {
  const tx = useT();
  const { steps, pending, dismiss } = useOnboarding();
  const [wizard, setWizard] = useState(() => remembered(LATER) === null);

  if (!pending) return null;

  const later = () => {
    remember(LATER, "1");
    setWizard(false);
  };

  return (
    <>
      {wizard && <SetupWizard steps={steps} onLater={later} onDismiss={() => dismiss.mutate()} />}
      <section className="card onboarding">
        <div className="card-head">
          <h3>{tx("Getting set up")}</h3>
          <span className="row" style={{ gap: 8 }}>
            <button
              className="btn tiny"
              type="button"
              onClick={() => {
                remember(LATER, null);
                setWizard(true);
              }}
            >
              {tx("Continue setup")}
            </button>
            <button className="text-btn tiny" type="button" onClick={() => dismiss.mutate()}>
              {tx("Hide this")}
            </button>
          </span>
        </div>
        <p className="muted small onboarding-lead">
          {tx(
            "Slipwright runs the agents; the model keys stay yours. Two things to connect and you are ready.",
          )}
        </p>
        <ul className="onboarding-steps">
          {steps.map((step) => {
            const where = step.where;
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
    </>
  );
}

/** One step at a time: what it is, why, and a door to where it is done. */
function SetupWizard({
  steps,
  onLater,
  onDismiss,
}: {
  steps: Step[];
  onLater: () => void;
  onDismiss: () => void;
}) {
  const tx = useT();
  const navigate = useNavigate();
  // opens on the first thing still to do, so coming back from a settings page lands on
  // the step after the one just finished rather than at the beginning again
  const [at, setAt] = useState(() => {
    const first = steps.findIndex((s) => !s.done);
    return first < 0 ? 0 : first;
  });
  // back at the wizard, so the way back has served its purpose
  useEffect(() => remember(AWAY, null), []);

  const step = steps[Math.min(at, steps.length - 1)];
  if (!step) return null;
  const where = step.where;
  const last = at >= steps.length - 1;

  const go = () => {
    remember(AWAY, step.key);
    navigate(where.to);
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onLater()}>
      <div className="modal wizard" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
        <div className="modal-head">
          <div>
            <div className="muted small">
              {tx("Step {n} of {total}", { n: at + 1, total: steps.length })}
            </div>
            <h3>{tx("Getting set up")}</h3>
          </div>
          <button className="btn ghost icon" onClick={onLater} aria-label={tx("Close")}>
            <IconX />
          </button>
        </div>

        <ol className="wizard-rail">
          {steps.map((s, i) => (
            <li
              key={s.key}
              className={[s.done ? "done" : "", i === at ? "on" : ""].join(" ").trim()}
            >
              <button type="button" onClick={() => setAt(i)} title={tx(s.where.label)}>
                <span className="onboarding-mark">{s.done ? <IconCheck /> : i + 1}</span>
              </button>
            </li>
          ))}
        </ol>

        <div className="modal-body wizard-body">
          {at === 0 && (
            <p className="muted small">
              {tx(
                "Slipwright runs the agents; the model keys stay yours. Two things to connect and you are ready.",
              )}
            </p>
          )}
          <div className="wizard-icon">{where.icon}</div>
          <h2 id="wizard-title">
            {tx(where.label)}
            {!step.required && <span className="badge plain idle">{tx("optional")}</span>}
          </h2>
          <p className="muted">{tx(where.hint)}</p>
          {step.key === "two_factor" && !step.done ? (
            // it stays "not done" while the recovery codes are on screen (see the setup),
            // so going on is what takes them away -- and the step is ticked on the way
            <TwoFactorSetup onDone={() => setAt(Math.min(at + 1, steps.length - 1))} />
          ) : step.done ? (
            <div className="wizard-done">
              <IconCheck /> {tx("Already done")}
            </div>
          ) : (
            <button className="btn primary" type="button" onClick={go}>
              {tx(where.label)} <IconChevron />
            </button>
          )}
        </div>

        <div className="modal-foot wizard-foot">
          <button className="text-btn tiny" type="button" onClick={onDismiss}>
            {tx("Do not show this again")}
          </button>
          <span className="row" style={{ gap: 8 }}>
            {at > 0 && (
              <button className="btn" type="button" onClick={() => setAt(at - 1)}>
                {tx("Back")}
              </button>
            )}
            {last ? (
              <button className="btn" type="button" onClick={onLater}>
                {tx("Close")}
              </button>
            ) : (
              <button className="btn" type="button" onClick={() => setAt(at + 1)}>
                {step.done ? tx("Next") : tx("Skip for now")}
              </button>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

/** The way back to the wizard, from the page one of its steps sent the person to. */
export function SetupReturn() {
  const tx = useT();
  const { pathname } = useLocation();
  const { pending } = useOnboarding();
  if (!pending || pathname === "/" || remembered(AWAY) === null) return null;
  return (
    <Link className="btn setup-return" to="/">
      <IconChevron style={{ transform: "rotate(180deg)" }} /> {tx("Back to setup")}
    </Link>
  );
}
