# E2E Tests for Digibro Chatbot

End-to-end tests using Playwright for testing the complete chat application with Bedrock Agent integration.

## Prerequisites

- Node.js 18+ installed
- Frontend application configured with valid AWS endpoints
- Playwright browsers installed

## Installation

```bash
# Install Playwright browsers (first time only)
npx playwright install

# Or install specific browser
npx playwright install chromium
```

## Production frontend bootstrap smoke

The isolated bootstrap smoke builds and tests the deployable production artifact. It does not start the general Playwright E2E stack, Angular development servers, authentication setup, a backend, or AWS services.

Prerequisites:

- dependencies installed with `npm ci`;
- an existing Chromium-compatible browser on Linux;
- `CHROME_BIN` pointing to that executable when it is not available as `chromium`, `chromium-browser`, `google-chrome`, or `google-chrome-stable` on `PATH`.

Run the same entry point used by GitLab CI:

```bash
npm run test:smoke:frontend
```

The command runs `npm run build:prod`, serves only `dist/ng-digibro-frontend/browser`, and opens `/#/` in headless Chromium. It explicitly removes these optional IdP variables instead of assigning empty or test values:

- `NG_APP_REDIRECT_SIGNIN_URL`
- `NG_APP_REDIRECT_SIGNOUT_URL`
- `NG_APP_COGNITO_DOMAIN`

Syntactically valid local test values are supplied for the required Cognito and frontend settings; no login is attempted. The test fails on every startup `pageerror` or `console.error`, requires `.drv-page`, and verifies the configured landing route: `#/login` with `drv-login` when anonymous access is disabled, or `#/chat` with `drv-chat-page` when it is enabled. Browser downloads are intentionally not part of this command or the CI job.

For the merge request, record:

1. the successful production build and browser smoke with the optional IdP variables absent;
2. the one-time isolated negative run using the direct access form from `b7812a1a`, including its browser error;
3. the successful run after restoring `import.meta.env?.KEY`;
4. the successful `frontend-tests`, `frontend-build`, and `frontend-browser-smoke` jobs.

The historical regression must only be reproduced in a disposable local working copy. Do not commit, push, or run that temporary change in a merge request pipeline.

## Deployed frontend browser smoke

The post-deploy mode tests an already deployed frontend. It does **not** build the frontend, start `ng serve` or a local static server, query AWS, install a browser, authenticate a user, or call backend/retrieval functionality.

Provide the deployment evidence and run the same environment-neutral npm entry point used by CI:

```bash
cd drv-frontend
FRONTEND_BASE_URL="https://frontend.example.test/" \
ENV_LABEL="isolated-test" \
FRONTEND_ENTRYPOINT_PATH="main.js" \
FRONTEND_ENTRYPOINT_SHA256="<64-character-sha256>" \
FRONTEND_ANONYMOUS_ACCESS="false" \
CHROME_BIN="$(command -v chromium)" \
npm run test:smoke:deployed
```

Optional bounded readiness settings are `FRONTEND_READINESS_TIMEOUT_MS` (default `120000`), `FRONTEND_READINESS_INTERVAL_MS` (default `5000`), and `FRONTEND_REQUEST_TIMEOUT_MS` (default `15000`). The runner repeatedly fetches the exact EntryPoint URL until its content matches `FRONTEND_ENTRYPOINT_SHA256`. Only network, HTTP, and stale-content states are retried. After the expected content is confirmed, Playwright starts once, opens `/#/`, fails on every `pageerror` or `console.error`, requires `.drv-page`, and verifies the configured Login- or Chat-Landing-Page.

