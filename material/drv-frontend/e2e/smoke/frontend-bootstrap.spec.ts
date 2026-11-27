import { test } from '@playwright/test';

import { expectConfiguredFrontendBootstrap } from './frontend-bootstrap.assertions';

const ARTIFACT_HEADER = 'production-dist';

test('production artifact bootstraps its configured landing route', async ({
  page,
}) => {
  await expectConfiguredFrontendBootstrap(page, {
    artifactHeader: ARTIFACT_HEADER,
  });
});
