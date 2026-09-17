import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Crumbs } from "../components/Crumbs";
import { PageHead } from "../components/ui";
import { describeError, type NewProject } from "../api/client";
import {
  useCreateProject,
  useGitHubRepos,
  useGitHubSettings,
  useJiraProjects,
  useJiraSettings,
} from "../api/hooks";

type Source = "local" | "github";

export function NewProjectPage() {
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
  const [githubRepo, setGithubRepo] = useState("");
  const [jiraKey, setJiraKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: NewProject = {
      name: name.trim(),
      description: description.trim(),
      jira_project_key: jiraKey.trim() || null,
    };
    if (source === "local") body.repo_path = repoPath.trim();
    else body.github_repo = githubRepo.trim();
    try {
      const project = await create.mutateAsync(body);
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
      <PageHead title="New project" subtitle="A repository for the agents to work on." />
      <form className="form card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="name">Name</label>
          <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this project is, for the people who will read the board"
          />
        </div>

        <div className="field">
          <label>Source</label>
          <div className="segmented">
            <button
              type="button"
              className={source === "github" ? "on" : ""}
              onClick={() => setSource("github")}
            >
              GitHub repository
            </button>
            <button
              type="button"
              className={source === "local" ? "on" : ""}
              onClick={() => setSource("local")}
            >
              Local checkout
            </button>
          </div>
        </div>

        {source === "local" ? (
          <div className="field">
            <label htmlFor="repo_path">Path on the server</label>
            <input
              id="repo_path"
              type="text"
              className="mono"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/repos/my-service"
            />
            <div className="help">
              The path as the <em>server</em> sees it. In Docker only the mounted folder is visible:
              put the checkout under <code>SLIPWRIGHT_REPOS</code> (default <code>./repos</code>)
              and enter <code>/repos/&lt;name&gt;</code>.
            </div>
          </div>
        ) : (
          <div className="field">
            <label htmlFor="github_repo">Repository (owner/name)</label>
            {githubReady && repos.data && repos.data.length > 0 ? (
              <select
                id="github_repo"
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
              >
                <option value="">Pick a repository…</option>
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
                placeholder="owner/name"
              />
            )}
            {!githubReady && (
              <div className="callout hint">
                No GitHub token is configured, so private repositories cannot be cloned.{" "}
                <Link to="/settings/github">Connect GitHub</Link> to pick from your repositories.
              </div>
            )}
            {repos.error && <div className="callout error">{describeError(repos.error)}</div>}
          </div>
        )}

        <div className="field">
          <label htmlFor="jira_key">Jira project (optional)</label>
          {jiraReady && jiraProjects.data && jiraProjects.data.length > 0 ? (
            <select id="jira_key" value={jiraKey} onChange={(e) => setJiraKey(e.target.value)}>
              <option value="">Not linked</option>
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
              placeholder="e.g. DEM"
            />
          )}
          {!jiraReady && (
            <div className="muted small">
              <Link to="/settings/jira">Connect Jira</Link> to mirror epics, stories and tasks.
            </div>
          )}
        </div>

        {error && <div className="callout error">{error}</div>}
        <div className="row">
          <button className="btn primary" type="submit" disabled={!canSubmit || create.isPending}>
            {create.isPending ? (source === "github" ? "Cloning…" : "Creating…") : "Create project"}
          </button>
          <Link className="btn" to="/projects">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
