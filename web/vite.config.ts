import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// The production build lands inside the Python package so `slipwright serve` can serve
// it at `/`; in development Vite proxies `/api` to the Python server.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../slipwright/api/static", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.SLIPWRIGHT_API ?? "http://127.0.0.1:8500",
        changeOrigin: false,
      },
    },
  },
});
