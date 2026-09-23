import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Crumbs } from "../components/Crumbs";
import { PageHead } from "../components/ui";
import { api, describeError, type Job, type NewProject } from "../api/client";
import {
  useCreateProject,
  useCreateSourceRepo,
  useJiraProjects,
  useJiraSettings,
  useLocalRepos,
  useSourceRepos,
  useSources,
} from "../api/hooks";
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
  const [language, setLanguage] = useState<NewProject["language"]>("tr");
  const [firstRequest, setFirstRequest] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: NewProject = {
      name: name.trim(),
      description: description.trim(),
      jira_project_key: jiraKey.trim() || null,
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
      }
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const canSubmit =
    name.trim() !== "" &&
    (host === "local"
      ? repoPath.trim() !== ""
      : mode === "new"
        ? newRepoName.trim() !== ""
        : githubRepo.trim() !== "");

  return (
    <div>
      <Crumbs items={[{ label: "Projects", to: "/projects" }, { label: "New project" }]} />
      <PageHead
        title={tx("New project")}
        subtitle={tx("A repository for the agents to work on.")}
      />
      <form className="form card" onSubmit={submit}>
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
              <select id="repo_path" value={repoPath} onChange={(e) => setRepoPath(e.target.value)}>
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
                  {tx("These are the folders under")} <code>{local.data?.root}</code> ( {tx("your")}{" "}
                  <code>SLIPWRIGHT_REPOS</code> {tx("folder")}).{" "}
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

        <div className="field">
          <label htmlFor="jira_key">{tx("Jira project (optional)")}</label>
          {jiraReady && jiraProjects.data && jiraProjects.data.length > 0 ? (
            <select id="jira_key" value={jiraKey} onChange={(e) => setJiraKey(e.target.value)}>
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
              value={jiraKey}
              onChange={(e) => setJiraKey(e.target.value.toUpperCase())}
              placeholder={tx("e.g. DEM")}
            />
          )}
          {!jiraReady && (
            <div className="muted small">
              <Link to="/settings/jira">{tx("Connect Jira")}</Link>{" "}
              {tx("to mirror epics, stories and tasks.")}
            </div>
          )}
        </div>

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

        {error && <div className="callout error">{error}</div>}
        <div className="row">
          <button className="btn primary" type="submit" disabled={!canSubmit || create.isPending}>
            {create.isPending
              ? source === "github"
                ? tx("Cloning…")
                : tx("Creating…")
              : tx("Create project")}
          </button>
          <Link className="btn" to="/projects">
            {tx("Cancel")}
          </Link>
        </div>
      </form>
    </div>
  );
}
