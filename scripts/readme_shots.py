"""Take the README's screenshots of what a development does with its phases.

    uv run --with playwright python scripts/readme_shots.py

The world is ``demo.py``'s -- no key, no network, every role answering from its script --
and the development is carried to each moment by the engine itself rather than by hand,
so the pictures come out the same every time the README needs them again. A browser
(Playwright's Chromium) opens each page at 1440x900, twice the pixels, in the dark theme
and in English, as the other screenshots are.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "docs" / "screenshots"
PORT = 8591


SECOND = "Notes can be pinned to the top of the list"

#: what a person asked the backend agent of phase 1, and what it said; the second heard a
#: change, which the page puts in the box for the person to send on or plan again from
TALK = [
    (
        "Why is the search done in SQL and not in Python?",
        "The notes table can grow past what fits in memory, and SQLite's LIKE on an "
        "indexed column answers in milliseconds; filtering in Python would read every "
        "note on every keystroke.",
        None,
    ),
    (
        "Could the search match tags as well?",
        "Yes: a join on note_tags in the same query. It is not in this phase's task, so "
        "nothing is changed until you say so.",
        "Make the search match a note's tags as well as its text.",
    ),
]


def a_person_pushes(remote: Path, branch: str, scratch: Path) -> None:
    """Somebody checks the paused branch out, fixes something, and pushes it back."""
    clone = scratch / "colleague"
    git = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@acme.dev"]
    subprocess.run(["git", "clone", "-q", "-b", branch, str(remote), str(clone)], check=True)
    (clone / "NOTES.md").write_text("Pinned notes sort first.\n", encoding="utf-8")
    subprocess.run([*git, "-C", str(clone), "add", "NOTES.md"], check=True)
    subprocess.run([*git, "-C", str(clone), "commit", "-qm", "Pinned notes"], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q"], check=True)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="slipwright-shots-"))
    repos = scratch / "repos"
    demo.a_repository(repos)
    profile = json.loads((HERE / "examples" / "python-fastapi.profile.json").read_text("utf-8"))
    always = f'"{sys.executable}" -c "pass"'
    profile["build_cmd"], profile["test_cmd"] = always, always
    profile_path = scratch / "demo.profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    os.environ.update(
        {
            "SLIPWRIGHT_PROVIDER": "scripted",
            "SLIPWRIGHT_PROFILE": str(profile_path),
            "SLIPWRIGHT_STATE_DIR": str(scratch / "state"),
            "SLIPWRIGHT_WORK_DIR": str(scratch / "work"),
            "SLIPWRIGHT_DEMO_PROJECT": "0",
            "SLIPWRIGHT_UPDATE_IMAGE": "off",  # no "new version" in the corner of a picture
        }
    )

    import uvicorn
    from playwright.sync_api import sync_playwright

    from slipwright.api import create_app
    from slipwright.config import Settings, build_engine
    from slipwright.schemas.job import APPROVAL_STATES, JobMessage, JobState
    from slipwright.schemas.profile import RoleName
    from slipwright.schemas.project import Project

    engine = build_engine(Settings.from_env({**os.environ}))
    replies, asides = demo.the_script(profile)
    for role, reply in replies.items():
        engine.provider.replies[RoleName(role)] = reply  # type: ignore[attr-defined]
    engine.provider.discovery.update(asides)  # type: ignore[attr-defined]
    demo.the_outside(engine, scratch)
    # the checkout knows where it is pushed, as a clone would: a stopped development is
    # pushed there, and what a person pushes meanwhile is pulled from there
    remote = scratch / "remote" / f"{demo.PROJECT}.git"
    subprocess.run(
        ["git", "-C", str(repos / demo.PROJECT), "remote", "add", "origin", str(remote)],
        check=True,
    )

    project = engine.create_project(
        Project(
            name="Notes app",
            description="A small notes service with a web page, built end to end.",
            repo_path=repos / demo.PROJECT,
            language="en",  # the agents' words as they wrote them: nothing to translate
        )
    )
    job = engine.start(engine.create_job(demo.REQUEST, project_id=project.id).id)
    while job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL:
        job = engine.approve(job.id)

    app = create_app(engine, require_auth=False, price_refresh_s=0)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    base = f"http://127.0.0.1:{PORT}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="dark"
        )
        page.goto(base)
        page.evaluate("localStorage.setItem('slipwright.lang', 'en')")

        # 1. the plan, before it is approved: what each phase needs, and how it will run
        page.goto(f"{base}/projects/{project.id}/jobs/{job.id}")
        page.get_by_text("phases run at once").first.scroll_into_view_if_needed()
        page.mouse.wheel(0, -260)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "plan-side-by-side.png"))

        # 2. the development, finished: each phase with what it came after and its commit
        for _ in range(40):
            if job.state not in APPROVAL_STATES:
                break
            job = engine.approve(job.id)
        page.goto(f"{base}/projects/{project.id}")
        page.get_by_role("button", name="Details").first.click()
        page.get_by_text("Building", exact=True).first.scroll_into_view_if_needed()
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "pipeline-phases.png"))

        # 3. a second development, stopped at its design gate with phase 1 built: a
        # conversation with the agent of that phase, as it would stand after two questions
        # (put in the store: the scripted provider answers roles, not questions)
        again = engine.start(engine.create_job(SECOND, project_id=project.id).id)
        while again.state is not JobState.AWAITING_DESIGN_APPROVAL:
            again = engine.approve(again.id)
        for text, answer, change in TALK:
            engine.store.add_message(
                JobMessage(
                    job_id=again.id,
                    kind="question",
                    text=text,
                    by="Ada",
                    step="phase:1",
                    phase=1,
                    role="backend",
                    status="answered",
                    answer=answer,
                    change=change,
                )
            )
        page.goto(f"{base}/projects/{project.id}")
        page.get_by_role("button", name="Details").first.click()  # the newest is on top
        page.get_by_text("Search by words and tag").first.click()
        page.get_by_text("Write to the agent").first.scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(scratch / "debug.png"), full_page=True)
        page.screenshot(path=str(OUT / "agent-talk.png"))

        # 4. the same development stopped and pushed, a person's commit on its branch,
        # and Slipwright asked to carry on: it offers to pull that commit in first
        again = engine.pause(again.id, push=True, by="Ada")
        a_person_pushes(remote, again.data.branch_name, scratch)
        page.goto(f"{base}/projects/{project.id}/jobs/{again.id}")
        page.get_by_text("The branch is pushed").first.wait_for()
        page.wait_for_timeout(800)
        page.screenshot(
            path=str(OUT / "paused.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 520}
        )
        page.get_by_role("button", name="Carry on").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "pause-carry-on.png"))
        browser.close()

    server.should_exit = True
    engine.store.close()
    print(f"saved to {OUT}; state left in {scratch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
