"""GitHub REST client for the settings page: who am I, which repositories can I see.

Pushing and pull requests still go through ``gh`` (``githost.py``); this client only
covers what the UI needs to connect an account and pick a repository. Tests pass an
``httpx`` transport that answers locally.
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHubIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    name: str | None = None
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None


class GitHubRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    private: bool = False
    default_branch: str = "main"
    html_url: str = ""
    description: str | None = None


class GitHubSettings(BaseModel):
    """What the settings page reads and writes. The token itself is never returned."""

    model_config = ConfigDict(extra="forbid")

    owner: str | None = Field(default=None, description="Default owner/org for new projects.")
    base_branch: str = "main"
    token_set: bool = False
    token_hint: str | None = Field(default=None, description="Last four characters, if set.")


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        api_url: str = DEFAULT_API,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not token:
            raise GitHubError("no GitHub token configured")
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "slipwright",
            },
            transport=transport,
            timeout=timeout,
        )

    def whoami(self) -> GitHubIdentity:
        resp = self._get("/user")
        data = resp.json()
        remaining = resp.headers.get("x-ratelimit-remaining")
        limit = resp.headers.get("x-ratelimit-limit")
        return GitHubIdentity(
            login=data["login"],
            name=data.get("name"),
            rate_limit_remaining=int(remaining) if remaining else None,
            rate_limit_limit=int(limit) if limit else None,
        )

    def list_repos(self, *, limit: int = 300) -> list[GitHubRepo]:
        repos: list[GitHubRepo] = []
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
                    GitHubRepo(
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

    def _get(self, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._client.get(path, **kw)
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed: {exc}") from exc
        if resp.status_code == 401:
            raise GitHubError("GitHub rejected the token (401)")
        if resp.status_code >= 400:
            message = ""
            with contextlib.suppress(ValueError):
                message = resp.json().get("message", "")
            raise GitHubError(f"GitHub returned {resp.status_code}: {message or resp.text[:200]}")
        return resp


__all__ = ["GitHubClient", "GitHubError", "GitHubIdentity", "GitHubRepo", "GitHubSettings"]
