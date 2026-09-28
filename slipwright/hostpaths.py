"""What a path inside the server is called on the machine the person is sitting at.

In Docker a checkout lives at ``/work/repos/<id>`` -- a path that means nothing to
Windows Explorer or the macOS Finder. The installation says what its two mounted trees
are called outside (``SLIPWRIGHT_HOST_WORK_DIR`` for ``/work``, ``SLIPWRIGHT_HOST_REPOS``
for ``/repos``) and every path under them is translated, so "copy the path" copies
something that opens.

Nothing configured means the server runs on the machine itself (from source), where the
path already is the host path and is returned unchanged.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_WINDOWS = re.compile(r"^([A-Za-z]:|\\\\)")


def _join(prefix: str, parts: tuple[str, ...]) -> str:
    """``prefix`` followed by ``parts``, in the prefix's own spelling: backslashes for a
    drive or a share, forward slashes for everything else."""
    if _WINDOWS.match(prefix) or "\\" in prefix:
        base = prefix.replace("/", "\\").rstrip("\\")
        return "\\".join([base, *parts]) if parts else base
    base = prefix.rstrip("/") or "/"
    return "/".join([base.rstrip("/"), *parts]) if parts else base


class HostPaths:
    """An ordered list of (path inside, what it is called outside)."""

    def __init__(self, mappings: list[tuple[str, str]] | None = None) -> None:
        # longest prefix first, so /work/repos could be mapped apart from /work
        self.mappings = sorted(
            (
                (PurePosixPath(inside), outside.strip())
                for inside, outside in mappings or []
                if inside and outside and outside.strip()
            ),
            key=lambda m: len(m[0].parts),
            reverse=True,
        )

    def to_host(self, path: str) -> str:
        """The host spelling of ``path``, or ``path`` itself when no mapping covers it."""
        inside = PurePosixPath(path.replace("\\", "/"))
        for root, outside in self.mappings:
            if inside == root or root in inside.parents:
                return _join(outside, inside.relative_to(root).parts)
        return path

    def __bool__(self) -> bool:
        return bool(self.mappings)


__all__ = ["HostPaths"]
