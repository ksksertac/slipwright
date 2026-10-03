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
    from slipwright.schemas.job import APPROVAL_STATES, JobState
    from slipwright.schemas.profile import RoleName
    from slipwright.schemas.project import Project

    engine = build_engine(Settings.from_env({**os.environ}))
    replies, asides = demo.the_script(profile)
    for role, reply in replies.items():
        engine.provider.replies[RoleName(role)] = reply  # type: ignore[attr-defined]
    engine.provider.discovery.update(asides)  # type: ignore[attr-defined]
    demo.the_outside(engine, scratch)

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
        browser.close()

    server.should_exit = True
    engine.store.close()
    print(f"saved to {OUT}; state left in {scratch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
