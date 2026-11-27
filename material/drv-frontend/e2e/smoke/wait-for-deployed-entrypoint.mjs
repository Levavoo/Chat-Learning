import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

function required(value, name) {
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function positiveInteger(value, name, fallback) {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

export function entrypointUrl(baseUrl, entrypointPath) {
  const base = new URL(required(baseUrl, 'FRONTEND_BASE_URL'));
  if (!['http:', 'https:'].includes(base.protocol)) {
    throw new Error('FRONTEND_BASE_URL must use http or https');
  }
  if (base.username || base.password) {
    throw new Error('FRONTEND_BASE_URL must not contain credentials');
  }

  base.hash = '';
  base.search = '';
  if (!base.pathname.endsWith('/')) {
    base.pathname += '/';
  }

  const rawPath = required(entrypointPath, 'FRONTEND_ENTRYPOINT_PATH');
  if (/^[a-z][a-z\d+.-]*:/i.test(rawPath) || rawPath.startsWith('//')) {
    throw new Error('FRONTEND_ENTRYPOINT_PATH must be a safe relative path');
  }
  const relativePath = rawPath.replace(/^\.?\//, '');
  if (!relativePath || relativePath.split('/').includes('..')) {
    throw new Error('FRONTEND_ENTRYPOINT_PATH must be a safe relative path');
  }
  return new URL(relativePath, base).toString();
}

export function sha256(content) {
  return createHash('sha256').update(content).digest('hex');
}

export async function waitForDeployedEntrypoint({
  baseUrl,
  entrypointPath,
  expectedSha256,
  envLabel,
  timeoutMs = 120_000,
  intervalMs = 5_000,
  requestTimeoutMs = 15_000,
  fetchImpl = fetch,
  sleep = (milliseconds) =>
    new Promise((resolve) => setTimeout(resolve, milliseconds)),
  now = Date.now,
  log = console.log,
}) {
  required(envLabel, 'ENV_LABEL');
  const expected = required(
    expectedSha256,
    'FRONTEND_ENTRYPOINT_SHA256',
  ).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(expected)) {
    throw new Error(
      'FRONTEND_ENTRYPOINT_SHA256 must be a 64-character SHA-256',
    );
  }

  const url = entrypointUrl(baseUrl, entrypointPath);
  const deadline = now() + timeoutMs;
  let attempt = 0;
  let lastFailure = 'no request attempted';

  log(`Frontend readiness [${envLabel}]`);
  log(`EntryPoint URL: ${url}`);
  log(`Expected SHA-256: ${expected}`);
  log(
    `Readiness budget: ${timeoutMs}ms; interval: ${intervalMs}ms; request timeout: ${requestTimeoutMs}ms`,
  );

  while (now() < deadline) {
    attempt += 1;
    try {
      const response = await fetchImpl(url, {
        headers: {
          'cache-control': 'no-cache',
          pragma: 'no-cache',
        },
        redirect: 'follow',
        signal: AbortSignal.timeout(requestTimeoutMs),
      });

      if (!response.ok) {
        lastFailure = `HTTP ${response.status}`;
        log(`Attempt ${attempt}: ${lastFailure}; retrying`);
      } else {
        const actual = sha256(Buffer.from(await response.arrayBuffer()));
        if (actual === expected) {
          log(`Attempt ${attempt}: expected EntryPoint SHA-256 confirmed`);
          return { attempt, url, sha256: actual };
        }
        lastFailure = `SHA-256 mismatch (actual ${actual})`;
        log(`Attempt ${attempt}: ${lastFailure}; retrying`);
      }
    } catch (error) {
      lastFailure =
        error instanceof Error
          ? `${error.name}: ${error.message}`
          : String(error);
      log(`Attempt ${attempt}: ${lastFailure}; retrying`);
    }

    const remaining = deadline - now();
    if (remaining <= 0) {
      break;
    }
    await sleep(Math.min(intervalMs, remaining));
  }

  throw new Error(
    `Frontend readiness [${envLabel}] timed out after ${timeoutMs}ms and ${attempt} attempt(s): ${lastFailure}; expected ${entrypointPath} SHA-256 ${expected}`,
  );
}

async function main() {
  await waitForDeployedEntrypoint({
    baseUrl: process.env.FRONTEND_BASE_URL,
    entrypointPath: process.env.FRONTEND_ENTRYPOINT_PATH,
    expectedSha256: process.env.FRONTEND_ENTRYPOINT_SHA256,
    envLabel: process.env.ENV_LABEL,
    timeoutMs: positiveInteger(
      process.env.FRONTEND_READINESS_TIMEOUT_MS,
      'FRONTEND_READINESS_TIMEOUT_MS',
      120_000,
    ),
    intervalMs: positiveInteger(
      process.env.FRONTEND_READINESS_INTERVAL_MS,
      'FRONTEND_READINESS_INTERVAL_MS',
      5_000,
    ),
    requestTimeoutMs: positiveInteger(
      process.env.FRONTEND_REQUEST_TIMEOUT_MS,
      'FRONTEND_REQUEST_TIMEOUT_MS',
      15_000,
    ),
  });
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch((error) => {
    console.error(
      `deployed frontend readiness failed: ${error instanceof Error ? error.message : String(error)}`,
    );
    process.exitCode = 1;
  });
}
