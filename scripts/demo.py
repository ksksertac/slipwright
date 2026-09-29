"""Set up a recordable demo: a server with no API key, and a development to walk through.

The README wants thirty seconds of the pipeline moving through its gates, and the thing
that makes that awkward to record is everything around it -- a key, a repository, a
project, a request typed on camera. This does all of it and leaves the server running on
a throwaway state directory, so the recording is: run this, open the link, press approve.

    uv run python scripts/demo.py

Nothing here talks to a model. ``SLIPWRIGHT_PROVIDER=scripted`` answers every role from
the canned script the test suite uses, so the run is free, offline and the same every
time -- which is what you want when the take has to be repeated.

Pass ``--keep`` to leave the state directory behind, or ``--port`` to move it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

#: What the demo development asks for. Short enough to read in a screen recording, and
#: recognisably a real request rather than "test".
REQUEST = "Add a /health endpoint that reports the version"

SEED = """\
# Notes

A small service the demo builds on.
"""


def a_repository(at: Path) -> Path:
    """A git repository with one commit in it: a development needs somewhere to branch."""
    repo = at / "notes"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(SEED, encoding="utf-8")
    run = lambda *args: subprocess.run(  # noqa: E731 - a local shorthand, used four times
        ["git", *args], cwd=repo, check=True, capture_output=True
    )
    run("init", "-q", "-b", "main")
    run("add", "-A")
    run("-c", "user.name=demo", "-c", "user.email=demo@localhost", "commit", "-qm", "first commit")
    return repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument("--keep", action="store_true", help="leave the state directory behind")
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="slipwright-demo-"))
    state = scratch / "state"
    repo = a_repository(scratch)

    # The scripted development has to get past the build gate, and a repository with a
    # README in it has nothing to build. The demo profile's two commands are therefore a
    # command that succeeds -- the same trick the test suite uses, for the same reason.
    profile = json.loads((HERE / "examples" / "python-fastapi.profile.json").read_text("utf-8"))
    always = f'"{sys.executable}" -c "pass"'
    profile["build_cmd"], profile["test_cmd"] = always, always
    profile_path = scratch / "demo.profile.json"
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    env = {
        **os.environ,
        "SLIPWRIGHT_PROVIDER": "scripted",
        "SLIPWRIGHT_PROFILE": str(profile_path),
        "SLIPWRIGHT_STATE_DIR": str(state),
        "SLIPWRIGHT_WORK_DIR": str(scratch / "work"),
        "SLIPWRIGHT_DEMO_PROJECT": "0",  # the worked example would crowd the recording
        "SLIPWRIGHT_PORT": str(args.port),
    }

    from slipwright.config import Settings, build_engine
    from slipwright.schemas.project import Project

    settings = Settings.from_env(env)
    engine = build_engine(settings)
    # English, so the agents' own words are shown as they were written: a project in
    # another language sends them through the translation bridge, and the scripted
    # provider's stand-in translator marks everything it touches
    project = engine.create_project(Project(name="Notes", repo_path=repo, language="en"))
    # started, not merely created: the recording wants to arrive at a gate that is already
    # waiting for somebody, not at a development nobody has set off
    job = engine.start(engine.create_job(REQUEST, project_id=project.id).id)
    engine.store.close()

    where = f"http://127.0.0.1:{args.port}/projects/{project.id}/jobs/{job.id}"
    print("\n  Recording set up. No API key is used; every role answers from the script.\n")
    print(f"  Open:  {where}")
    print("  Press 'Approve' at each gate; the whole pipeline runs in a few seconds.\n")
    # flushed, because uvicorn's own logging starts a line later and would bury the link
    print(
        "  Ctrl-C stops the server." + ("" if args.keep else f"  {scratch} is removed after.\n"),
        flush=True,
    )

    try:
        # the CLI builds the app itself -- there is no module-level one to point uvicorn at
        subprocess.run(
            [
                sys.executable,
                "-m",
                "slipwright.cli",
                "serve",
                "--port",
                str(args.port),
                # a recording has nobody to log in: the state directory is a throwaway and
                # the server is bound to this machine
                "--no-auth",
            ],
            cwd=HERE,
            env=env,
            check=False,
        )
    except KeyboardInterrupt:  # pragma: no cover - the person stopped the recording
        pass
    finally:
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