In GitLab, the same post-deploy browser-smoke runtime is active for Dev, QA, and Prod. Each environment job consumes `FRONTEND_DEPLOYED=true`, `CF_URL`, `FRONTEND_ENTRYPOINT_PATH`, `FRONTEND_ENTRYPOINT_SHA256`, and `FRONTEND_ANONYMOUS_ACCESS` directly from its own `deploy-frontend:<env>` dotenv artifact. Dev runs in the root pipeline; QA and Prod run in their protected promotion child pipelines and are excluded from non-mutating rehearsals. A false, missing, or incomplete deployment signal fails closed. Preprod is not enabled by this rollout. Failure screenshots, traces, and the HTML report are retained as short-lived job artifacts.

## Running Tests

### Run all E2E tests

```bash
npm run test:e2e
```

### Run only Bedrock integration tests

```bash
npm run test:e2e:bedrock
```

### Run tests in UI mode (interactive)

```bash
npm run test:e2e:ui
```

### Run tests in debug mode

```bash
npm run test:e2e:debug
```

### View test report

```bash
npm run test:e2e:report
```

## Test Structure

```
e2e/
├── tests/
│   └── bedrock-integration.spec.ts   # Bedrock Agent integration tests
├── fixtures/
│   └── bedrock-scenarios.ts          # Test data and scenarios
├── utils/
│   └── chat-helpers.ts               # Utility functions for tests
└── playwright.config.ts              # Playwright configuration
```

## Test Coverage

### Bedrock Integration Tests

- **Conversation Flow**: Tests basic send/receive functionality
- **Context Continuity**: Verifies agent remembers conversation history
- **Multi-turn Conversations**: Tests complex conversations with multiple exchanges
- **Session Persistence**: Tests session ID persistence across page refreshes
- **New Conversation**: Tests starting fresh conversations with new session IDs
- **Error Handling**: Tests error scenarios and graceful degradation
- **Performance**: Tests response times and loading states
- **API Integration**: Verifies correct API request format with session IDs

## Configuration

Tests can be configured via environment variables:

```bash
# Base URL (defaults to http://localhost:4200)
BASE_URL=https://your-deployed-app.com npm run test:e2e

# Run in CI mode with retries
CI=true npm run test:e2e
```

## Test Timeouts

- Default test timeout: 30 seconds
- Expect timeout: 10 seconds
- Action timeout: 10 seconds

These are increased from defaults to accommodate Bedrock Agent response times.

## CI/CD Integration

Tests are configured to run differently in CI environments:

- Retries: 2 retries in CI, 0 locally
- Workers: 1 worker in CI, parallel locally
- Screenshots/Videos: Only on failure

## Troubleshooting

### Tests timing out

- Increase timeout values in `playwright.config.ts`
- Check that backend is responding properly
- Verify AWS credentials and Bedrock access

### Cannot find elements

- Check element selectors match actual DOM structure
- Use `npm run test:e2e:ui` to debug interactively
- Add `await page.pause()` in tests to inspect

### Tests failing intermittently

- Check for race conditions
- Add appropriate `waitFor` calls
- Verify network stability

## Best Practices

1. **Non-deterministic responses**: Use flexible assertions (regex, contains) rather than exact matches
2. **Longer timeouts**: Bedrock responses can take 2-10 seconds
3. **Retry logic**: Tests have retries enabled in CI
4. **Isolated tests**: Each test should be independent
5. **Clean state**: Tests start with fresh sessions

## Writing New Tests

Use the helper functions from `utils/chat-helpers.ts`:

```typescript
import { test, expect } from '@playwright/test';
import { sendMessage, waitForAssistantResponse } from '../utils/chat-helpers';

test('my new test', async ({ page }) => {
  await page.goto('/');
  await sendMessage(page, 'Hello');
  const response = await waitForAssistantResponse(page);
  expect(response).toBeTruthy();
});
```

## Performance Benchmarks

Expected response times:

- First message (cold start): < 15 seconds
- Follow-up messages: < 5 seconds
- Page load: < 3 seconds

## References

- [Playwright Documentation](https://playwright.dev/)
- [Testing Best Practices](https://playwright.dev/docs/best-practices)
- [Story 3.4](../../docs/sprint-artifacts/3-4-e2e-test-bedrock-integration.md)
