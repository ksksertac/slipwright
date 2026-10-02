import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

// The tests run inside workerd, against the real Durable Object and real sockets, so what
// they prove is what the deployed relay does -- not what a mock of it would.
export default defineConfig({
  plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.toml" } })],
});
