import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";
import type { Plugin } from "vite";

// Nothing is loaded from the network: fonts and the logo are bundled, and the page has no
// business fetching anything (the main process does all of that). Only in the built app:
// the dev server's hot reload needs an inline script this would block.
const csp: Plugin = {
  name: "slipwright-csp",
  apply: "build",
  transformIndexHtml: (html) =>
    html.replace(
      "<head>",
      `<head>\n    <meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'" />`,
    ),
};

// Three builds, as electron-vite lays them out: the main process (Node, owns everything
// that touches the network, the disk or a child process), the preload (the one typed
// bridge) and the renderer (a sandboxed page that only draws).
export default defineConfig({
  main: {
    resolve: { alias: { "@shared": resolve("src/shared") } },
  },
  preload: {
    resolve: { alias: { "@shared": resolve("src/shared") } },
  },
  renderer: {
    resolve: { alias: { "@shared": resolve("src/shared") } },
    plugins: [react(), csp],
  },
});
