import { defineConfig } from '@playwright/test';

import { chromiumSmokeProject } from './playwright.smoke.shared';

export default defineConfig({
  testDir: './e2e/smoke',
  testMatch: 'frontend-bootstrap.spec.ts',
  outputDir: 'e2e/test-results/smoke',
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
    ['html', { outputFolder: 'e2e/playwright-report/smoke', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
  projects: [chromiumSmokeProject('chromium-smoke')],
  webServer: {
    command: 'node e2e/smoke/static-server.mjs',
    url: 'http://127.0.0.1:4173/',
    reuseExistingServer: false,
    timeout: 10_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
