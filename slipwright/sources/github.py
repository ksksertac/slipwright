"""GitHub as a source host: the REST calls for identity and repositories, and ``gh`` for
push, pull requests and CI (``githost.GhHost``, unchanged and still used directly by the
older settings path)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from slipwright import net
from slipwright.githost import CiStatus, GhHost, GitHostError
from slipwright.sources.registry import (
    Identity,
    Repo,
    SourceCredentials,
    SourceError,
    SourceSpec,
)
from slipwright.sources.scrub import scrub


class GitHubHost:
    def __init__(
        self,
        creds: SourceCredentials,
        spec: SourceSpec,
        *,
        transport: httpx.BaseTransport | None = None,
        base_branch: str = "main",
        timeout: float = 20.0,
    ) -> None:
        if not creds.token:
            raise SourceError("no GitHub token configured")
        self.creds = creds
        self.spec = spec
        self.base_branch = base_branch
        self._gh = GhHost(token=creds.token)
        self._client = httpx.Client(
            base_url=(creds.api_url or spec.default_api_url).rstrip("/"),
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "slipwright",
            },
            transport=transport,
            timeout=timeout,
        )

    # -- identity and repositories ---------------------------------------------------------

    def whoami(self) -> Identity:
        resp = self._get("/user")
        data = resp.json()
        remaining = resp.headers.get("x-ratelimit-remaining")
        limit = resp.headers.get("x-ratelimit-limit")
        return Identity(
            login=data["login"],
            name=data.get("name"),
            rate_limit_remaining=int(remaining) if remaining else None,
            rate_limit_limit=int(limit) if limit else None,
        )

    def list_repos(self, *, limit: int = 300) -> list[Repo]:
        repos: list[Repo] = []
        page = 1
        while len(repos) < limit:
            resp = self._get(
                "/user/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            batch: list[dict[str, Any]] = resp.json()
            if not batch:
                break
            for r in batch:
                repos.append(
                    Repo(
                        full_name=r["full_name"],
                        private=bool(r.get("private")),
                        default_branch=r.get("default_branch") or "main",
                        html_url=r.get("html_url") or "",
                        description=r.get("description"),
                    )
                )
            if len(batch) < 100:
                break
            page += 1
        return repos[:limit]

    def create_repo(self, name: str, *, private: bool = True, description: str = "") -> Repo:
        """A repository with a first commit in it: an empty one has no branch to work from,
        so ``auto_init`` is what makes the clone usable straight away. Created under the
        configured owner when that is an organisation, else under the token's own account."""
        body = {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": True,
        }
        owner = (self.creds.owner or "").strip()
        path = "/user/repos"
        if owner and owner.lower() != self.whoami().login.lower():
            path = f"/orgs/{owner}/repos"
        data = self._post(path, json=body).json()
        return Repo(
            full_name=data["full_name"],
            private=bool(data.get("private")),
            default_branch=data.get("default_branch") or "main",
            html_url=data.get("html_url") or "",
            description=data.get("description"),
        )

    # -- the repository itself --------------------------------------------------------------

    def clone_url(self, full_name: str) -> str:
        return f"https://{self.spec.clone_host}/{full_name}.git"

    def authenticated_url(self, url: str) -> str:
        prefix = f"https://{self.spec.clone_host}/"
        if not url.startswith(prefix):
            return url
        return url.replace(
            prefix, f"https://{self.spec.push_user}:{self.creds.token}@{self.spec.clone_host}/", 1
        )

    def push(self, worktree: Path, branch: str) -> None:
        # git and `gh` print back the URL they were given, token and all, and whatever
        # they print ends up in the job's history and on the page
        with self._quiet_about_the_token():
            self._gh.push(worktree, branch)

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        with self._quiet_about_the_token():
            return self._gh.open_pr(worktree, branch, title, body)

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        with self._quiet_about_the_token():
            return self._gh.ci_status(worktree, branch, pr_url)

    @contextmanager
    def _quiet_about_the_token(self) -> Iterator[None]:
        """Re-raise whatever the host says with the credential masked."""
        try:
            yield
        except SourceError as exc:
            raise SourceError(scrub(str(exc), self.creds.token)) from exc
        except GitHostError as exc:
            raise type(exc)(scrub(str(exc), self.creds.token)) from exc

    # -- plumbing ---------------------------------------------------------------------------

    def _get(self, path: str, **kw: Any) -> httpx.Response:
        return self._request("GET", path, **kw)

    def _post(self, path: str, **kw: Any) -> httpx.Response:
        return self._request("POST", path, **kw)

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = net.request(self._client, method, path, **kw)
        except httpx.HTTPError as exc:
            raise SourceError(f"GitHub request failed: {exc}") from exc
        if resp.status_code == 401:
            raise SourceError("GitHub rejected the token (401)")
        if resp.status_code >= 400:
            raise SourceError(f"GitHub returned {resp.status_code}: {_why(resp)}")
        return resp


def _why(resp: httpx.Response) -> str:
    """What GitHub actually objected to. Its top-level ``message`` is a headline -- a 422
    on repository creation says only "Repository creation failed." -- and the reason a
    person can act on ("name already exists on this account") is in ``errors``. Reporting
    the headline alone left people guessing, so both are shown."""
    body: dict[str, Any] = {}
    with contextlib.suppress(ValueError):
        parsed = resp.json()
        body = parsed if isinstance(parsed, dict) else {}
    message = str(body.get("message") or "").strip()
    reasons: list[str] = []
    for item in body.get("errors") or []:
        if isinstance(item, str):
            reasons.append(item)
        elif isinstance(item, dict):
            detail = str(item.get("message") or item.get("code") or "").strip()
            field = str(item.get("field") or "").strip()
            if detail:
                reasons.append(f"{field}: {detail}" if field and field not in detail else detail)
    if reasons:
        joined = "; ".join(dict.fromkeys(reasons))
        return f"{message} ({joined})" if message else joined
    return message or resp.text[:200]


__all__ = ["GitHubHost"]
