import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Crumbs } from "../components/Crumbs";
import { PageHead } from "../components/ui";
import { api, describeError, type Job, type NewProject } from "../api/client";
import {
  useCreateProject,
  useCreateSourceRepo,
  useCreateJiraProject,
  useJiraProjects,
  useJiraSettings,
  useLocalRepos,
  useSourceRepos,
  useSources,
} from "../api/hooks";
import { IconCheck } from "../components/icons";
import { useT } from "../i18n";

// "local" is the checkout on this machine; anything else is a connected host
type Source = string;

export function NewProjectPage() {
  const tx = useT();
  const navigate = useNavigate();
  const create = useCreateProject();
  const sources = useSources();
  const jira = useJiraSettings();
  const connected = (sources.data ?? []).filter((s) => s.token_set);
  const jiraReady = !!(jira.data?.token_set && jira.data.site_url);
  const jiraProjects = useJiraProjects(jiraReady);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<Source>("");
  // the first connected host is the default; with none, the local checkout is
  const host = source || connected[0]?.name || "local";
  const hostRow = connected.find((s) => s.name === host);
  const repos = useSourceRepos(hostRow ? host : null);
  const openRepo = useCreateSourceRepo(host);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [newRepoName, setNewRepoName] = useState("");
  const [privateRepo, setPrivateRepo] = useState(true);
  const [repoPath, setRepoPath] = useState("");
  const [typing, setTyping] = useState(false); // type a path instead of picking a folder
  const local = useLocalRepos(host === "local");
  const folders = local.data?.repos ?? [];
  const [githubRepo, setGithubRepo] = useState("");
  const [jiraKey, setJiraKey] = useState("");
  const [touchedJira, setTouchedJira] = useState(false);
  const [jiraMode, setJiraMode] = useState<"existing" | "new">("existing");
  const [newJiraKey, setNewJiraKey] = useState("");
  const createJira = useCreateJiraProject();
  const [language, setLanguage] = useState<NewProject["language"]>("tr");
  const [firstRequest, setFirstRequest] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  // a Jira key is short and uppercase (SCRUM); the project's name is not one
  const badJiraKey = jiraKey.trim() !== "" && !/^[A-Z][A-Z0-9_]*$/.test(jiraKey.trim());
  // Jira's own rule for a key it will accept: 2-10 characters, letter first
  const badNewJiraKey = newJiraKey.trim() !== "" && !/^[A-Z][A-Z0-9]{1,9}$/.test(newJiraKey.trim());
  const jiraSite = (jira.data?.site_url ?? "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  // one project is not a choice, so it is linked by default; derived rather than stored,
  // because the list arrives after the first render and "not linked" stays pickable
  const onlyProject = jiraProjects.data?.length === 1 ? jiraProjects.data[0] : undefined;
  const chosenJiraKey = touchedJira ? jiraKey : (onlyProject?.key ?? jiraKey);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: NewProject = {
      name: name.trim(),
      description: description.trim(),
      jira_project_key: chosenJiraKey.trim() || null,
      language,
    };
    if (host === "local") {
      body.repo_path = repoPath.trim();
      // optional here: with it the branch is pushed and a pull request opened
      if (githubRepo.trim()) body.github_repo = githubRepo.trim();
    } else {
      body.source = host;
      body.github_repo = githubRepo.trim();
    }
    try {
      if (jiraReady && jiraMode === "new" && newJiraKey.trim()) {
        // open it on Jira first, for the same reason the repository is opened first: the
        // project is created against what actually came back, not what was typed
        const made = await createJira.mutateAsync({
          key: newJiraKey.trim(),
          name: name.trim() || newJiraKey.trim(),
        });
        body.jira_project_key = made.key;
      }
      if (host !== "local" && mode === "new") {
        // open it on the host first: the project is created against what comes back
        const made = await openRepo.mutateAsync({
          name: newRepoName.trim(),
          private: privateRepo,
          description: description.trim(),
        });
        body.github_repo = made.full_name;
      }
      const project = await create.mutateAsync(body);
      if (firstRequest.trim()) {
        // the first development starts right away; the pipeline shows it working
        await api.post<Job>(`/api/projects/${project.id}/jobs`, { request: firstRequest.trim() });
        navigate(`/projects/${project.id}`);
        return;
      }
      // nothing to build yet: get to know the project first — the checkout is read, or,
      // when there is nothing to read, the Product Owner asks what you are building
      navigate(`/projects/${project.id}/brief`);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const canSubmit =
    name.trim() !== "" &&
    !badJiraKey &&
    !badNewJiraKey &&
    (host === "local"
      ? repoPath.trim() !== ""
      : mode === "new"
        ? newRepoName.trim() !== ""
        : githubRepo.trim() !== "");

  /* One question at a time, in the order somebody answers them: what it is called, where
     the work happens, what tracks it, what to build first. Each step says whether it has
     what it needs, so "Next" is the only thing that can be wrong and it says so where the
     answer is -- rather than a Create button at the foot of a page that refuses without
     telling you which of six fields is empty. */
  const steps: { key: string; label: string; ready: boolean }[] = [
    { key: "project", label: "The project", ready: name.trim() !== "" },
    {
      key: "where",
      label: "Where the work happens",
      ready:
        host === "local"
          ? repoPath.trim() !== ""
          : mode === "new"
            ? newRepoName.trim() !== ""
            : githubRepo.trim() !== "",
    },
    { key: "tracking", label: "Tracking", ready: !badJiraKey && !badNewJiraKey },
    { key: "first", label: "The first development", ready: true },
  ];
  const last = steps.length - 1;
  const at = Math.min(step, last);
  const reachable = steps.findIndex((s) => !s.ready);
  const furthest = reachable === -1 ? last : reachable;

  return (
    <div>
      <Crumbs items={[{ label: "Projects", to: "/projects" }, { label: "New project" }]} />
      <PageHead
        title={tx("New project")}
        subtitle={tx("A repository for the agents to work on.")}
      />
      <form className="np-form" onSubmit={submit}>
        <ol className="stepper-head">
          {steps.map((s, i) => (
            <li
              key={s.key}
              className={i === at ? "on" : i < at || s.ready ? "done" : ""}
              aria-current={i === at ? "step" : undefined}
            >
              <button
                type="button"
                // a step you have already answered can be gone back to; one that needs an
                // earlier answer cannot be jumped to
                disabled={i > furthest}
                onClick={() => setStep(i)}
              >
                <span className="stepper-n">{i < at && s.ready ? <IconCheck /> : i + 1}</span>
                <span className="truncate">{tx(s.label)}</span>
              </button>
            </li>
          ))}
        </ol>
        <div className="np-grid" data-step={steps[at]!.key}>
          {/* What it is called and in which language it is written: the two answers that
            are always needed, whatever the repository turns out to be. */}
          <section className="card np-section np-project">
            <h3>{tx("The project")}</h3>
            <div className="field">
              <label htmlFor="name">{tx("Name")}</label>
              <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="description">{tx("Description")}</label>
              <textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={tx("What this project is, for the people who will read the board")}
              />
            </div>

            <div className="field">
              <label htmlFor="language">{tx("Language the agents write in")}</label>
              <select
                id="language"
                value={language ?? "tr"}
                onChange={(e) => setLanguage(e.target.value as NewProject["language"])}
              >
                <option value="tr">{tx("Turkish")}</option>
                <option value="en">{tx("English")}</option>
              </select>
            </div>
          </section>

          {/* Where the work happens. The longest part of the form, so it has the column to
            itself and the answers below it change with the source. */}
          <section className="card np-section np-where">
            <h3>{tx("Where the work happens")}</h3>
            <div className="field">
              <label>{tx("Source")}</label>
              <div className="segmented">
                {connected.map((row) => (
                  <button
                    key={row.name}
                    type="button"
                    className={host === row.name ? "on" : ""}
                    onClick={() => setSource(row.name)}
                  >
                    {row.label}
                  </button>
                ))}
                <button
                  type="button"
                  className={host === "local" ? "on" : ""}
                  onClick={() => setSource("local")}
                >
                  {tx("Local checkout")}
                </button>
              </div>
              {connected.length === 0 && (
                <div className="help">
                  {tx("No source is connected yet:")}{" "}
                  <Link to="/settings/sources">{tx("connect one")}</Link>{" "}
                  {tx("to work on a hosted repository.")}
                </div>
              )}
            </div>

            {source === "local" ? (
              <div className="field">
                <label htmlFor="repo_path">
                  {folders.length > 0 && !typing ? tx("Checkout") : tx("Path on the server")}
                </label>
                {folders.length > 0 && !typing ? (
                  <select
                    id="repo_path"
                    value={repoPath}
                    onChange={(e) => setRepoPath(e.target.value)}
                  >
                    <option value="">
                      {tx("Pick a folder under {root}…", { root: local.data?.root ?? "" })}
                    </option>
                    {folders.map((r) => (
                      <option key={r.path} value={r.path}>
                        {r.name}
                        {r.is_git ? "" : " — not a git repository yet (git init on create)"}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="repo_path"
                    type="text"
                    className="mono"
                    value={repoPath}
                    onChange={(e) => setRepoPath(e.target.value)}
                    placeholder={
                      local.data?.root ? `${local.data.root}/my-service` : "/repos/my-service"
                    }
                  />
                )}
                <div className="help">
                  {folders.length > 0 && !typing ? (
                    <>
                      {tx("These are the folders under")} <code>{local.data?.root}</code> ({" "}
                      {tx("your")} <code>SLIPWRIGHT_REPOS</code> {tx("folder")}).{" "}
                      {tx(
                        "A folder that is not a git repository yet becomes one on create, with everything in it committed.",
                      )}{" "}
                      <a
                        onClick={(e) => {
                          e.preventDefault();
                          setTyping(true);
                        }}
                        href="#"
                      >
                        {tx("Type a path instead")}
                      </a>
                    </>
                  ) : (
                    <>
                      {tx("The path as the")} <em>{tx("server")}</em>{" "}
                      {tx(
                        "sees it. In Docker only the mounted folder is visible: put the checkout under",
                      )}{" "}
                      <code>SLIPWRIGHT_REPOS</code> ({tx("default")} <code>{tx("./repos")}</code>){" "}
                      {tx("and enter")} <code>/repos/&lt;name&gt;</code>.
                      {folders.length > 0 && (
                        <>
                          {" "}
                          <a
                            onClick={(e) => {
                              e.preventDefault();
                              setTyping(false);
                            }}
                            href="#"
                          >
                            {tx("Pick from the list")}
                          </a>
                        </>
                      )}
                    </>
                  )}
                </div>
              </div>
            ) : null}

            {host !== "local" && (
              <div className="field">
                <label>{tx("Repository")}</label>
                <div className="segmented">
                  <button
                    type="button"
                    className={mode === "existing" ? "on" : ""}
                    onClick={() => setMode("existing")}
                  >
                    {tx("An existing one")}
                  </button>
                  <button
                    type="button"
                    className={mode === "new" ? "on" : ""}
                    onClick={() => setMode("new")}
                  >
                    {tx("Open a new one")}
                  </button>
                </div>
              </div>
            )}

            <div className="field">
              <label htmlFor="github_repo">
                {host === "local"
                  ? tx("Push finished work to (optional)")
                  : mode === "new"
                    ? tx("Name of the new repository")
                    : tx("Repository (owner/name)")}
              </label>
              {host !== "local" && mode === "new" ? (
                <>
                  <input
                    id="github_repo"
                    type="text"
                    value={newRepoName}
                    onChange={(e) => setNewRepoName(e.target.value)}
                    placeholder={name.trim() || tx("my-service")}
                  />
                  <label className="row small" style={{ marginTop: 6 }}>
                    <input
                      type="checkbox"
                      checked={privateRepo}
                      onChange={(e) => setPrivateRepo(e.target.checked)}
                    />
                    {tx("Private")}
                  </label>
                  <div className="help">
                    {tx(
                      "It is opened on {label} when you create the project, with a first commit in it, and the agents work there from the start.",
                      { label: hostRow?.label ?? host },
                    )}
                    {hostRow?.owner ? ` (${hostRow.owner})` : ""}
                  </div>
                  {openRepo.error && (
                    <div className="callout error">{describeError(openRepo.error)}</div>
                  )}
                </>
              ) : repos.data && repos.data.length > 0 ? (
                <select
                  id="github_repo"
                  value={githubRepo}
                  onChange={(e) => setGithubRepo(e.target.value)}
                >
                  <option value="">
                    {host === "local" ? tx("Not linked") : tx("Pick a repository…")}
                  </option>
                  {repos.data.map((r) => (
                    <option key={r.full_name} value={r.full_name}>
                      {r.full_name}
                      {r.private ? " (private)" : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="github_repo"
                  type="text"
                  className="mono"
                  value={githubRepo}
                  onChange={(e) => setGithubRepo(e.target.value)}
                  placeholder={tx("owner/name")}
                />
              )}
              {host === "local" && (
                <div className="help">
                  {tx(
                    "Where finished work is pushed: each development pushes its branch and opens a pull request there. Leave it empty and the branch stays in the checkout for you to merge by hand.",
                  )}
                </div>
              )}
            </div>
          </section>

          <section className="card np-section np-tracking">
            <h3>{tx("Tracking")}</h3>
            <div className="field">
              <label htmlFor="jira_key">{tx("Which Jira project? (optional)")}</label>
              {/* the connection is entered once in Settings and is not asked for again; what
                is asked here is which project on it this one's epics and stories go into --
                an existing one, or a Scrum project opened now under the same account */}
              {jiraReady && (
                <div className="muted small" style={{ marginBottom: 6 }}>
                  {tx("Jira is connected ({site}).", { site: jiraSite })}{" "}
                  {tx("Pick the project its epics, stories and tasks are written into.")}
                </div>
              )}
              {jiraReady && (
                <div className="seg" style={{ marginBottom: 8 }}>
                  <button
                    type="button"
                    className={jiraMode === "existing" ? "active" : ""}
                    onClick={() => setJiraMode("existing")}
                  >
                    {tx("An existing Jira project")}
                  </button>
                  <button
                    type="button"
                    className={jiraMode === "new" ? "active" : ""}
                    onClick={() => setJiraMode("new")}
                  >
                    {tx("Open a new Jira project")}
                  </button>
                </div>
              )}
              {jiraReady && jiraMode === "new" ? (
                <>
                  <input
                    id="jira_key"
                    type="text"
                    className="mono"
                    value={newJiraKey}
                    onChange={(e) => setNewJiraKey(e.target.value.toUpperCase())}
                    placeholder={tx("e.g. DEM")}
                  />
                  <div className="muted small">
                    {tx(
                      "A Scrum project with this key is opened on Jira when you create the project, named after it, led by the connected account.",
                    )}
                  </div>
                  {createJira.error && (
                    <div className="muted small bad-text">{describeError(createJira.error)}</div>
                  )}
                </>
              ) : jiraReady && jiraProjects.data && jiraProjects.data.length > 0 ? (
                <select
                  id="jira_key"
                  value={chosenJiraKey}
                  onChange={(e) => {
                    setTouchedJira(true);
                    setJiraKey(e.target.value);
                  }}
                >
                  <option value="">{tx("Not linked")}</option>
                  {jiraProjects.data.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.key} — {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="jira_key"
                  type="text"
                  className="mono"
                  value={chosenJiraKey}
                  onChange={(e) => {
                    setTouchedJira(true);
                    setJiraKey(e.target.value.toUpperCase());
                  }}
                  placeholder={tx("e.g. DEM")}
                />
              )}
              {!jiraReady && (
                <div className="muted small">
                  <Link to="/settings/jira">{tx("Connect Jira")}</Link>{" "}
                  {tx("to mirror epics, stories and tasks.")}
                </div>
              )}
              {jiraReady && jiraMode === "existing" && jiraProjects.isError && (
                <div className="muted small">
                  {tx("The Jira project list could not be loaded, so type the key yourself.")}
                </div>
              )}
              {badNewJiraKey && (
                <div className="muted small bad-text">
                  {tx("A Jira key is 2 to 10 characters, starts with a letter, like SCRUM.")}
                </div>
              )}
              {badJiraKey && (
                <div className="muted small bad-text">
                  {tx(
                    "That is a project name, not its key. The key is short and uppercase, like SCRUM.",
                  )}
                </div>
              )}
            </div>
          </section>

          {/* The first development, across the foot: it is the one field somebody writes a
            sentence into, so it gets the width. */}
          <section className="card np-section np-first">
            <h3>{tx("The first development")}</h3>
            <div className="field">
              <label htmlFor="first_request">
                {tx("What should the agents build first? (optional)")}
              </label>
              <textarea
                id="first_request"
                value={firstRequest}
                onChange={(e) => setFirstRequest(e.target.value)}
                placeholder={tx(
                  "e.g. Add a /health endpoint that reports the database status, with tests",
                )}
                style={{ minHeight: 90 }}
              />
              <div className="help">
                {tx("Every request becomes a")} <em>{tx("development")}</em>
                {tx(
                  ": the Product Owner turns it into epics, stories and tasks for you to approve, the Architect plans it, the specialists build it. You can add more later from the project's",
                )}{" "}
                <strong>{tx("Developments")}</strong> {tx("tab.")}
              </div>
            </div>
          </section>
        </div>

        {error && <div className="callout error">{error}</div>}
        <div className="np-actions">
          {at > 0 && (
            <button className="btn" type="button" onClick={() => setStep(at - 1)}>
              {tx("Back")}
            </button>
          )}
          {at < last ? (
            <button
              className="btn primary"
              type="button"
              disabled={!steps[at]!.ready}
              onClick={() => setStep(at + 1)}
            >
              {tx("Continue")}
            </button>
          ) : (
            <button className="btn primary" type="submit" disabled={!canSubmit || create.isPending}>
              {create.isPending
                ? source === "github"
                  ? tx("Cloning…")
                  : tx("Creating…")
                : tx("Create project")}
            </button>
          )}
          <Link className="btn ghost" to="/projects">
            {tx("Cancel")}
          </Link>
          {at === last && !canSubmit && (
            <span className="muted small">{tx("Something above is still missing.")}</span>
          )}
        </div>
      </form>
    </div>
  );
}
