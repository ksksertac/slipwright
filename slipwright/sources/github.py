"""GitHub as a source host: the REST calls for identity and repositories, and ``gh`` for
push, pull requests and CI (``githost.GhHost``, unchanged and still used directly by the
older settings path)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import httpx

from slipwright.githost import CiStatus, GhHost
from slipwright.sources.registry import (
    Identity,
    Repo,
    SourceCredentials,
    SourceError,
    SourceSpec,
)


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
        self._gh.push(worktree, branch)

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        return self._gh.open_pr(worktree, branch, title, body)

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return self._gh.ci_status(worktree, branch, pr_url)

    # -- plumbing ---------------------------------------------------------------------------

    def _get(self, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._client.get(path, **kw)
        except httpx.HTTPError as exc:
            raise SourceError(f"GitHub request failed: {exc}") from exc
        if resp.status_code == 401:
            raise SourceError("GitHub rejected the token (401)")
        if resp.status_code >= 400:
            message = ""
            with contextlib.suppress(ValueError):
                message = resp.json().get("message", "")
            raise SourceError(f"GitHub returned {resp.status_code}: {message or resp.text[:200]}")
        return resp


__all__ = ["GitHubHost"]
