import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// eslint-config-next 16 ships native flat configs, so no FlatCompat wrapper is needed.
const config = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "node_modules/**",
    "lib/api/schema.d.ts",
    "playwright-report/**",
    "test-results/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // XSS defence (edge case 47): extracted product names are rendered as text only.
      "react/no-danger": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
]);

export default config;
