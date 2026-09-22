import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Crumbs } from "../components/Crumbs";
import { PageHead } from "../components/ui";
import { api, describeError, type Job, type NewProject } from "../api/client";
import {
  useCreateProject,
  useGitHubRepos,
  useGitHubSettings,
  useJiraProjects,
  useJiraSettings,
  useLocalRepos,
} from "../api/hooks";
import { useT } from "../i18n";

type Source = "local" | "github";

export function NewProjectPage() {
  const tx = useT();
  const navigate = useNavigate();
  const create = useCreateProject();
  const github = useGitHubSettings();
  const jira = useJiraSettings();
  const githubReady = !!github.data?.token_set;
  const jiraReady = !!(jira.data?.token_set && jira.data.site_url);
  const repos = useGitHubRepos(githubReady);
  const jiraProjects = useJiraProjects(jiraReady);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<Source>(githubReady ? "github" : "local");
  const [repoPath, setRepoPath] = useState("");
  const [typing, setTyping] = useState(false); // type a path instead of picking a folder
  const local = useLocalRepos(source === "local");
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
    if (source === "local") body.repo_path = repoPath.trim();
    else body.github_repo = githubRepo.trim();
    try {
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
    name.trim() !== "" && (source === "local" ? repoPath.trim() !== "" : githubRepo.trim() !== "");

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
            <button
              type="button"
              className={source === "github" ? "on" : ""}
              onClick={() => setSource("github")}
            >
              {tx("GitHub repository")}
            </button>
            <button
              type="button"
              className={source === "local" ? "on" : ""}
              onClick={() => setSource("local")}
            >
              {tx("Local checkout")}
            </button>
          </div>
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
        ) : (
          <div className="field">
            <label htmlFor="github_repo">{tx("Repository (owner/name)")}</label>
            {githubReady && repos.data && repos.data.length > 0 ? (
              <select
                id="github_repo"
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
              >
                <option value="">{tx("Pick a repository…")}</option>
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
            {!githubReady && (
              <div className="callout hint">
                No GitHub token is configured, so private repositories cannot be cloned.{" "}
                <Link to="/settings/github">{tx("Connect GitHub")}</Link>{" "}
                {tx("to pick from your repositories.")}
              </div>
            )}
            {repos.error && <div className="callout error">{describeError(repos.error)}</div>}
          </div>
        )}

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
