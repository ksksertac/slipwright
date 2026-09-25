"""Getting to know a project before the first development (T11.2, T11.3).

Two ways in, one result. A repository that already holds code is *analysed*: the
Architect reads it and writes down what it is, in lines a person can strike out. An
empty repository is *taken in*: the Product Owner asks the person what they are building,
reads the answers, asks again if it must, and ends with the story the first development
starts from plus the same kind of lines.

Neither runs inside a job — there is no branch, no worktree, nothing to build yet — so
these functions take the checkout directly and never touch the job state machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import list_tree, read_files, writing_rules
from slipwright.roles.results import AnalysisResult, IntakeResult
from slipwright.schemas.brief import CATEGORIES, Intake
from slipwright.schemas.profile import Profile, RoleName

# A checkout holding only these is empty as far as the agents are concerned: there is
# nothing to analyse, so the person is interviewed instead.
_NOT_CODE = {
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "license",
    "license.md",
    "license.txt",
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    "notice",
    "changelog.md",
    "contributing.md",
    "code_of_conduct.md",
}

ANALYSIS_INSTRUCTIONS = """\
Read the repository in `worktree` and write the project brief: what an engineer joining
this codebase would have to be told before touching it. Every entry of `items` is one
fact, in its `category`, with a `title` of one line and at most two sentences of
`detail`. Cover what the project is for, the stack and versions actually used, how the
pieces fit together, the parts of the code and what each is responsible for, the
conventions this repository already follows (naming, layout, error handling, tests), how
it is built, tested and run, where and how it is deployed, and anything an agent should
be careful with. Write only what the repository shows you — no advice, no plans, no
improvements, and nothing you had to guess. Ten to twenty entries is typical; if the
repository is too small to fill them, write fewer. `summary` is the one-paragraph account
for the person who will approve this list."""

INTAKE_INSTRUCTIONS = """\
You are the Product Owner and the repository is empty: nothing exists yet, so everything
you need has to come from the person. Ask them about the product in plain language — what
it is for, who uses it, the flows that matter, which platforms it needs (web, mobile,
backend, none of them), what it must connect to, where it will run, what it must not do.
Ask only what changes what gets built, never what the Architect decides on its own
(frameworks, file layout, libraries), and never what they already answered: `rounds`
holds every question asked and the answer given.

Ask between three and six questions at a time, each with a short `why` and a `hint`
showing the kind of answer you expect. When the answers are enough to start — or when
`round` has reached `max_rounds` and you must work with what you have — answer instead
with `ready: true`, a `story` and `items`. `story` is the first development's request,
written as the person would have written it if they knew how: two short paragraphs, what
to build and what done looks like, no technology choices. `items` is the project brief
drawn from the answers, one fact per entry in its category."""


# Read in full for the analysis: manifests say what the stack is, CI says how it is built
# and run, and the docs say what it is for.
_READ_FILES = (
    "README.md",
    "README.rst",
    "README",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "Makefile",
    "Dockerfile",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".github/workflows/ci.yml",
    ".github/workflows/ci.yaml",
    ".github/workflows/build.yml",
    ".github/workflows/test.yml",
)


def repository_is_empty(root: Path) -> bool:
    """True when the checkout holds nothing an Architect could analyse."""
    for entry in list_tree(root, limit=200):
        if entry.startswith("..."):
            return False
        name = Path(entry).name.lower()
        if entry.count("/") == 0 and name in _NOT_CODE:
            continue
        if entry.startswith(".git/") or entry.startswith(".slipwright/"):
            continue
        return False
    return True


def _writing(language: str) -> str:
    return writing_rules(language)


def analyse(
    checkout: Path,
    profile: Profile,
    *,
    language: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    feedback: str | None = None,
) -> RoleResult:
    """The Architect reads an existing checkout and proposes the brief."""
    context: dict[str, Any] = {
        "instructions": ANALYSIS_INSTRUCTIONS,
        "writing": _writing(language),
        "categories": list(CATEGORIES),
        "worktree": {
            "tree": list_tree(checkout),
            "files": read_files(checkout, _READ_FILES),
        },
    }
    if feedback:
        context["feedback"] = feedback
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.ARCHITECT,
        profile,
        context,
        provider=provider,
        output_schema_cls=AnalysisResult,
        **kwargs,
    )


def interview(
    intake: Intake,
    profile: Profile,
    *,
    project_name: str,
    description: str,
    language: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
) -> RoleResult:
    """The Product Owner asks the next round, or finishes with the story."""
    context: dict[str, Any] = {
        "instructions": INTAKE_INSTRUCTIONS,
        "writing": _writing(language),
        "categories": list(CATEGORIES),
        "project": {"name": project_name, "description": description},
        "round": len(intake.rounds) + 1,
        "max_rounds": intake.max_rounds,
        "rounds": [
            {
                "number": r.number,
                "answers": [{"question": q.question, "answer": q.answer} for q in r.questions],
            }
            for r in intake.rounds
        ],
    }
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.PO,
        profile,
        context,
        provider=provider,
        output_schema_cls=IntakeResult,
        **kwargs,
    )


__all__ = [
    "ANALYSIS_INSTRUCTIONS",
    "INTAKE_INSTRUCTIONS",
    "analyse",
    "interview",
    "repository_is_empty",
]
