// Records the README's demo, as a GIF: one development followed from the request to the
// pushed branch.
//
// The agents, then a project created from nothing, then the development it asks for
// walking through its gates -- work stops and waits for a person, which is the thing that
// makes Slipwright different, so what the take shows is somebody deciding and the lane
// filling in behind them. Along the way it looks at what surrounds the lane: the screens
// the Designer drew, a gate put to the person's phone and approved there, the tasks
// moving across the Jira board, the AWS deployment DevOps wrote and the branch it pushed,
// and the bot answering "how is it going?". No model and no service is called: the demo
// server answers every role from a script and stands in for Telegram, Jira and the Git
// host (scripts/demo_world.py), which makes the take free, offline and the same every
// time.
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
const OUT = process.env.DEMO_OUT ?? join(ROOT, "docs", "demo.gif");
// Shown at its own size: GitHub gives a README image about 900px and scales a wider one
// down, which keeps text sharp. Scaling a narrower one up is what blurred the first take.
const SIZE = { width: 1280, height: 800 };

// what demo.py leaves in the folder the form offers, and what the project asks for
const PROJECT = "notes-service";
const REQUEST = "A page to write, search and tag notes";

/** The gate buttons say "Approve · <what>", in whichever language the interface is in. */
const APPROVE = /^(Approve|Onayla)/;

const frames = mkdtempSync(join(tmpdir(), "slipwright-demo-"));
const holds = [];

/** One frame of ``page``, left on screen for ``ms``. */
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

// where the pointer was last seen, per page: each page has a mouse of its own
const pointers = new WeakMap();
const pointerOf = (page) =>
  pointers.get(page) ?? { x: SIZE.width / 2, y: SIZE.height / 2 };

/** Glide to ``target`` on camera, press it, and show the press. */
async function press(page, target, { before = 500 } = {}) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error("nothing to press");
  const from = pointerOf(page);
  const to = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  const steps = 5;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const ease = t * (2 - t);
    await page.mouse.move(
      from.x + (to.x - from.x) * ease,
      from.y + (to.y - from.y) * ease,
    );
    await shoot(page, 50);
  }
  pointers.set(page, to);
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

/** Frames of ``page`` until ``until()`` says so: for pages that change on their own. */
async function watchFor(page, until, { most = 10_000, every = 350 } = {}) {
  const end = Date.now() + most;
  while (Date.now() < end) {
    if (await until().catch(() => false)) return true;
    await page.waitForTimeout(every / 2);
    await shoot(page, every);
  }
  return false;
}

const api = async (path, init) => (await fetch(`${BASE}${path}`, init)).json();

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: SIZE,
  colorScheme: "dark",
});
await context.addInitScript(POINTER);
const page = await context.newPage();
// the phone and the Jira board, open in pages of their own the whole take, the way a
// person has them open on the desk beside the browser
const phone = await context.newPage();
const board = await context.newPage();

/** A scene on the phone, with what the caption beside it says. */
async function onPhone(kicker, title, line) {
  await phone.evaluate(
    ([k, t, l]) => window.caption(k, t, l),
    [kicker, title, line],
  );
  await phone.waitForTimeout(300);
}

/** A look at the Jira board: how far the development's tasks have got. */
async function lookAtBoard(ms, until = null) {
  await board.waitForTimeout(400);
  if (until) await watchFor(board, until, { most: 6_000 });
  // twice: once while what just changed is still lit, once after it has faded
  await shoot(board, 1000);
  await board.waitForTimeout(2600);
  await shoot(board, ms);
}

const issues = async () => (await api("/demo/jira/state")).issues;

