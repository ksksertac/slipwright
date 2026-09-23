import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // the tree module imports vscode, which only exists inside the editor
    alias: { vscode: new URL("./test/vscode-stub.ts", import.meta.url).pathname },
    include: ["test/**/*.test.ts"],
  },
});
