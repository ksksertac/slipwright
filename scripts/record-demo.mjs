// Records the README's demo, as a GIF: Slipwright used the way a person first uses it.
//
// The agents, then a project created from nothing, then the development it asks for
// walking through its gates -- work stops and waits for a person, which is the thing that
// makes Slipwright different, so what the take shows is somebody pressing approve and the
// lane filling in behind them. No model is called: the demo server answers every role
// from a script, which makes the take free, offline and the same every time.
//
//   uv run python scripts/demo.py --port 8531 --root C:/demo   # in one terminal
//   node scripts/record-demo.mjs                               # in another
//
// ``--root`` because the checkout's path is on screen, and a temporary directory's path
// is somebody's user name and a random suffix. Each take needs a fresh server: the take
// creates the project, and the second take would find it already there.
//
// It is shot as screenshots, not as video. The first version recorded Playwright's video
// and cut frames out of it: the video is a low-bitrate VP8 stream, the frames were then
// scaled down to fit, and GitHub scaled them back up -- three losses on a picture that is
// mostly small text, and the text was the part nobody could read. A screenshot is the
// page's own pixels, and each one stays on screen for as long as it is worth reading.
import { chromium } from "../web/node_modules/playwright/index.mjs";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.DEMO_URL ?? "http://127.0.0.1:8531";
const OUT = join(ROOT, "docs", "demo.gif");
// Shown at its own size: GitHub gives a README image about 900px and scales a wider one
// down, which keeps text sharp. Scaling a narrower one up is what blurred the first take.
const SIZE = { width: 1280, height: 800 };

// what demo.py leaves in the folder the form offers, and what the project asks for
const PROJECT = "health-service";
const REQUEST = "Add a /health endpoint that reports the version";

/** The gate buttons say "Approve · <what>", in whichever language the interface is in. */
const APPROVE = /^(Approve|Onayla)/;

const frames = mkdtempSync(join(tmpdir(), "slipwright-demo-"));
const holds = [];

/** One frame, left on screen for ``ms``. */
async function shoot(page, ms) {
  const n = String(holds.length + 1).padStart(4, "0");
  await page.screenshot({ path: join(frames, `${n}.png`) });
  holds.push(ms);
}

// A screenshot has no pointer in it, and without one a viewer sees pages change for no
// reason. This draws one the page can see: it follows the real mouse, and swells on a press.
const POINTER = `
  addEventListener("DOMContentLoaded", () => {
    const dot = document.createElement("div");
    dot.id = "demo-pointer";
    Object.assign(dot.style, {
      position: "fixed", left: "-40px", top: "-40px", width: "22px", height: "22px",
      marginLeft: "-11px", marginTop: "-11px", borderRadius: "50%", zIndex: 2147483647,
      pointerEvents: "none", background: "rgba(255,255,255,.28)",
      border: "2px solid rgba(255,255,255,.9)", boxShadow: "0 0 0 1px rgba(0,0,0,.5)",
      transition: "transform .08s",
    });
    document.body.appendChild(dot);
    const at = (e) => { dot.style.left = e.clientX + "px"; dot.style.top = e.clientY + "px"; };
    addEventListener("mousemove", at, true);
    addEventListener("mousedown", () => (dot.style.transform = "scale(.7)"), true);
    addEventListener("mouseup", () => (dot.style.transform = ""), true);
  });
`;

let pointer = { x: SIZE.width / 2, y: SIZE.height / 2 };

/** Glide to ``target`` on camera, press it, and show the press. */
async function press(page, target, { before = 500 } = {}) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error("nothing to press");
  const to = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  const steps = 5;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const ease = t * (2 - t);
    await page.mouse.move(
      pointer.x + (to.x - pointer.x) * ease,
      pointer.y + (to.y - pointer.y) * ease,
    );
    await shoot(page, 50);
  }
  pointer = to;
  await shoot(page, before);
  await page.mouse.down();
  await shoot(page, 120);
  await page.mouse.up();
}

/** Type into ``field`` a few characters a frame, as a person would be seen to. */
async function type(page, field, text) {
  await press(page, field, { before: 150 });
  for (let i = 0; i < text.length; i += 3) {
    await page.keyboard.type(text.slice(i, i + 3));
    await shoot(page, 90);
  }
  await shoot(page, 700);
}

/** Frames while the agents work, until ``until`` can be pressed or the time runs out. */
async function watch(
  page,
  until,
  { most = 20_000, every = 450, or = null } = {},
) {
  const end = Date.now() + most;
  // pressable, not merely visible: a gate's button is drawn, greyed out, while the work
  // behind it is still going, and pressing it then does nothing
  const ready = async () =>
    (await until.first().isVisible()) && (await until.first().isEnabled());
  while (Date.now() < end) {
    if (await ready().catch(() => false)) return true;
    if (or && (await or())) return true;
    await page.waitForTimeout(every / 2);
    await shoot(page, every);
  }
  return false;
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: SIZE,
  colorScheme: "dark",
});
await context.addInitScript(POINTER);
const page = await context.newPage();

