import { expect, type Page } from '@playwright/test';

interface BootstrapOptions {
  artifactHeader?: string;
}

export interface FrontendSmokeConfiguration {
  anonymousAccess: boolean;
}

export function frontendSmokeConfiguration(
  environment: Record<string, string | undefined> = process.env,
): FrontendSmokeConfiguration {
  const value = environment['FRONTEND_ANONYMOUS_ACCESS'];
  if (value !== 'true' && value !== 'false') {
    throw new Error(
      `FRONTEND_ANONYMOUS_ACCESS must be exactly true or false, got '${value ?? ''}'`,
    );
  }

  return { anonymousAccess: value === 'true' };
}

export async function expectConfiguredFrontendBootstrap(
  page: Page,
  options: BootstrapOptions = {},
) {
  const configuration = frontendSmokeConfiguration();
  const startupErrors: string[] = [];

  page.on('pageerror', (error) => {
    startupErrors.push(`[pageerror] ${error.stack ?? error.message}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location();
      const source = location.url
        ? ` (${location.url}:${location.lineNumber}:${location.columnNumber})`
        : '';
      startupErrors.push(`[console.error] ${message.text()}${source}`);
    }
  });

  const diagnostics = () =>
    startupErrors.length === 0
      ? 'No pageerror or console.error messages were captured.'
      : `Browser startup errors:\n${startupErrors.join('\n')}`;

  try {
    const response = await page.goto('/#/', {
      waitUntil: 'load',
    });

    expect(
      response,
      'The frontend must return a navigation response.',
    ).not.toBeNull();
    expect(
      response?.ok(),
      `Navigation failed with HTTP ${response?.status()}.`,
    ).toBe(true);

    if (options.artifactHeader) {
      expect(
        response?.headers()['x-frontend-smoke-artifact'],
        'The smoke must be served by the production-dist static server, not a dev server.',
      ).toBe(options.artifactHeader);
    }

    await expect(
      page.locator('.drv-page'),
      'Angular must render the application shell after bootstrap.',
    ).toBeVisible();

    const expectedHash = configuration.anonymousAccess ? '#/chat' : '#/login';
    const expectedSelector = configuration.anonymousAccess
      ? 'drv-chat-page'
      : 'drv-login';
    await expect
      .poll(() => new URL(page.url()).hash, {
        message: `The configured landing route must be ${expectedHash}.`,
      })
      .toBe(expectedHash);
    await expect(
      page.locator(expectedSelector),
      `The configured landing component ${expectedSelector} must be visible.`,
    ).toBeVisible();
  } catch (error) {
    const detail =
      error instanceof Error ? (error.stack ?? error.message) : String(error);
    throw new Error(`${detail}\n\n${diagnostics()}`);
  }

  expect(startupErrors, diagnostics()).toEqual([]);
}
