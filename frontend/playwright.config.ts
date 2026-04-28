import { existsSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";


const frontendBaseUrl = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173";
const localPlaywrightChromiumExecutablePath = process.env.LOCALAPPDATA
  ? path.join(
      process.env.LOCALAPPDATA,
      "ms-playwright",
      "chromium-1217",
      "chrome-win64",
      "chrome.exe",
    )
  : undefined;
const resolvedChromiumExecutablePath =
  localPlaywrightChromiumExecutablePath !== undefined && existsSync(localPlaywrightChromiumExecutablePath)
    ? localPlaywrightChromiumExecutablePath
    : undefined;


/** Configure Playwright for the local dashboard workflow. */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: frontendBaseUrl,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions:
          resolvedChromiumExecutablePath !== undefined
            ? { executablePath: resolvedChromiumExecutablePath }
            : undefined,
      },
    },
  ],
});