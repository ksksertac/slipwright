import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { describeError, type Project } from "../api/client";
import { useDeleteProject, usePatchProject } from "../api/hooks";
import { ConfirmModal, Modal } from "./Modal";
import { useToast } from "./Toast";

/** Edit a project's name, description and Jira key. */
export function EditProjectModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const patch = usePatchProject(project.id);
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [jiraKey, setJiraKey] = useState(project.jira_project_key ?? "");
  const [githubRepo, setGithubRepo] = useState(project.github_repo ?? "");
  const [review, setReview] = useState<Project["review"]>(project.review);
  const [supervisor, setSupervisor] = useState<Project["supervisor"]>(project.supervisor);

  const save = () => {
    patch.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        jira_project_key: jiraKey.trim() || null,
        github_repo: githubRepo.trim() || null,
        review,
        supervisor,
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
      title="Edit project"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!name.trim() || patch.isPending} onClick={save}>
            {patch.isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="ep-name">Name</label>
        <input id="ep-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="ep-desc">Description</label>
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
          <label htmlFor="ep-jira">Jira project key</label>
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
        <label htmlFor="ep-review">Standards review after each phase</label>
        <select
          id="ep-review"
          value={review}
          onChange={(e) => setReview(e.target.value as Project["review"])}
        >
          <option value="off">off — never review</option>
          <option value="advisory">advisory — record findings, never block</option>
          <option value="blocking">blocking — the specialist fixes, then you decide</option>
        </select>
        <div className="help faint small">
          QA checks every phase's diff against the standards its specialist was given. In blocking
          mode a blocking finding sends the phase back (two rounds) before it waits for you.
        </div>
      </div>
      <fieldset className="field" style={{ border: 0, padding: 0 }}>
        <label htmlFor="ep-gate">Supervisor at the gates</label>
        <select
          id="ep-gate"
          value={supervisor.mode}
          onChange={(e) =>
            setSupervisor({ ...supervisor, mode: e.target.value as Project["supervisor"]["mode"] })
          }
        >
          <option value="manual">manual — no supervisor, you decide every gate</option>
          <option value="assisted">
            assisted — a recommendation next to each gate, you decide
          </option>
          <option value="auto">auto — confident low-risk approvals are made for you</option>
        </select>
        {supervisor.mode === "auto" && (
          <div className="grid-2" style={{ marginTop: 8 }}>
            <div className="field">
              <label htmlFor="ep-threshold">Confidence needed</label>
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
              <label htmlFor="ep-cap">Automatic approvals per development</label>
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
  const remove = useDeleteProject();
  const toast = useToast();
  const navigate = useNavigate();
  return (
    <ConfirmModal
      title="Delete project"
      body={
        <>
          Delete <strong>{project.name}</strong> and its finished developments? The repository on
          disk is not touched. Projects with a running development cannot be deleted.
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
