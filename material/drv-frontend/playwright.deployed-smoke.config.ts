import { defineConfig } from '@playwright/test';

import { chromiumSmokeProject } from './playwright.smoke.shared';

const baseURL = process.env.FRONTEND_BASE_URL;
if (!baseURL) {
  throw new Error(
    'FRONTEND_BASE_URL is required for the deployed frontend smoke; no fallback URL is allowed',
  );
}

export default defineConfig({
  testDir: './e2e/smoke',
  testMatch: 'deployed-frontend.spec.ts',
  outputDir: 'e2e/test-results/deployed-smoke',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  preserveOutput: 'failures-only',
  reporter: [
    ['list'],
    [
      'html',
      {
        outputFolder: 'e2e/playwright-report/deployed-smoke',
        open: 'never',
      },
    ],
  ],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
  projects: [chromiumSmokeProject('chromium-deployed-smoke')],
});
