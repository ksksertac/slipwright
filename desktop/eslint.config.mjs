import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["out", "dist", "node_modules", "build"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/main/**/*.ts", "src/preload/**/*.ts", "test/**/*.ts", "*.ts", "scripts/**/*.cjs"],
    languageOptions: { globals: globals.node },
  },
  { files: ["scripts/**/*.cjs"], rules: { "@typescript-eslint/no-require-imports": "off" } },
  {
    files: ["src/renderer/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
);
