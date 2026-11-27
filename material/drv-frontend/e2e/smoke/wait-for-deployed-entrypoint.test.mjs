import assert from 'node:assert/strict';
import test from 'node:test';

import {
  entrypointUrl,
  sha256,
  waitForDeployedEntrypoint,
} from './wait-for-deployed-entrypoint.mjs';

const NEW_CONTENT = Buffer.from('new deployed main bundle');
const OLD_CONTENT = Buffer.from('old cached main bundle');
const EXPECTED_SHA = sha256(NEW_CONTENT);

function clock() {
  let current = 0;
  return {
    now: () => current,
    sleep: async (milliseconds) => {
      current += milliseconds;
    },
  };
}

test('joins an environment-neutral base URL and relative entrypoint', () => {
  assert.equal(
    entrypointUrl('https://frontend.example.test', 'main.js'),
    'https://frontend.example.test/main.js',
  );
  assert.equal(
    entrypointUrl('https://frontend.example.test/base/', './assets/main.js'),
    'https://frontend.example.test/base/assets/main.js',
  );
});

test('rejects unsafe base URLs and entrypoint paths', () => {
  assert.throws(
    () => entrypointUrl('file:///tmp/frontend', 'main.js'),
    /must use http or https/,
  );
  assert.throws(
    () => entrypointUrl('https://user:secret@example.test/', 'main.js'),
    /must not contain credentials/,
  );
  for (const unsafePath of [
    '../main.js',
    'assets/../main.js',
    'https://other.example.test/main.js',
    '//other.example.test/main.js',
  ]) {
    assert.throws(
      () => entrypointUrl('https://frontend.example.test/', unsafePath),
      /must be a safe relative path/,
    );
  }
});

test('retries an old cached hash and accepts only the expected content', async () => {
  const time = clock();
  const responses = [OLD_CONTENT, NEW_CONTENT];
  const logs = [];

  const result = await waitForDeployedEntrypoint({
    baseUrl: 'https://frontend.example.test/',
    entrypointPath: 'main.js',
    expectedSha256: EXPECTED_SHA,
    envLabel: 'test',
    timeoutMs: 100,
    intervalMs: 10,
    requestTimeoutMs: 20,
    fetchImpl: async () => new Response(responses.shift(), { status: 200 }),
    now: time.now,
    sleep: time.sleep,
    log: (message) => logs.push(message),
  });

  assert.equal(result.attempt, 2);
  assert.equal(result.sha256, EXPECTED_SHA);
  assert.match(logs.join('\n'), /SHA-256 mismatch/);
  assert.match(logs.join('\n'), /expected EntryPoint SHA-256 confirmed/);
});

test('retries transient HTTP failures within the fixed budget', async () => {
  const time = clock();
  let calls = 0;

  const result = await waitForDeployedEntrypoint({
    baseUrl: 'https://frontend.example.test/',
    entrypointPath: 'assets/main.js',
    expectedSha256: EXPECTED_SHA,
    envLabel: 'qa-like-label',
    timeoutMs: 100,
    intervalMs: 10,
    requestTimeoutMs: 20,
    fetchImpl: async () => {
      calls += 1;
      return calls === 1
        ? new Response('not ready', { status: 503 })
        : new Response(NEW_CONTENT, { status: 200 });
    },
    now: time.now,
    sleep: time.sleep,
    log: () => {},
  });

  assert.equal(result.attempt, 2);
});

test('fails after the budget while an old hash is still served', async () => {
  const time = clock();

  await assert.rejects(
    waitForDeployedEntrypoint({
      baseUrl: 'https://frontend.example.test/',
      entrypointPath: 'main.js',
      expectedSha256: EXPECTED_SHA,
      envLabel: 'prod-like-label',
      timeoutMs: 25,
      intervalMs: 10,
      requestTimeoutMs: 20,
      fetchImpl: async () => new Response(OLD_CONTENT, { status: 200 }),
      now: time.now,
      sleep: time.sleep,
      log: () => {},
    }),
    /timed out after 25ms and 3 attempt\(s\).*SHA-256 mismatch/,
  );
});

test('rejects missing inputs and malformed hashes', async () => {
  const common = {
    baseUrl: 'https://frontend.example.test/',
    entrypointPath: 'main.js',
    envLabel: 'test',
  };

  await assert.rejects(
    waitForDeployedEntrypoint({ ...common, expectedSha256: '' }),
    /FRONTEND_ENTRYPOINT_SHA256 is required/,
  );
  await assert.rejects(
    waitForDeployedEntrypoint({ ...common, expectedSha256: 'abc' }),
    /64-character SHA-256/,
  );
});