try {
  // "load", not "networkidle": both pages poll, so the network is never idle
  await phone.goto(`${BASE}/demo/telegram`, { waitUntil: "load" });
  await board.goto(`${BASE}/demo/jira`, { waitUntil: "load" });

  // -- the agents: who is going to do the work -------------------------------------------
  await page.goto(`${BASE}/agents`, { waitUntil: "networkidle" });
  // English, whatever the installation is set to: this is the README's recording and its
  // readers are not all Turkish. The choice is remembered for the pages that follow.
  const english = page.getByRole("button", { name: "EN", exact: true }).first();
  if (await english.count()) await english.click();
  await page.mouse.move(SIZE.width / 2, SIZE.height / 2);
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
  // tracking: Jira is connected, and its one project is already chosen -- held long
  // enough to read, because the board comes back later in the take
  await page.locator("#jira_key").waitFor({ state: "visible" });
  await page.waitForTimeout(400);
  await shoot(page, 1800);
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
  await shoot(page, 2200);
  await press(page, approveBrief);

  // -- the development: the lane, and a person at every gate ----------------------------
  // the development is started behind the approval, so it is asked for until it is there
  let job;
  for (let i = 0; i < 40 && !job; i++) {
    await page.waitForTimeout(250);
    job = (await api("/api/jobs"))[0];
  }
  if (!job) throw new Error("approving the brief started no development");
  await shoot(page, 700);
  const lane = `${BASE}/projects/${job.project_id}/jobs/${job.id}`;
  await page.goto(lane, { waitUntil: "networkidle" });
  await shoot(page, 600);

  const now = async () => api(`/api/jobs/${job.id}`);
  // finished, or stopped for good: either way there is no gate left to wait for, and
  // waiting out the timeout instead is dead tape at the end of the take
  const over = async () =>
    ["done", "failed", "cancelled"].includes((await now()).state);

  const seen = new Set();
  let testGates = 0;
  for (let round = 0; round < 12; round++) {
    const gate = page.getByRole("button", { name: APPROVE });
    if (!(await watch(page, gate, { most: 15_000, or: over }))) break;
    if (!(await gate.first().isVisible())) break; // it finished rather than stopped
    await page.waitForTimeout(300);
    const state = (await now()).state;

    if (state === "awaiting_design_approval") {
      // -- the Designer's screens: each opened at full size, and signed off there ------
      await page.locator(".design-gate").scrollIntoViewIfNeeded();
      await page.waitForTimeout(900); // the frames load their mocks
      await shoot(page, 2000);
      const cards = page.locator(".mock-card");
      for (let i = 0; i < (await cards.count()); i++) {
        await press(page, cards.nth(i).locator(".mock-open"), { before: 300 });
        await page.waitForTimeout(900);
        await shoot(page, 2400);
        const mobile = page.locator(".mock-surfaces button", {
          hasText: "Mobile",
        });
        if (await mobile.count()) {
          await press(page, mobile.first(), { before: 250 });
          await page.waitForTimeout(700);
          await shoot(page, 2200);
        }
        const yes = page
          .locator(".mock-modal-foot")
          .getByRole("button", { name: APPROVE });
        await press(page, yes.first(), { before: 300 });
        await page.waitForTimeout(500);
        await shoot(page, 500);
        // the modal stays open on a screen already approved; closed to reach the next
        const close = page.getByRole("button", { name: "Close" });
        if (
          await close
            .first()
            .isVisible()
            .catch(() => false)
        ) {
          await close.first().click();
          await page.waitForTimeout(300);
        }
      }
      await shoot(page, 900);
      continue;
    }

    if (state === "awaiting_test_approval" && testGates++ === 0) {
      // -- a gate on the phone: QA's cases, approved from Telegram ---------------------
      await shoot(page, 1600);
      await onPhone(
        "Telegram",
        "The gate comes to your phone",
        "QA is waiting for its test cases to be approved. Ada is away from the desk.",
      );
      const buttons = phone.locator(".kb button");
      await watchFor(phone, async () => (await buttons.count()) > 0);
      await shoot(phone, 2800);
      await press(phone, buttons.first(), { before: 400 });
      await watchFor(phone, async () =>
        /Approved by/.test(await phone.locator("#chat").innerText()),
      );
      await phone.waitForTimeout(300);
      await shoot(phone, 2600);
      // back at the desk, the lane has moved on without anybody touching it
      await page.bringToFront();
      await page.waitForTimeout(500);
      await shoot(page, 1400);
      continue;
    }

    if (state === "awaiting_deploy_approval") {
      // -- DevOps' plan: AWS, the services, and the files it will write ----------------
      await page
        .getByText("Files it will write")
        .first()
        .scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await shoot(page, 3400);
    }

    const button = gate.first();
    await button.scrollIntoViewIfNeeded();
    // long enough to read what is being approved; this is the point of the whole take
    await shoot(page, state === "awaiting_deploy_approval" ? 600 : 2200);
    await press(page, button, { before: 350 });
    await page.waitForTimeout(250);
    await shoot(page, 500);

    if (state === "awaiting_architecture_approval" && !seen.has("board")) {
      // the plan is approved: the backlog is now issues on the team's Jira board
      seen.add("board");
      await lookAtBoard(3000, async () => (await issues()).length >= 6);
    }
    if (
      state === "awaiting_test_approval" &&
      testGates > 1 &&
      !seen.has("board-progress")
    ) {
      // the written tests, approved: every phase is built, and the board says so too
      seen.add("board-progress");
      await lookAtBoard(2600);
    }
  }

  // -- the finished lane: deployment written, branch pushed, pull request open ----------
  await watchFor(page, over, { most: 20_000 });
  await page.evaluate(() => scrollTo(0, 0));
  await page.waitForTimeout(800);
  await shoot(page, 2400);
  // the history says where it went: the pull request, and the checks on it
  await press(page, page.getByRole("tab", { name: "History" }));
  await page.waitForTimeout(600);
  await shoot(page, 2600);
  // and the deployment itself, opened: the files DevOps wrote for AWS
  const written = page
    .locator("li", { hasText: /deployment files written/ })
    .getByText("detail", { exact: true })
    .first();
  if (await written.count()) {
    await press(page, written, { before: 300 });
    await page.waitForTimeout(800);
    await page.mouse.move(SIZE.width - 60, SIZE.height - 60);
    await shoot(page, 4000);
  }

  // Jira: everything done, and the pull request's link left on each issue
  await lookAtBoard(3200);

  // -- keeping track from the phone -----------------------------------------------------
  await onPhone(
    "Telegram",
    "Ask how it is going",
    "The bot answers from the account's own developments, wherever Ada is.",
  );
  await phone.bringToFront();
  await shoot(phone, 900);
  await type(phone, phone.locator("#say"), "/status");
  await phone.keyboard.press("Enter");
  const before = await phone.locator(".msg").count();
  await watchFor(
    phone,
    async () => (await phone.locator(".msg").count()) >= before + 2,
  );
  await phone.waitForTimeout(300);
  // out of the way: the last frame is the one held longest
  await phone.mouse.move(SIZE.width - 60, SIZE.height - 60);
  await shoot(phone, 4200);
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
mkdirSync(dirname(OUT), { recursive: true });
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
if (process.env.DEMO_KEEP_FRAMES) console.log(`  frames kept in ${frames}`);
else rmSync(frames, { recursive: true, force: true });
if (gif.status !== 0) process.exit(1);
console.log(`  wrote ${OUT}`);
