import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { describeError, type Project } from "../api/client";
import { useDeleteProject, usePatchProject } from "../api/hooks";
import { ConfirmModal, Modal } from "./Modal";
import { useToast } from "./Toast";
import { useT } from "../i18n";

/** Edit a project's name, description and Jira key. */
export function EditProjectModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const tx = useT();
  const patch = usePatchProject(project.id);
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [jiraKey, setJiraKey] = useState(project.jira_project_key ?? "");
  const [githubRepo, setGithubRepo] = useState(project.github_repo ?? "");
  const [review, setReview] = useState<Project["review"]>(project.review);
  const [supervisor, setSupervisor] = useState<Project["supervisor"]>(project.supervisor);
  const [budget, setBudget] = useState<Project["budget"]>(project.budget);
  const [sprint, setSprint] = useState<Project["jira_sprint"]>(project.jira_sprint);
  const [language, setLanguage] = useState<Project["language"]>(project.language);

  const save = () => {
    patch.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        jira_project_key: jiraKey.trim() || null,
        github_repo: githubRepo.trim() || null,
        review,
        supervisor,
        budget,
        jira_sprint: sprint,
        language,
      },
      {
        onSuccess: () => {
          toast.ok("Project saved");
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      title={tx("Edit project")}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {tx("Cancel")}
          </button>
          <button className="btn primary" disabled={!name.trim() || patch.isPending} onClick={save}>
            {patch.isPending ? tx("Saving…") : tx("Save")}
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="ep-name">{tx("Name")}</label>
        <input id="ep-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="ep-desc">{tx("Description")}</label>
        <textarea
          id="ep-desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="ep-gh">GitHub repository (owner/name)</label>
          <input
            id="ep-gh"
            type="text"
            className="mono"
            value={githubRepo}
            onChange={(e) => setGithubRepo(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ep-jira">{tx("Jira project key")}</label>
          <input
            id="ep-jira"
            type="text"
            className="mono"
            value={jiraKey}
            onChange={(e) => setJiraKey(e.target.value.toUpperCase())}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="ep-language">{tx("Language the agents write in")}</label>
        <select
          id="ep-language"
          value={language}
          onChange={(e) => setLanguage(e.target.value as Project["language"])}
        >
          <option value="tr">{tx("Turkish")}</option>
          <option value="en">{tx("English")}</option>
        </select>
        <div className="help faint small">
          {tx(
            "Backlog titles and descriptions (and so Jira), plan summaries, test cases and every summary are written in this language; code stays in English.",
          )}
        </div>
      </div>
      <div className="field">
        <label htmlFor="ep-sprint">{tx("Jira sprint for mirrored stories")}</label>
        <select
          id="ep-sprint"
          value={sprint}
          onChange={(e) => setSprint(e.target.value as Project["jira_sprint"])}
        >
          <option value="create">
            {tx("running sprint, else start a new one for the development")}
          </option>
          <option value="active">
            {tx("running sprint only, else leave them in the backlog")}
          </option>
          <option value="off">{tx("never — stories stay in the backlog")}</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="ep-review">{tx("Standards review after each phase")}</label>
        <select
          id="ep-review"
          value={review}
          onChange={(e) => setReview(e.target.value as Project["review"])}
        >
          <option value="off">{tx("off — never review")}</option>
          <option value="advisory">{tx("advisory — record findings, never block")}</option>
          <option value="blocking">{tx("blocking — the specialist fixes, then you decide")}</option>
        </select>
        <div className="help faint small">
          QA checks every phase's diff against the standards its specialist was given. In blocking
          mode a blocking finding sends the phase back (two rounds) before it waits for you.
        </div>
      </div>
      <fieldset className="field" style={{ border: 0, padding: 0 }}>
        <label htmlFor="ep-gate">{tx("Supervisor at the gates")}</label>
        <select
          id="ep-gate"
          value={supervisor.mode}
          onChange={(e) =>
            setSupervisor({ ...supervisor, mode: e.target.value as Project["supervisor"]["mode"] })
          }
        >
          <option value="manual">{tx("manual — no supervisor, you decide every gate")}</option>
          <option value="assisted">
            {tx("assisted — a recommendation next to each gate, you decide")}
          </option>
          <option value="auto">{tx("auto — confident low-risk approvals are made for you")}</option>
        </select>
        {supervisor.mode === "auto" && (
          <div className="grid-2" style={{ marginTop: 8 }}>
            <div className="field">
              <label htmlFor="ep-threshold">{tx("Confidence needed")}</label>
              <input
                id="ep-threshold"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={supervisor.threshold}
                onChange={(e) =>
                  setSupervisor({ ...supervisor, threshold: Number(e.target.value) })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="ep-cap">{tx("Automatic approvals per development")}</label>
              <input
                id="ep-cap"
                type="number"
                min={0}
                max={20}
                value={supervisor.cap}
                onChange={(e) => setSupervisor({ ...supervisor, cap: Number(e.target.value) })}
              />
            </div>
            <label className="row small" style={{ gridColumn: "1 / -1" }}>
              <input
                type="checkbox"
                checked={supervisor.allow_final_gate}
                onChange={(e) =>
                  setSupervisor({ ...supervisor, allow_final_gate: e.target.checked })
                }
              />
              let it approve the written tests too (the gate before the pull request)
            </label>
          </div>
        )}
        <div className="help faint small">
          Rejections are never automatic; every automatic approval is recorded on the job and can be
          undone from the dashboard while the next step runs.
        </div>
      </fieldset>
      <fieldset className="field" style={{ border: 0, padding: 0 }}>
        <label>Budget per development (blank = unlimited)</label>
        <div className="grid-3">
          <div className="field">
            <label htmlFor="ep-b-tokens" className="small">
              {tx("Tokens")}
            </label>
            <input
              id="ep-b-tokens"
              type="number"
              min={1000}
              step={1000}
              value={budget.max_tokens ?? ""}
              onChange={(e) =>
                setBudget({ ...budget, max_tokens: e.target.value ? Number(e.target.value) : null })
              }
            />
          </div>
          <div className="field">
            <label htmlFor="ep-b-clock" className="small">
              Wall clock (seconds)
            </label>
            <input
              id="ep-b-clock"
              type="number"
              min={60}
              step={60}
              value={budget.max_wall_clock_s ?? ""}
              onChange={(e) =>
                setBudget({
                  ...budget,
                  max_wall_clock_s: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </div>
          <div className="field">
            <label htmlFor="ep-b-calls" className="small">
              {tx("Model calls")}
            </label>
            <input
              id="ep-b-calls"
              type="number"
              min={1}
              value={budget.max_invocations ?? ""}
              onChange={(e) =>
                setBudget({
                  ...budget,
                  max_invocations: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </div>
        </div>
        <div className="help faint small">
          {tx(
            "Exceeding a limit fails the development with the reason in its history — never silently.",
          )}
        </div>
      </fieldset>
      <div className="help faint small">
        The checkout path ({project.repo_path ?? "—"}) cannot be changed here; models and
        permissions per role live under Agents.
      </div>
      {patch.error && <div className="callout error">{describeError(patch.error)}</div>}
    </Modal>
  );
}

/** Confirm and delete a project; refused by the server while a job is running. */
export function DeleteProjectModal({
  project,
  onClose,
  redirectTo,
}: {
  project: Project;
  onClose: () => void;
  redirectTo?: string;
}) {
  const tx = useT();
  const remove = useDeleteProject();
  const toast = useToast();
  const navigate = useNavigate();
  return (
    <ConfirmModal
      title={tx("Delete project")}
      body={
        <>
          {tx("Delete")} <strong>{project.name}</strong>{" "}
          {tx(
            "and its finished developments? The repository on disk is not touched. Projects with a running development cannot be deleted.",
          )}
        </>
      }
      busy={remove.isPending}
      error={remove.error ? describeError(remove.error) : null}
      onClose={onClose}
      onConfirm={() =>
        remove.mutate(project.id, {
          onSuccess: () => {
            toast.ok(`Deleted ${project.name}`);
            onClose();
            if (redirectTo) navigate(redirectTo);
          },
        })
      }
    />
  );
}
