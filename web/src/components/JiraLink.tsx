import { useJiraSettings } from "../api/hooks";

export function JiraLink({ issueKey }: { issueKey: string | null | undefined }) {
  const jira = useJiraSettings();
  if (!issueKey) return null;
  const site = jira.data?.site_url;
  if (!site) return <span className="tag">{issueKey}</span>;
  return (
    <a className="tag" href={`${site}/browse/${issueKey}`} target="_blank" rel="noreferrer">
      {issueKey}
    </a>
  );
}
