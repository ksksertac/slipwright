"""``slipwright`` command line: a thin HTTP client over the API, plus ``serve``.

slipwright serve                      run the API (state in ./.slipwright)
slipwright project new <name> ...     register a project (--repo <path> | --github owner/name)
slipwright project list               list projects
slipwright project show <id>          show a project and its jobs
slipwright new <project|repo> "<request>"  create and start a job
slipwright status [job-id]            list jobs, or show one with its history
slipwright approve <job-id>           leave the current approval gate
slipwright reject <job-id> "<why>"    re-run the current phase with feedback
slipwright message <job-id> "<text>"  steer a running job
slipwright user add <name>            create a login (the first one is admin)
slipwright user list                  list logins
slipwright token new <name>           issue a bearer token for the CLI (SLIPWRIGHT_TOKEN)
slipwright standards reindex          rebuild the standards index (works on the state dir)
slipwright standards search "<q>"     see which sections a task would retrieve

Client commands authenticate with --token or the SLIPWRIGHT_TOKEN environment variable.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from slipwright.config import Settings


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


_token: str | None = None


def call(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if _token:
        headers["Authorization"] = f"Bearer {_token}"
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - local API
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode(errors="replace")
        try:
            detail = json.loads(payload).get("detail", payload)
        except ValueError:
            detail = payload
        raise ApiError(exc.code, str(detail)) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, f"cannot reach {base_url}: {exc.reason}") from exc


def format_project(project: dict[str, Any]) -> str:
    remote = project.get("github_repo") or project.get("clone_url") or "-"
    jira = project.get("jira_project_key") or "-"
    return (
        f"{project['id']}  {project['name']:<24} repo={project.get('repo_path') or '-'}  "
        f"remote={remote}  jira={jira}"
    )


def format_job(job: dict[str, Any], *, history: bool = False) -> str:
    lines = [
        f"{job['id']}  {job['state']:<28} port={job.get('port') or '-'}  {job['request']}",
    ]
    if history:
        lines.append(f"  project:  {job.get('project_id') or '-'}")
        lines.append(f"  repo:     {job['repo_path']}")
        lines.append(f"  worktree: {job.get('worktree_path') or '-'}")
        data = job.get("data") or {}
        if data.get("plan"):
            phases = data["plan"].get("phases", [])
            lines.append(f"  plan:     phase {data.get('phase_index', 0)}/{len(phases)}")
        if data.get("pr_url"):
            lines.append(f"  pr:       {data['pr_url']}")
        lines.append("  history:")
        for t in job.get("history", []):
            note = f"  {t['note']}" if t.get("note") else ""
            lines.append(f"    {t['at'][:19]}  {t['from_state']} -> {t['to_state']}{note}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slipwright", description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=None, help="API base URL (default: from settings)")
    parser.add_argument("--token", default=None, help="bearer token (default: SLIPWRIGHT_TOKEN)")
    parser.add_argument("--state-dir", type=Path, default=None, dest="global_state_dir")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument(
        "--provider",
        choices=["live", "anthropic", "scripted"],
        default=None,
        help="live: route per role to Anthropic/OpenAI/DeepSeek; scripted: canned replies",
    )
    serve.add_argument("--profile", type=Path, default=None, help="seed profile JSON")
    serve.add_argument("--state-dir", type=Path, default=None)
    serve.add_argument(
        "--no-auth", action="store_true", help="serve without login (trusted local use only)"
    )

    user = sub.add_parser("user", help="manage logins (works directly on the state dir)")
    usub = user.add_subparsers(dest="user_command", required=True)
    uadd = usub.add_parser("add", help="create a login; the first one becomes admin")
    uadd.add_argument("name")
    uadd.add_argument("--password", default=None, help="otherwise prompted for")
    uadd.add_argument("--admin", action="store_true", help="make this user an admin")
    usub.add_parser("list", help="list logins")

    token = sub.add_parser("token", help="bearer tokens (works directly on the state dir)")
    tsub = token.add_subparsers(dest="token_command", required=True)
    tnew = tsub.add_parser("new", help="issue a token for a user and print it once")
    tnew.add_argument("name", help="username")
    tnew.add_argument("--label", default="cli")

    standards = sub.add_parser("standards", help="standards corpus and its search index")
    ssub = standards.add_subparsers(dest="standards_command", required=True)
    sre = ssub.add_parser("reindex", help="rebuild the index from the Markdown corpus")
    sre.add_argument("--project", default=None, help="also index this project's overrides")
    sse = ssub.add_parser("search", help="try a query")
    sse.add_argument("query")
    sse.add_argument("--domain", default=None)
    sse.add_argument("--project", default=None)
    sse.add_argument("-k", type=int, default=4)

    project = sub.add_parser("project", help="manage projects")
    psub = project.add_subparsers(dest="project_command", required=True)
    pnew = psub.add_parser("new", help="register a project")
    pnew.add_argument("name")
    pnew.add_argument("--repo", type=Path, default=None, help="local checkout")
    pnew.add_argument("--github", default=None, help="owner/name to clone from GitHub")
    pnew.add_argument("--clone-url", default=None, help="any git URL to clone from")
    pnew.add_argument("--jira", default=None, help="Jira project key")
    pnew.add_argument("--description", default="")
    psub.add_parser("list", help="list projects")
    pshow = psub.add_parser("show", help="show a project and its jobs")
    pshow.add_argument("project_id")

    new = sub.add_parser("new", help="create and start a job")
    new.add_argument("target", help="project id, or a repository path")
    new.add_argument("request")

    status = sub.add_parser("status", help="list jobs or show one")
    status.add_argument("job_id", nargs="?")
    status.add_argument("--json", action="store_true", dest="as_json")

    approve = sub.add_parser("approve", help="approve the current gate")
    approve.add_argument("job_id")

    reject = sub.add_parser("reject", help="reject the current gate with feedback")
    reject.add_argument("job_id")
    reject.add_argument("feedback")

    message = sub.add_parser("message", help="send a steering message to a job")
    message.add_argument("job_id")
    message.add_argument("text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    global _token
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    base_url = args.url or settings.url
    _token = args.token or settings.token
    if args.global_state_dir:
        settings.state_dir = args.global_state_dir

    if args.command == "serve":
        return _serve(settings, args)
    if args.command == "user":
        return _user(settings, args)
    if args.command == "token":
        return _token_cmd(settings, args)
    if args.command == "standards":
        return _standards(settings, args)

    try:
        if args.command == "project":
            return _project(base_url, args)
        if args.command == "new":
            target = Path(args.target)
            if target.is_dir():
                job = call(
                    base_url,
                    "POST",
                    "/api/jobs",
                    {"request": args.request, "repo_path": str(target.resolve())},
                )
            else:
                job = call(
                    base_url, "POST", f"/api/projects/{args.target}/jobs", {"request": args.request}
                )
            print(format_job(job))
        elif args.command == "status":
            if args.job_id:
                job = call(base_url, "GET", f"/api/jobs/{args.job_id}")
                print(json.dumps(job, indent=2) if args.as_json else format_job(job, history=True))
            else:
                jobs = call(base_url, "GET", "/api/jobs")
                if args.as_json:
                    print(json.dumps(jobs, indent=2))
                elif not jobs:
                    print("no jobs")
                else:
                    print("\n".join(format_job(j) for j in jobs))
        elif args.command == "approve":
            print(format_job(call(base_url, "POST", f"/api/jobs/{args.job_id}/approve")))
        elif args.command == "reject":
            job = call(
                base_url, "POST", f"/api/jobs/{args.job_id}/reject", {"feedback": args.feedback}
            )
            print(format_job(job))
        elif args.command == "message":
            job = call(base_url, "POST", f"/api/jobs/{args.job_id}/message", {"text": args.text})
            print(format_job(job))
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _project(base_url: str, args: argparse.Namespace) -> int:
    if args.project_command == "new":
        body: dict[str, Any] = {
            "name": args.name,
            "description": args.description,
            "github_repo": args.github,
            "clone_url": args.clone_url,
            "jira_project_key": args.jira,
        }
        if args.repo is not None:
            body["repo_path"] = str(args.repo.resolve())
        print(format_project(call(base_url, "POST", "/api/projects", body)))
    elif args.project_command == "list":
        projects = call(base_url, "GET", "/api/projects")
        print("\n".join(format_project(p) for p in projects) if projects else "no projects")
    elif args.project_command == "show":
        project = call(base_url, "GET", f"/api/projects/{args.project_id}")
        print(format_project(project))
        if project.get("description"):
            print(f"  {project['description']}")
        jobs = call(base_url, "GET", f"/api/projects/{args.project_id}/jobs")
        print("  jobs:" if jobs else "  jobs: none")
        for job in jobs:
            print("    " + format_job(job))
    return 0


def _open_store(settings: Settings) -> Any:
    from slipwright.store import JobStore

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return JobStore(settings.db_path)


def _user(settings: Settings, args: argparse.Namespace) -> int:
    from slipwright.store import UsernameTaken

    with _open_store(settings) as store:
        if args.user_command == "add":
            password = args.password
            if password is None:
                password = getpass.getpass(f"password for {args.name}: ")
                if password != getpass.getpass("again: "):
                    print("error: passwords do not match", file=sys.stderr)
                    return 1
            try:
                user = store.create_user(args.name, password, is_admin=True if args.admin else None)
            except (UsernameTaken, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"{user.id}  {user.username}  admin={'yes' if user.is_admin else 'no'}")
        elif args.user_command == "list":
            users = store.list_users()
            if not users:
                print("no users")
            for u in users:
                print(f"{u.id}  {u.username:<24} admin={'yes' if u.is_admin else 'no'}")
    return 0


def _token_cmd(settings: Settings, args: argparse.Namespace) -> int:
    with _open_store(settings) as store:
        user = store.find_user(args.name)
        if user is None:
            print(f"error: user not found: {args.name}", file=sys.stderr)
            return 1
        _, secret = store.create_token(user.id, args.label)
        print(secret)
    return 0


def _standards(settings: Settings, args: argparse.Namespace) -> int:
    from slipwright.config import build_engine
    from slipwright.standards.index import StandardsIndexError

    engine = build_engine(settings)
    try:
        if args.standards_command == "reindex":
            result = engine.reindex_standards(None, force=True)
            print(f"global: {result}")
            projects = (
                [engine.store.get_project(args.project)]
                if args.project
                else engine.store.list_projects()
            )
            for project in projects:
                print(f"{project.name}: {engine.reindex_standards(project.id, force=True)}")
        else:
            hits = engine.search_standards(
                args.query, args.domain, project_id=args.project, k=args.k
            )
            if not hits:
                print("no matching sections")
            for hit in hits:
                print(
                    f"{hit.score:.3f}  [{hit.chunk.domain}] {hit.chunk.title} — {hit.chunk.heading}"
                )
                print(f"        {hit.chunk.page} ({hit.chunk.scope})")
    except StandardsIndexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.store.close()
    return 0


def _serve(settings: Settings, args: argparse.Namespace) -> int:
    import uvicorn

    from slipwright.api import create_app
    from slipwright.config import build_engine

    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.provider:
        settings.provider = args.provider
    if args.profile:
        settings.profile_path = args.profile
    if args.state_dir:
        settings.state_dir = args.state_dir
    if args.no_auth:
        settings.require_auth = False

    app = create_app(build_engine(settings), require_auth=settings.require_auth, dev=settings.dev)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
