// Records the README's "Stop, work on it by hand, carry on" picture, as a GIF.
//
// Unlike record-demo.mjs it drives no server: the scene is drawn by demo-pause.html from
// the time alone, because what it shows happens in two places at once -- Slipwright, and
// somebody's editor -- and nothing here can put a real editor on screen the same way twice.
// The wording is the interface's own, so the picture stays true to the product.
//
//   node scripts/record-pause.mjs
//   uv run --with pillow python scripts/frames-to-gif.py <the folder it prints> docs/screenshots/pause-by-hand.gif
//
// Shot every STEP ms; frames-to-gif folds the ones that did not change into the one before,
// so a held screen costs one frame however long it is held.
import { chromium } from "../web/node_modules/playwright/index.mjs";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const STEP = 100;

const frames = mkdtempSync(join(tmpdir(), "slipwright-pause-"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1000, height: 600 } });
await page.goto(pathToFileURL(join(HERE, "demo-pause.html")).href);
await page.evaluate(() => window.ready);
const total = await page.evaluate(() => window.TOTAL);
const stage = page.locator("#stage");

const holds = [];
for (let t = 0; t <= total; t += STEP) {
  await page.evaluate((at) => window.render(at), t);
  await stage.screenshot({ path: join(frames, `${String(holds.length + 1).padStart(4, "0")}.png`) });
  holds.push(STEP);
}
// the last screen stays long enough to read before it starts again
holds[holds.length - 1] = 2500;
writeFileSync(join(frames, "holds.json"), JSON.stringify(holds));
await browser.close();
console.log(`  ${holds.length} shots, ${(total / 1000).toFixed(0)}s -> ${frames}`);
