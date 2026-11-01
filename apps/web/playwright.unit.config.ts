import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./unit",
  workers: 1,
  retries: 0,
  timeout: 10_000,
});
