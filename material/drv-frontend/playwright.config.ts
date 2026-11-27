import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for E2E tests
 * See https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './e2e/tests',
  timeout: 30000,
  expect: {
    timeout: 20000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { outputFolder: 'e2e/playwright-report' }],
    ['json', { outputFile: 'e2e/test-results.json' }],
    ['list'],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:4200',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10000,
  },

  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: 'frontend-extern-chrome',
      testDir: './e2e/frontend-extern',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:4200',
        storageState: './e2e/.auth/user-extern.json',
      },
      dependencies: ['setup'],
    },
    {
      name: 'frontend-extern-firefox',
      testDir: './e2e/frontend-extern',
      use: {
        ...devices['Desktop Firefox'],
        baseURL: 'http://localhost:4200',
        storageState: './e2e/.auth/user-extern.json',
      },
      dependencies: ['setup'],
    },
    {
      name: 'frontend-intern-chrome',
      testDir: './e2e/frontend-intern',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:4201',
        storageState: './e2e/.auth/user-intern.json',
      },
      dependencies: ['setup'],
    },
    {
      name: 'frontend-intern-firefox',
      testDir: './e2e/frontend-intern',
      use: {
        ...devices['Desktop Firefox'],
        baseURL: 'http://localhost:4201',
        storageState: './e2e/.auth/user-intern.json',
      },
      dependencies: ['setup'],
    },
    // {
    //   name: 'chromium',
    //   use: { ...devices['Desktop Chrome'] },
    // },
  ],

  // Patrick: Je nachdem wie das Frontend für die e2e Tests gestartet werden kann, müsst ihr
  // ggfs den 'command' anpassen
  webServer: [
    {
      name: 'frontend-extern',
      command: 'npm run dev',
      port: 4200,
      reuseExistingServer: !process.env.CI,
    },
    {
      name: 'frontend-intern',
      command: 'npm run dev:intern',
      port: 4201,
      reuseExistingServer: !process.env.CI,
    },
  ],

  //   webServer: {
  //     command: 'npm run local',
  //     url: 'http://localhost:4200',
  //     reuseExistingServer: !process.env.CI,
  //     timeout: 120000,
  //   },
});