try {
  // -- the agents: who is going to do the work -------------------------------------------
  await page.goto(`${BASE}/agents`, { waitUntil: "networkidle" });
  // English, whatever the installation is set to: this is the README's recording and its
  // readers are not all Turkish. The choice is remembered for the pages that follow.
  const english = page.getByRole("button", { name: "EN", exact: true }).first();
  if (await english.count()) await english.click();
  await page.mouse.move(pointer.x, pointer.y);
  await page.waitForTimeout(600);
  await shoot(page, 2600);

  // -- a project, from nothing -----------------------------------------------------------
  await press(page, page.getByRole("link", { name: "Projects" }).first());
  await page.waitForLoadState("networkidle");
  await shoot(page, 700);
  await press(page, page.getByRole("link", { name: /New project/ }).first());
  await page.waitForLoadState("networkidle");
  await shoot(page, 500);

  await type(page, page.locator("#name"), PROJECT);
  await page.locator("#language").selectOption("en");
  await shoot(page, 500);
  await press(page, page.getByRole("button", { name: "Continue" }));
  await shoot(page, 400);

  await press(page, page.getByRole("button", { name: "Local checkout" }));
  const folder = page.locator("select#repo_path");
  await folder.waitFor({ state: "visible" });
  const repoPath = await folder
    .locator("option", { hasText: PROJECT })
    .first()
    .getAttribute("value");
  await press(page, folder, { before: 200 });
  await folder.selectOption(repoPath);
  await shoot(page, 900);
  await press(page, page.getByRole("button", { name: "Continue" }));
  await shoot(page, 500);
  // tracking: Jira is optional and the demo has none
  await press(page, page.getByRole("button", { name: "Continue" }));
  await shoot(page, 400);

  await type(page, page.locator("#first_request"), REQUEST);
  await press(page, page.getByRole("button", { name: "Create project" }));

  // -- the brief: what the agents know before they start ---------------------------------
  const analyse = page.getByRole("button", { name: "Analyse the repository" });
  await watch(page, analyse, { most: 8_000 });
  await shoot(page, 900);
  await press(page, analyse);
  const approveBrief = page.getByRole("button", {
    name: "Approve and continue",
  });
  await watch(page, approveBrief);
  await page.waitForTimeout(400);
  await shoot(page, 2600);
  await press(page, approveBrief);

  // -- the development: the lane, and a person at every gate ----------------------------
  // the development is started behind the approval, so it is asked for until it is there
  let job;
  for (let i = 0; i < 40 && !job; i++) {
    await page.waitForTimeout(250);
    job = (await (await fetch(`${BASE}/api/jobs`)).json())[0];
  }
  if (!job) throw new Error("approving the brief started no development");
  await shoot(page, 700);
  await page.goto(`${BASE}/projects/${job.project_id}/jobs/${job.id}`, {
    waitUntil: "networkidle",
  });
  await shoot(page, 600);

  // finished, or stopped for good: either way there is no gate left to wait for, and
  // waiting out the timeout instead is dead tape at the end of the take
  const over = async () => {
    const now = await (await fetch(`${BASE}/api/jobs/${job.id}`)).json();
    return ["done", "failed", "cancelled"].includes(now.state);
  };
  let pressed = 0;
  for (; pressed < 10; pressed++) {
    const gate = page.getByRole("button", { name: APPROVE });
    if (!(await watch(page, gate, { most: 15_000, or: over }))) break;
    if (!(await gate.first().isVisible())) break; // it finished rather than stopped
    await page.waitForTimeout(300);
    const button = gate.first();
    await button.scrollIntoViewIfNeeded();
    // long enough to read what is being approved; this is the point of the whole take
    await shoot(page, 2400);
    await press(page, button, { before: 350 });
    await page.waitForTimeout(250);
    await shoot(page, 500);
  }
  console.log(`  pressed approve ${pressed} time(s)`);
  if (pressed === 0) throw new Error("no gate was waiting: nothing to show");

  // the finished lane, from the top, and the pull request's worth of tests beside it
  await page.evaluate(() => scrollTo(0, 0));
  await page.waitForTimeout(800);
  const tests = page
    .getByRole("tab", { name: "Tests" })
    .or(page.getByRole("button", { name: "Tests", exact: true }));
  await shoot(page, 1800);
  if (await tests.count()) {
    await press(page, tests.first());
    // out of the way: the last frame is the one held longest, and a pointer parked on
    // the tab it pressed covers the word that says what is being shown
    await page.mouse.move(SIZE.width - 60, SIZE.height - 60);
    await page.waitForTimeout(600);
    await shoot(page, 3200);
  }
} catch (err) {
  // the page as it was when the script lost its way, which says more than the locator
  const seen = join(tmpdir(), "slipwright-demo-failed.png");
  await page.screenshot({ path: seen }).catch(() => {});
  console.error(`  the take stopped; the page at that moment is ${seen}`);
  throw err;
} finally {
  await browser.close();
}

writeFileSync(join(frames, "holds.json"), JSON.stringify(holds));
mkdirSync(join(ROOT, "docs"), { recursive: true });
const gif = spawnSync(
  "uv",
  [
    "run",
    "--with",
    "pillow",
    "python",
    join(ROOT, "scripts", "frames-to-gif.py"),
    frames,
    OUT,
  ],
  { stdio: "inherit", cwd: ROOT, shell: true },
);
rmSync(frames, { recursive: true, force: true });
if (gif.status !== 0) process.exit(1);
console.log(`  wrote ${OUT}`);
