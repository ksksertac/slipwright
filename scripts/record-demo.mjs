// Records the README's demo: a development walked through its gates, as a GIF.
//
// The point of the recording is the thing that makes Slipwright different -- work stops
// and waits for a person -- so what it shows is somebody pressing approve and the lane
// filling in behind them. No model is called: the server runs on the scripted provider,
// which makes the take free, offline and the same every time.
//
//   uv run python scripts/demo.py --port 8531 --keep   # in one terminal
//   node scripts/record-demo.mjs                       # in another
//
// Playwright and ffmpeg both come with the web toolchain, so there is nothing to install.
import { chromium } from "../web/node_modules/playwright/index.mjs";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.DEMO_URL ?? "http://127.0.0.1:8531";
const OUT = join(ROOT, "docs", "demo.gif");
// 1280x800 is the smallest size the pipeline lane reads at, and the largest a README
// image is shown at on GitHub without being scaled down twice.
const SIZE = { width: 1280, height: 800 };
//: A README image is shown at about 900px, and twelve frames a second is
//: plenty for a page where the movement is a card changing colour.
const WIDE = 760;
const FPS = 8;

/** The gate buttons say "Approve · <what>", in whichever language the interface is in. */
const APPROVE = /^(Approve|Onayla)/;

async function settle(page, ms = 900) {
  await page.waitForTimeout(ms);
}

/** Press approve until there is nothing left waiting, or we have pressed enough times. */
async function walkTheGates(page, most = 8) {
  for (let i = 0; i < most; i++) {
    const button = page.getByRole("button", { name: APPROVE }).first();
    try {
      // the scripted pipeline answers instantly; a long wait here is just dead tape
      await button.waitFor({ state: "visible", timeout: 6_000 });
    } catch {
      return i; // nothing is waiting: the development has finished or failed
    }
    // a beat before the press, so a viewer reads the gate before it goes
    await settle(page, 900);
    await button.click();
    await settle(page, 1000);
  }
  return most;
}

const videos = mkdtempSync(join(tmpdir(), "slipwright-demo-"));
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: SIZE,
  deviceScaleFactor: 1,
  colorScheme: "dark",
  recordVideo: { dir: videos, size: SIZE },
});
const page = await context.newPage();
// the video starts here, and the page takes a second or two to be worth looking at; the
// difference is measured rather than guessed, and trimmed off the front at the end
const rolling = Date.now();
let ready = rolling;

try {
  // straight to the development, asked for rather than guessed at: the demo server has
  // exactly one, and clicking a path through the project pages is three things that can
  // each move without this script noticing
  const jobs = await (await fetch(`${BASE}/api/jobs`)).json();
  const job = jobs[0];
  if (!job) throw new Error("the demo server has no development to record");
  await page.goto(`${BASE}/projects/${job.project_id}/jobs/${job.id}`, {
    waitUntil: "networkidle",
  });
  // English, whatever the installation is set to: this is the README's recording and its
  // readers are not all Turkish. The toggle is in the header and the choice is remembered
  const english = page.getByRole("button", { name: "EN", exact: true }).first();
  if (await english.count()) {
    await english.click();
    await settle(page, 700);
  }
  await settle(page, 1200);

  await page
    .getByRole("button", { name: APPROVE })
    .first()
    .waitFor({ state: "visible", timeout: 20_000 });
  ready = Date.now();

  const pressed = await walkTheGates(page);
  console.log(`  pressed approve ${pressed} time(s)`);
  if (pressed === 0) throw new Error("no gate was waiting: nothing to show");
  await settle(page, 1600);
} finally {
  await context.close(); // the video is only written out on close
  await browser.close();
}

const webm = readdirSync(videos).find((f) => f.endsWith(".webm"));
if (!webm) {
  console.error("playwright wrote no video");
  process.exit(1);
}

// Playwright's ffmpeg is a stripped build: no `fps` filter, no palettegen, and no GIF
// muxer -- only webm in, PNG frames out. So it does the part it can (frames at a chosen
// rate, scaled) and Pillow assembles the GIF, which it is better at anyway.
const cache = join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
const ffmpeg = join(
  cache,
  readdirSync(cache).find((d) => d.startsWith("ffmpeg")) ?? "",
  "ffmpeg-win64.exe",
);
const frames = join(videos, "frames");
mkdirSync(frames, { recursive: true });
mkdirSync(join(ROOT, "docs"), { recursive: true });

// a beat before the gate appears, so the first frame is a page somebody can read
const trim = Math.max(0, (ready - rolling) / 1000 - 0.8);
const shot = spawnSync(
  ffmpeg,
  ["-y", "-ss", trim.toFixed(2), "-i", join(videos, webm), "-r", String(FPS),
   "-vf", `scale=${WIDE}:-1`, join(frames, "%04d.png")],
  { stdio: "inherit" },
);
if (shot.status !== 0) {
  console.error("ffmpeg could not take the frames apart");
  process.exit(1);
}

const gif = spawnSync(
  "uv",
  ["run", "--with", "pillow", "python", join(ROOT, "scripts", "frames-to-gif.py"),
   frames, OUT, String(FPS)],
  { stdio: "inherit", cwd: ROOT, shell: true },
);
rmSync(videos, { recursive: true, force: true });
if (gif.status !== 0) process.exit(1);
console.log(`  wrote ${OUT}`);
