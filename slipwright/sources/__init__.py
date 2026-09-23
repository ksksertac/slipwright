"""Where the code lives: the hosts Slipwright can clone from, push to and open pull
requests on.

A *source* is one hosting service. Each one answers the same questions — who am I, which
repositories can I see, push this branch, open a pull request, how is its CI doing — so the
engine never names a vendor: it asks the registry for the host a project belongs to. The
settings page lists whatever the registry holds, the way the models page lists providers.
"""

from slipwright.sources.registry import (
    BITBUCKET,
    GITHUB,
    SOURCES,
    Identity,
    Repo,
    SourceCredentials,
    SourceError,
    SourceHost,
    SourceSpec,
    build_host,
    source_names,
)

__all__ = [
    "BITBUCKET",
    "GITHUB",
    "SOURCES",
    "Identity",
    "Repo",
    "SourceCredentials",
    "SourceError",
    "SourceHost",
    "SourceSpec",
    "build_host",
    "source_names",
]
