// slipwright-agent as one file: the worker, the models, the relay and ws bundled together,
// so a server needs Node 20 and nothing else -- no npm install, no Electron.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const pkg = JSON.parse(readFileSync(fileURLToPath(import.meta.resolve("../package.json")), "utf8"));

await build({
  entryPoints: ["src/cli/index.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  outfile: "out/cli/slipwright-agent.cjs",
  alias: { "@shared": resolve("src/shared") },
  define: { __VERSION__: JSON.stringify(pkg.version) },
  banner: { js: "#!/usr/bin/env node" },
  // ws reaches for these native speed-ups when they are there and does without otherwise
  external: ["bufferutil", "utf-8-validate"],
  logLevel: "info",
});
