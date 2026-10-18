import type { Config } from "tailwindcss";

export default {
  // lib/ is included because band colour classes are defined in lib/bands.ts.
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#1f5f3b", dark: "#174a2e", light: "#e8f2ec" },
        accent: "#c8781a",
        band: {
          "very-bad": "#c62828",
          bad: "#ef6c00",
          good: "#f2b300",
          "very-good": "#7cb342",
          excellent: "#2e7d32",
        },
      },
      fontFamily: { sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
    },
  },
  plugins: [],
} satisfies Config;
