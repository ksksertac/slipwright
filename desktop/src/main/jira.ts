// Jira, on the person's own account: a phase this machine takes moves its issue to
// "In Progress" under their name, as if they had picked it up themselves. All of it is a
// courtesy -- a failure is logged and the work goes on.

export interface JiraCredentials {
  site: string;
  email: string;
  token: string;
}

export function siteUrl(site: string): string {
  const bare = site.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  return `https://${bare}`;
}

async function jira<T>(creds: JiraCredentials, method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(siteUrl(creds.site) + path, {
    method,
    headers: {
      authorization: `Basic ${Buffer.from(`${creds.email}:${creds.token}`).toString("base64")}`,
      accept: "application/json",
      ...(body ? { "content-type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error(`Jira ${response.status} on ${path}`);
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export async function myself(creds: JiraCredentials): Promise<{ accountId: string; displayName: string }> {
  return jira(creds, "GET", "/rest/api/3/myself");
}

interface Transition {
  id: string;
  name: string;
  to?: { name?: string; statusCategory?: { key?: string; name?: string } };
}

/** The first transition into the "In Progress" category. Its key is `indeterminate` in
 *  every Jira, whatever the workflow calls the status itself ("Devam ediyor", "Doing"). */
export function inProgress(transitions: Transition[]): Transition | null {
  return (
    transitions.find((t) => t.to?.statusCategory?.key === "indeterminate") ??
    transitions.find((t) => /in progress/i.test(t.to?.statusCategory?.name ?? "")) ??
    null
  );
}

export async function takeIssue(creds: JiraCredentials, key: string, accountId: string | null, log: (t: string) => void): Promise<string | null> {
  const issue = encodeURIComponent(key);
  let account = accountId;
  try {
    account ??= (await myself(creds)).accountId;
    await jira(creds, "PUT", `/rest/api/3/issue/${issue}/assignee`, { accountId: account });
    log(`Jira: ${key} assigned to you`);
  } catch (error) {
    log(`Jira: ${key} not assigned (${(error as Error).message})`);
  }
  try {
    const { transitions } = await jira<{ transitions: Transition[] }>(creds, "GET", `/rest/api/3/issue/${issue}/transitions`);
    const move = inProgress(transitions ?? []);
    if (move) {
      await jira(creds, "POST", `/rest/api/3/issue/${issue}/transitions`, { transition: { id: move.id } });
      log(`Jira: ${key} → ${move.to?.name ?? move.name}`);
    }
  } catch (error) {
    log(`Jira: ${key} not moved (${(error as Error).message})`);
  }
  return account;
}
