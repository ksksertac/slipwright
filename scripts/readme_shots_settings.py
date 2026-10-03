"""Take the README's screenshots of Settings -> Machines and Settings -> Move.

    uv run --with playwright python scripts/readme_shots_settings.py

Offline like ``readme_shots.py``: a scripted installation, three computers lent to it put
straight into the store (a real one would pair with a code), and a browser at 1440x900,
twice the pixels, in the dark theme and in English.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "docs" / "screenshots"
PORT = 8592

# what each machine says it does: the agents it writes for, and the platforms it builds
MACHINES = [
    ("Ayşe's MacBook Pro", ["write:mobile", "write:web", "ios", "android"]),
    ("Build server", ["write:backend", "write:devops"]),
    ("Can's ThinkPad", ["write:backend", "write:web"]),
]


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="slipwright-shots-"))
    os.environ.update(
        {
            "SLIPWRIGHT_PROVIDER": "scripted",
            "SLIPWRIGHT_STATE_DIR": str(scratch / "state"),
            "SLIPWRIGHT_WORK_DIR": str(scratch / "work"),
            "SLIPWRIGHT_DEMO_PROJECT": "0",
            "SLIPWRIGHT_UPDATE_IMAGE": "off",
            "SLIPWRIGHT_NAME": "Office server",
        }
    )

    import uvicorn
    from playwright.sync_api import sync_playwright

    from slipwright.api import create_app
    from slipwright.config import Settings, build_engine

    engine = build_engine(Settings.from_env({**os.environ}))
    for i, (name, can) in enumerate(MACHINES):
        engine.store.add_worker(None, name, f"readme-shot-{i}", can)

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

        page.goto(f"{base}/settings/workers")
        page.get_by_text(MACHINES[0][0]).first.wait_for()
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "machines.png"))

        page.goto(f"{base}/settings/transfer")
        page.get_by_role("button", name="Receive here").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "move.png"))
        browser.close()

    server.should_exit = True
    engine.store.close()
    print(f"saved to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
