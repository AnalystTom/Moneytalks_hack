import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./browser-tests",
  workers: 1,
  outputDir: process.env.COUNCIL_TEST_OUTPUT || "/tmp/council-layout-results",
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    launchOptions: { executablePath: process.env.COUNCIL_CHROMIUM_PATH },
  },
  webServer: {
    command: "npm run preview -- --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
