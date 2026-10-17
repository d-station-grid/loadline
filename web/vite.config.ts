import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // OpenAPI からの生成物とテストの準備は、数字に入れない
      exclude: ["src/api/**", "src/test/**", "src/**/*.test.{ts,tsx}"],
      reporter: ["text", "json-summary"],
    },
  },
});
