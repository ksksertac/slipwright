// The project's own settings, after it exists.
//
// The same four answers the New project stepper asks for, in the same order and under the
// same headings -- what it is called, where the work happens, what tracks it -- except
// that here they are tabs rather than steps: a step is a thing you have not answered yet,
// and a tab is a thing you came back to change. The fourth step, the first development,
// has no place here: a project past its first one asks for the next from its own
// Developments tab.
//
// Everything is one PATCH per section, so saving the name cannot quietly rewrite the
// repository, and a section says what it is for rather than leaving somebody to guess
// what changing it will do to work already under way.
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { describeError, type Project } from "../api/client";
import { useJiraProjects, useJiraSettings, usePatchProject } from "../api/hooks";
import { ErrorBox } from "../components/ui";
import { useT } from "../i18n";

const PANELS = ["project", "where", "tracking"] as const;
type Panel = (typeof PANELS)[number];

const PANEL_LABEL: Record<Panel, string> = {
  project: "The project",
  where: "Where the work happens",
  tracking: "Tracking",
};

export function ProjectSettingsTab({ project }: { project: Project }) {
  const tx = useT();
  const [panel, setPanel] = useState<Panel>("project");
  return (
    <div className="ps">
      <nav className="ps-tabs" role="tablist">
        {PANELS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === panel}
            className={key === panel ? "on" : ""}
            onClick={() => setPanel(key)}
          >
            {tx(PANEL_LABEL[key])}
          </button>
        ))}
      </nav>
      {panel === "project" && <ProjectPanel project={project} />}
      {panel === "where" && <WherePanel project={project} />}
      {panel === "tracking" && <TrackingPanel project={project} />}
    </div>
  );
}

/** A section that saves on its own, and says so once it has. */
function Section({
  children,
  onSave,
  pending,
  error,
  saved,
  can = true,
}: {
  children: React.ReactNode;
  onSave: () => void;
  pending: boolean;
  error: unknown;
  saved: boolean;
  can?: boolean;
}) {
  const tx = useT();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSave();
  };
  return (
    <form className="card np-section" onSubmit={submit}>
      {children}
      {error ? <div className="callout error">{describeError(error)}</div> : null}
      <div className="np-actions">
        <button className="btn primary" type="submit" disabled={!can || pending}>
          {pending ? tx("Saving…") : tx("Save")}
        </button>
        {saved && !pending && <span className="muted small">{tx("Saved")}</span>}
      </div>
    </form>
  );
}

function ProjectPanel({ project }: { project: Project }) {
  const tx = useT();
  const patch = usePatchProject(project.id);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [language, setLanguage] = useState(project.language ?? "tr");
  return (
    <Section
      onSave={() => patch.mutate({ name: name.trim(), description, language })}
      pending={patch.isPending}
      error={patch.error}
      saved={patch.isSuccess}
      can={name.trim() !== ""}
    >
      <div className="field">
        <label htmlFor="ps-name">{tx("Name")}</label>
        <input id="ps-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="ps-description">{tx("Description")}</label>
        <textarea
          id="ps-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={tx("What this project is, for the people who will read the board")}
        />
      </div>
      <div className="field">
        <label htmlFor="ps-language">{tx("Language the agents write in")}</label>
        <select
          id="ps-language"
          value={language}
          onChange={(e) => setLanguage(e.target.value as Project["language"])}
        >
          <option value="tr">{tx("Turkish")}</option>
          <option value="en">{tx("English")}</option>
        </select>
        <div className="help">
          {tx("What is already written stays as it was; this is for what comes next.")}
        </div>
      </div>
    </Section>
  );
}

function WherePanel({ project }: { project: Project }) {
  const tx = useT();
  const patch = usePatchProject(project.id);
  const [githubRepo, setGithubRepo] = useState(project.github_repo ?? "");
  return (
    <Section
      onSave={() => patch.mutate({ github_repo: githubRepo.trim() })}
      pending={patch.isPending}
      error={patch.error}
      saved={patch.isSuccess}
    >
      <div className="field">
        <label>{tx("The checkout")}</label>
        <div className="mono small">{project.repo_path}</div>
        <div className="help">
          {tx(
            "Where the agents work. It is set when the project is created and does not move: the developments already in it are worktrees of this checkout.",
          )}
        </div>
      </div>
      <div className="field">
        <label htmlFor="ps-repo">{tx("Where finished work is pushed (optional)")}</label>
        <input
          id="ps-repo"
          type="text"
          className="mono"
          value={githubRepo}
          onChange={(e) => setGithubRepo(e.target.value)}
          placeholder={tx("owner/name")}
        />
        <div className="help">
          {tx(
            "Finished work is pushed here: every development pushes its own branch and opens a pull request there. Leave it empty and the branch stays in the folder and you merge it yourself.",
          )}
        </div>
      </div>
    </Section>
  );
}

function TrackingPanel({ project }: { project: Project }) {
  const tx = useT();
  const patch = usePatchProject(project.id);
  const jira = useJiraSettings();
  const ready = Boolean(jira.data?.token_set && jira.data.site_url);
  const projects = useJiraProjects(ready);
  const [key, setKey] = useState(project.jira_project_key ?? "");
  const bad = key.trim() !== "" && !/^[A-Z][A-Z0-9_]*$/.test(key.trim());
  return (
    <Section
      onSave={() => patch.mutate({ jira_project_key: key.trim() })}
      pending={patch.isPending}
      error={patch.error}
      saved={patch.isSuccess}
      can={!bad}
    >
      <div className="field">
        <label htmlFor="ps-jira">{tx("Which Jira project? (optional)")}</label>
        {ready && projects.data && projects.data.length > 0 ? (
          <select id="ps-jira" value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="">{tx("Not linked")}</option>
            {projects.data.map((p) => (
              <option key={p.key} value={p.key}>
                {p.key} — {p.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="ps-jira"
            type="text"
            className="mono"
            value={key}
            onChange={(e) => setKey(e.target.value.toUpperCase())}
            placeholder={tx("e.g. DEM")}
          />
        )}
        {bad && (
          <div className="help bad-text">
            {tx("That is a project name, not its key. The key is short and uppercase, like SCRUM.")}
          </div>
        )}
        {!ready && (
          <div className="help">
            <Link to="/settings/jira">{tx("Connect Jira")}</Link>{" "}
            {tx("to mirror epics, stories and tasks.")}
          </div>
        )}
        {ready && (
          <div className="help">
            {tx(
              "Epics, stories and tasks are mirrored into it from the next development onwards; what is already on the board stays where it is.",
            )}
          </div>
        )}
      </div>
      <ErrorBox error={projects.error} />
    </Section>
  );
}
