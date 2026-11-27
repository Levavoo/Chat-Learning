import { expect, test } from '@playwright/test';

import {
  expectConfiguredFrontendBootstrap,
  frontendSmokeConfiguration,
} from './frontend-bootstrap.assertions';

for (const anonymousAccess of [false, true]) {
  test(`parses frontend smoke configuration anonymousAccess=${anonymousAccess}`, () => {
    expect(
      frontendSmokeConfiguration({
        FRONTEND_ANONYMOUS_ACCESS: String(anonymousAccess),
      }),
    ).toEqual({ anonymousAccess });
  });
}

test('rejects missing or invalid frontend smoke configuration', () => {
  expect(() =>
    frontendSmokeConfiguration({
      FRONTEND_ANONYMOUS_ACCESS: 'yes',
    }),
  ).toThrow(/FRONTEND_ANONYMOUS_ACCESS must be exactly true or false/);
  expect(() => frontendSmokeConfiguration({})).toThrow(
    /FRONTEND_ANONYMOUS_ACCESS must be exactly true or false/,
  );
});

test('deployed frontend bootstraps its configured landing route', async ({
  page,
}) => {
  await expectConfiguredFrontendBootstrap(page);
});
