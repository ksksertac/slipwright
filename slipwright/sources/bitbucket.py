"""Bitbucket Cloud as a source host, over its REST API — no extra binary in the image.

The token is a workspace or repository access token: it is the password in an https clone
URL under the fixed user ``x-token-auth``, and a bearer token for the API. Pull requests
and build statuses are the API's own; ``git`` itself does the pushing, as it does for
GitHub.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import httpx

from slipwright.githost import CiState, CiStatus, GitHostError, NoRemote
from slipwright.sources.registry import (
    Identity,
    Repo,
    SourceCredentials,
    SourceError,
    SourceSpec,
)
from slipwright.workspace import git as g

# Bitbucket's build states: INPROGRESS | SUCCESSFUL | FAILED | STOPPED
_STATES = {
    "SUCCESSFUL": CiState.SUCCESS,
    "INPROGRESS": CiState.PENDING,
    "FAILED": CiState.FAILURE,
    "STOPPED": CiState.FAILURE,
}


class BitbucketHost:
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
            raise SourceError("no Bitbucket token configured")
        self.creds = creds
        self.spec = spec
        self.base_branch = base_branch
        self._client = httpx.Client(
            base_url=(creds.api_url or spec.default_api_url).rstrip("/"),
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Accept": "application/json",
                "User-Agent": "slipwright",
            },
            transport=transport,
            timeout=timeout,
        )

    # -- identity and repositories ---------------------------------------------------------

    def whoami(self) -> Identity:
        """``/user`` answers for a user token; a workspace or repository token has no user,
        so the workspace it is scoped to is the identity."""
        try:
            data = self._get("/user").json()
            return Identity(
                login=data.get("username") or data.get("nickname") or "?",
                name=data.get("display_name"),
            )
        except SourceError:
            repos = self.list_repos(limit=1)
            workspace = self.creds.owner or (repos[0].full_name.split("/")[0] if repos else None)
            if workspace is None:
                raise
            return Identity(login=workspace, name=None)

    def list_repos(self, *, limit: int = 300) -> list[Repo]:
        repos: list[Repo] = []
        path: str | None = "/repositories"
        params: dict[str, Any] | None = {"role": "member", "pagelen": 100, "sort": "-updated_on"}
        if self.creds.owner:
            path = f"/repositories/{self.creds.owner}"
            params = {"pagelen": 100, "sort": "-updated_on"}
        while path and len(repos) < limit:
            payload = self._get(path, params=params).json()
            for r in payload.get("values", []):
                links = r.get("links") or {}
                html = (links.get("html") or {}).get("href") or ""
                repos.append(
                    Repo(
                        full_name=r.get("full_name") or "",
                        private=bool(r.get("is_private")),
                        default_branch=(r.get("mainbranch") or {}).get("name") or "main",
                        html_url=html,
                        description=r.get("description") or None,
                    )
                )
            nxt = payload.get("next")
            if not nxt:
                break
            path, params = nxt, None  # the next link carries its own query
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
        if not g.has_remote(worktree, "origin"):
            raise NoRemote("the checkout has no remote named 'origin'")
        url = self.authenticated_url(_origin(worktree))
        try:
            g.run(worktree, "push", "--force-with-lease", "-u", url, branch)
        except g.GitError as exc:
            raise GitHostError(f"push failed: {_scrub(exc.stderr, self.creds.token)}") from exc

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        repo = self._repo_of(worktree)
        existing = self._get(
            f"/repositories/{repo}/pullrequests",
            params={"q": f'source.branch.name="{branch}" AND state="OPEN"'},
        ).json()
        for pr in existing.get("values", []):
            url = ((pr.get("links") or {}).get("html") or {}).get("href")
            if url:
                return str(url)
        created = self._post(
            f"/repositories/{repo}/pullrequests",
            json={
                "title": title[:255],
                "description": body,
                "source": {"branch": {"name": branch}},
                "destination": {"branch": {"name": self.base_branch}},
                "close_source_branch": True,
            },
        ).json()
        url = ((created.get("links") or {}).get("html") or {}).get("href")
        if not url:
            raise SourceError("Bitbucket did not return a pull request link")
        return str(url)

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        repo = self._repo_of(worktree)
        head = g.run(worktree, "rev-parse", branch).stdout.strip()
        payload = self._get(f"/repositories/{repo}/commit/{head}/statuses").json()
        checks = payload.get("values", [])
        if not checks:
            return CiStatus(CiState.NONE, summary="no checks reported")
        states = [_STATES.get(str(c.get("state") or "").upper(), CiState.PENDING) for c in checks]
        summary = ", ".join(
            f"{c.get('name') or c.get('key')}: {s}" for c, s in zip(checks, states, strict=True)
        )
        if any(s is CiState.FAILURE for s in states):
            failed = [c for c, s in zip(checks, states, strict=True) if s is CiState.FAILURE]
            log = "\n".join(
                f"{c.get('name') or c.get('key')}: "
                f"{c.get('description') or ''} {c.get('url') or ''}".strip()
                for c in failed
            )
            return CiStatus(CiState.FAILURE, log=log.strip(), summary=summary)
        if any(s is CiState.PENDING for s in states):
            return CiStatus(CiState.PENDING, summary=summary)
        return CiStatus(CiState.SUCCESS, summary=summary)

    # -- plumbing ---------------------------------------------------------------------------

    def _repo_of(self, worktree: Path) -> str:
        """``workspace/repo`` from the checkout's origin, so a job never needs it passed in."""
        if not g.has_remote(worktree, "origin"):
            raise NoRemote("the checkout has no remote named 'origin'")
        path = _origin(worktree).split(self.spec.clone_host, 1)[-1].lstrip(":/")
        return path.removesuffix(".git")

    def _get(self, path: str, **kw: Any) -> httpx.Response:
        return self._request("GET", path, **kw)

    def _post(self, path: str, **kw: Any) -> httpx.Response:
        return self._request("POST", path, **kw)

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise SourceError(f"Bitbucket request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise SourceError(f"Bitbucket rejected the token ({resp.status_code})")
        if resp.status_code >= 400:
            message = ""
            with contextlib.suppress(ValueError):
                body = resp.json()
                message = (body.get("error") or {}).get("message") or ""
            raise SourceError(
                f"Bitbucket returned {resp.status_code}: {message or resp.text[:200]}"
            )
        return resp


def _origin(worktree: Path) -> str:
    """The configured remote URL, read raw: ``git remote get-url`` applies the checkout's
    own url.*.insteadOf rewrites, which would hide which repository this is."""
    return g.run(worktree, "config", "--get", "remote.origin.url").stdout.strip()


def _scrub(text: str, token: str) -> str:
    """git prints the URL it was given: the token must not reach the job's history."""
    return text.replace(token, "…") if token else text


__all__ = ["BitbucketHost"]
