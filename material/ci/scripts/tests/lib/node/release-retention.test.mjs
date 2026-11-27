import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  DEFAULT_CONCURRENCY,
  PINNED,
  RETENTION_TAG_KEY,
  UNPINNED,
  applyState,
  auditObjects,
  classifyObject,
  commandExitCode,
  desiredRetentionState,
  executeCommand,
  isRetryableAwsError,
  mapBounded,
  mergeRetentionTag,
  reconcileObjects,
  reconciliationPhases,
  retryOperation,
  AwsS3Sdk,
  isoSecondsUtc,
} from '../../../lib/node/release-retention.mjs';

const SCRIPT = fileURLToPath(
  new URL('../../../lib/node/release-retention.mjs', import.meta.url),
);

function object(Key) {
  return { Key, LastModified: '2026-04-01T00:00:00Z' };
}

function tags(state, extra = []) {
  return state
    ? [...extra, { Key: RETENTION_TAG_KEY, Value: state }]
    : [...extra];
}

function options(overrides = {}) {
  return {
    bucket: 'test-bucket',
    region: 'eu-central-1',
    profile: '',
    prefixes: ['releases/'],
    managedPrefixes: ['releases/'],
    protectedPrefixes: [],
    concurrency: 3,
    dryRun: false,
    failOnDrift: false,
    now: new Date('2026-07-17T00:00:00Z'),
    ...overrides,
  };
}

function captureRuntime() {
  const stdout = [];
  const stderr = [];
  return {
    runtime: {
      stdout: (value) => stdout.push(value),
      stderr: (value) => stderr.push(value),
      nowMs: () => 1_000,
      retries: 0,
      metrics: {
        objects_listed: 0,
        objects_scanned: 0,
        retention_tag_reads: 0,
        retention_tag_writes: 0,
        verification_reads: 0,
        s3_error_codes: [],
      },
    },
    stdout,
    stderr,
  };
}

class MemoryAws {
  constructor(objects, states, configuration = {}) {
    this.objects = objects;
    this.tagSets = new Map(
      Object.entries(states).map(([key, tagSet]) => [
        key,
        structuredClone(tagSet),
      ]),
    );
    this.delays = configuration.delays ?? {};
    this.getErrors = configuration.getErrors ?? {};
    this.verifyOverrides = configuration.verifyOverrides ?? {};
    this.events = [];
    this.getCounts = new Map();
    this.putCount = 0;
    this.active = 0;
    this.maxActive = 0;
  }

  async #activity(key, callback) {
    this.active += 1;
    this.maxActive = Math.max(this.maxActive, this.active);
    try {
      const delay = this.delays[key] ?? 0;
      if (delay > 0) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      } else {
        await Promise.resolve();
      }
      return callback();
    } finally {
      this.active -= 1;
    }
  }

  async listObjects(_bucket, prefix) {
    this.events.push(`list:${prefix}`);
    return this.objects.filter((item) => item.Key.startsWith(prefix));
  }

  async getTags(_bucket, key) {
    this.events.push(`get:${key}`);
    const count = (this.getCounts.get(key) ?? 0) + 1;
    this.getCounts.set(key, count);
    return this.#activity(key, () => {
      if (this.getErrors[key]) throw this.getErrors[key];
      if (count > 1 && this.verifyOverrides[key]) {
        return structuredClone(this.verifyOverrides[key]);
      }
      return structuredClone(this.tagSets.get(key) ?? []);
    });
  }

  async putTags(_bucket, key, tagSet) {
    this.events.push(`put:${key}`);
    this.putCount += 1;
    return this.#activity(key, () => {
      this.tagSets.set(key, structuredClone(tagSet));
    });
  }
}

test('updating retention preserves unrelated object tags', () => {
  assert.deepEqual(
    mergeRetentionTag(
      [
        { Key: 'owner', Value: 'retrieval' },
        { Key: RETENTION_TAG_KEY, Value: UNPINNED },
      ],
      PINNED,
    ),
    [
      { Key: 'owner', Value: 'retrieval' },
      { Key: RETENTION_TAG_KEY, Value: PINNED },
    ],
  );
});

test('active and previous releases are excluded while a 91-day unpinned release is eligible', () => {
  const now = new Date('2026-07-17T00:00:00Z');
  const oldObject = (Key) => ({ Key, LastModified: '2026-04-17T00:00:00Z' });
  const unpinned = [{ Key: RETENTION_TAG_KEY, Value: UNPINNED }];

  assert.equal(
    classifyObject(oldObject('releases/v1.2.0/a.xml'), unpinned, [], now)
      .eligible,
    true,
  );
  assert.equal(
    classifyObject(
      oldObject('releases/v1.3.0/a.xml'),
      unpinned,
      ['releases/v1.3.0/'],
      now,
    ).eligible,
    false,
  );
  assert.equal(
    classifyObject(oldObject('releases/v1.4.0/a.xml'), [], [], now).eligible,
    false,
  );
  assert.equal(
    classifyObject(oldObject('releases/v1.4.0/a.xml'), [], [], now).drift,
    true,
  );
  assert.equal(
    classifyObject(
      oldObject('releases/v1.3.0/a.xml'),
      unpinned,
      ['releases/v1.3.0/'],
      now,
    ).drift,
    true,
  );
  assert.equal(
    classifyObject(
      oldObject('releases/v1.3.0/a.xml'),
      [{ Key: RETENTION_TAG_KEY, Value: PINNED }],
      ['releases/v1.3.0/'],
      now,
    ).drift,
    false,
  );
});

test('reconciliation maps every protected prefix to pinned and everything else to unpinned', () => {
  const protectedPrefixes = ['releases/v1.4.0/', 'releases/v1.3.0/'];
  assert.equal(
    desiredRetentionState('releases/v1.4.0/xml/a.xml', protectedPrefixes),
    PINNED,
  );
  assert.equal(
    desiredRetentionState('releases/v1.2.0/xml/a.xml', protectedPrefixes),
    UNPINNED,
  );
  assert.deepEqual(
    reconciliationPhases(
      [
        { Key: 'releases/v1.2.0/xml/a.xml' },
        { Key: 'releases/v1.4.0/xml/a.xml' },
      ],
      protectedPrefixes,
    ),
    {
      pin: [{ Key: 'releases/v1.4.0/xml/a.xml' }],
      unpin: [{ Key: 'releases/v1.2.0/xml/a.xml' }],
    },
  );
});

test('bounded mapper never exceeds the configured concurrency', async () => {
  let active = 0;
  let maximum = 0;
  const results = await mapBounded(
    Array.from({ length: 20 }, (_, index) => index),
    4,
    async (value) => {
      active += 1;
      maximum = Math.max(maximum, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
      return value * 2;
    },
  );

  assert.equal(maximum, 4);
  assert.deepEqual(
    results,
    Array.from({ length: 20 }, (_, index) => index * 2),
  );
});

test('pin bounds tag reads and writes, preserves other tags, and verifies independently', async () => {
  const objects = Array.from({ length: 12 }, (_, index) =>
    object(`releases/v1/a-${String(index).padStart(2, '0')}.xml`),
  );
  const aws = new MemoryAws(
    objects,
    Object.fromEntries(
      objects.map((item) => [
        item.Key,
        tags(UNPINNED, [{ Key: 'owner', Value: 'retrieval' }]),
      ]),
    ),
    {
      delays: Object.fromEntries(objects.map((item) => [item.Key, 2])),
    },
  );
  const captured = captureRuntime();

  const result = await applyState(
    aws,
    options({ concurrency: 3 }),
    objects,
    PINNED,
    captured.runtime,
  );

  assert.ok(aws.maxActive > 1);
  assert.ok(aws.maxActive <= 3);
  assert.equal(aws.putCount, objects.length);
  assert.deepEqual(result, {
    total: objects.length,
    changed: objects.length,
    unchanged: 0,
    verified: objects.length,
  });
  for (const item of objects) {
    assert.equal(aws.getCounts.get(item.Key), 2);
    assert.deepEqual(aws.tagSets.get(item.Key), [
      { Key: 'owner', Value: 'retrieval' },
      { Key: RETENTION_TAG_KEY, Value: PINNED },
    ]);
  }
  assert.match(
    captured.stderr.join(''),
    /progress operation=pin\/verify completed=12 total=12 elapsed_ms=0/,
  );
});

test('already-correct objects are verified by the initial read without a redundant read-back', async () => {
  const objects = [object('releases/v1/a.xml'), object('releases/v1/b.xml')];
  const aws = new MemoryAws(objects, {
    'releases/v1/a.xml': tags(PINNED),
    'releases/v1/b.xml': tags(PINNED),
  });
  const captured = captureRuntime();

  const result = await applyState(
    aws,
    options({ concurrency: 2 }),
    objects,
    PINNED,
    captured.runtime,
  );

  assert.equal(aws.putCount, 0);
  assert.equal(aws.getCounts.get('releases/v1/a.xml'), 1);
  assert.equal(aws.getCounts.get('releases/v1/b.xml'), 1);
  assert.deepEqual(result, {
    total: 2,
    changed: 0,
    unchanged: 2,
    verified: 2,
  });
  assert.match(
    captured.stderr.join(''),
    /progress operation=pin\/verify completed=0 total=0 elapsed_ms=0/,
  );
});

test('QA-sized corpus uses bounded 24-way parallel tagging', async () => {
  const corpusSize = 3_357;
  const objects = Array.from({ length: corpusSize }, (_, index) =>
    object(`processed/releases/candidate/docs/chunk-${index}.md`),
  );
  const aws = new MemoryAws(
    objects,
    Object.fromEntries(objects.map((item) => [item.Key, tags(UNPINNED)])),
    {
      // A serial implementation would spend more than 20 seconds across the
      // read/write/verify phases. Keep the test fast while proving that the
      // large-corpus path actually reaches the QA concurrency bound.
      delays: Object.fromEntries(objects.map((item) => [item.Key, 2])),
    },
  );
  const captured = captureRuntime();
  const startedAt = Date.now();

  const result = await applyState(
    aws,
    options({ concurrency: 24 }),
    objects,
    PINNED,
    captured.runtime,
  );

  assert.equal(aws.maxActive, 24);
  assert.equal(aws.putCount, corpusSize);
  assert.equal(result.total, corpusSize);
  assert.equal(result.changed, corpusSize);
  assert.equal(result.verified, corpusSize);
  assert.ok(Date.now() - startedAt < 8_000);
});

test('dry run reads once, performs no writes or verification, and keeps sorted output', async () => {
  const objects = [object('releases/a'), object('releases/b')];
  const aws = new MemoryAws(objects, {
    'releases/a': tags(UNPINNED),
    'releases/b': tags(UNPINNED),
  });
  const captured = captureRuntime();

  const result = await applyState(
    aws,
    options({ dryRun: true }),
    objects,
    PINNED,
    captured.runtime,
  );

  assert.equal(aws.putCount, 0);
  assert.equal(aws.getCounts.get('releases/a'), 1);
  assert.equal(aws.getCounts.get('releases/b'), 1);
  assert.equal(result.verified, 0);
  assert.equal(
    captured.stdout.join(''),
    'would-tag\tpinned\treleases/a\nwould-tag\tpinned\treleases/b\n',
  );
});

test('transient failures use bounded exponential backoff with jitter', async () => {
  let attempts = 0;
  const delays = [];
  const retries = [];
  const result = await retryOperation(
    async () => {
      attempts += 1;
      if (attempts < 3) throw new Error('S3 returned SlowDown');
      return 'ok';
    },
    {
      random: () => 0.5,
      sleep: async (delayMs) => delays.push(delayMs),
      onRetry: (retry) => retries.push(retry.attempt),
    },
  );

  assert.equal(result, 'ok');
  assert.equal(attempts, 3);
  assert.deepEqual(delays, [125, 250]);
  assert.deepEqual(retries, [1, 2]);
});

test('retry classification includes throttling, transient 5xx, and network errors', () => {
  for (const message of [
    'An error occurred (ThrottlingException)',
    'HTTP status code: 503 Service Unavailable',
    'upstream returned 502',
    'read ECONNRESET',
    'Read timeout on endpoint URL: "https://bucket.s3.eu-central-1.amazonaws.com/key?tagging"',
    'Could not connect to the endpoint URL',
    'Temporary failure in name resolution',
  ]) {
    assert.equal(isRetryableAwsError(new Error(message)), true, message);
  }
  assert.equal(
    isRetryableAwsError(new Error('An error occurred (AccessDenied)')),
    false,
  );
});

test('permanent failures are not retried and exhausted transient failures remain bounded', async () => {
  let permanentAttempts = 0;
  await assert.rejects(
    retryOperation(async () => {
      permanentAttempts += 1;
      throw new Error('AccessDenied');
    }),
    (error) => error.message === 'AccessDenied' && error.attempts === 1,
  );
  assert.equal(permanentAttempts, 1);

  let transientAttempts = 0;
  await assert.rejects(
    retryOperation(
      async () => {
        transientAttempts += 1;
        throw new Error('SlowDown');
      },
      { maxAttempts: 3, random: () => 0, sleep: async () => {} },
    ),
    (error) => error.message === 'SlowDown' && error.attempts === 3,
  );
  assert.equal(transientAttempts, 3);
});

test('a permanent tag failure reports the affected object key', async () => {
  const objects = [object('releases/v1/failing.xml')];
  const aws = new MemoryAws(
    objects,
    {},
    {
      getErrors: { 'releases/v1/failing.xml': new Error('AccessDenied') },
    },
  );

  await assert.rejects(
    applyState(aws, options(), objects, PINNED, captureRuntime().runtime),
    /s3:\/\/test-bucket\/releases\/v1\/failing\.xml.*AccessDenied/,
  );
});

test('reconcile verifies every protected pin before starting any unpin work', async () => {
  const objects = [
    object('releases/active/a.xml'),
    object('releases/stale/b.xml'),
  ];
  const aws = new MemoryAws(
    objects,
    {
      'releases/active/a.xml': tags(UNPINNED),
      'releases/stale/b.xml': tags(PINNED),
    },
    {
      verifyOverrides: {
        'releases/active/a.xml': tags(UNPINNED),
      },
    },
  );

  await assert.rejects(
    reconcileObjects(
      aws,
      options({ protectedPrefixes: ['releases/active/'] }),
      objects,
      captureRuntime().runtime,
    ),
    /releases\/active\/a\.xml: expected pinned, found unpinned/,
  );
  assert.ok(aws.events.includes('put:releases/active/a.xml'));
  assert.equal(
    aws.events.some((event) => event.includes('releases/stale/b.xml')),
    false,
  );
});

test('audit output and summaries stay deterministic when reads finish out of order', async () => {
  const objects = [
    object('releases/active/a'),
    object('releases/old/b'),
    object('releases/old/c'),
  ];
  const aws = new MemoryAws(
    objects,
    {
      'releases/active/a': tags(PINNED),
      'releases/old/b': tags(UNPINNED),
      'releases/old/c': tags(PINNED),
    },
    {
      delays: {
        'releases/active/a': 5,
        'releases/old/b': 2,
        'releases/old/c': 0,
      },
    },
  );
  const captured = captureRuntime();
  const auditOptions = options({
    concurrency: 3,
    protectedPrefixes: ['releases/active/'],
    failOnDrift: true,
  });

  const result = await auditObjects(
    aws,
    auditOptions,
    objects,
    captured.runtime,
  );
  const emittedKeys = captured.stdout.map((line) => JSON.parse(line).key);

  assert.deepEqual(emittedKeys, [
    'releases/active/a',
    'releases/old/b',
    'releases/old/c',
  ]);
  assert.equal(result.eligible, 1);
  assert.equal(result.drift, 1);
  assert.equal(commandExitCode('audit', auditOptions, result), 3);
  assert.equal(
    commandExitCode('audit', { ...auditOptions, failOnDrift: false }, result),
    0,
  );
});

test('successful command emits a stable final summary', async () => {
  const objects = [object('releases/active/a'), object('releases/old/b')];
  const aws = new MemoryAws(objects, {
    'releases/active/a': tags(PINNED),
    'releases/old/b': tags(UNPINNED),
  });
  const captured = captureRuntime();

  await executeCommand(
    'audit',
    aws,
    options({ protectedPrefixes: ['releases/active/'] }),
    captured.runtime,
  );

  assert.equal(
    captured.stderr.at(-1),
    'summary operation=audit outcome=success total=2 protected=1 eligible=1 drift=0 objects_listed=0 objects_scanned=2 retention_tag_reads=0 retention_tag_writes=0 verification_reads=0 s3_error_codes=none retries=0 elapsed_ms=0\n',
  );
});

test('CLI uses concurrency eight by default and rejects unsafe bounds', () => {
  assert.equal(DEFAULT_CONCURRENCY, 8);
  for (const concurrency of ['0', '65', '1.5', 'many']) {
    const result = spawnSync(
      process.execPath,
      [
        SCRIPT,
        'pin',
        '--bucket',
        'test-bucket',
        '--prefix',
        'releases/v1/',
        '--concurrency',
        concurrency,
      ],
      { encoding: 'utf8' },
    );
    assert.equal(result.status, 2, concurrency);
    assert.match(
      result.stderr,
      /--concurrency must be an integer from 1 to 64/,
    );
  }
});

test('CLI retries a transient AWS failure and retains audit drift exit semantics', () => {
  const directory = mkdtempSync(join(tmpdir(), 'release-retention-test-'));
  const awsPath = join(directory, 'aws');
  const statePath = join(directory, 'attempts');
  writeFileSync(
    awsPath,
    `#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
const args = process.argv.slice(2);
if (args[1] === 'list-objects-v2') {
  process.stdout.write(JSON.stringify({Contents:[{Key:'releases/active/a.xml',LastModified:'2026-04-01T00:00:00Z'}]}));
} else if (args[1] === 'get-object-tagging') {
  const state = process.env.FAKE_AWS_STATE;
  const attempts = existsSync(state) ? Number(readFileSync(state, 'utf8')) : 0;
  writeFileSync(state, String(attempts + 1));
  if (attempts === 0) {
    process.stderr.write('An error occurred (SlowDown)');
    process.exit(1);
  }
  process.stdout.write(JSON.stringify({TagSet:[{Key:'renate:retention',Value:'unpinned'}]}));
} else {
  process.stderr.write('unexpected fake AWS operation');
  process.exit(2);
}
`,
  );
  chmodSync(awsPath, 0o755);

  try {
    const result = spawnSync(
      process.execPath,
      [
        SCRIPT,
        'audit',
        '--bucket',
        'test-bucket',
        '--managed-prefix',
        'releases/',
        '--protected-prefix',
        'releases/active/',
        '--fail-on-drift',
        '--concurrency',
        '2',
      ],
      {
        encoding: 'utf8',
        env: {
          ...process.env,
          PATH: `${directory}:${process.env.PATH}`,
          FAKE_AWS_STATE: statePath,
          // This case drives the CLI transport through a stubbed `aws` on PATH.
          // #662 made the SDK the default, so it must be requested explicitly —
          // which also keeps the documented rollback transport under test.
          RELEASE_RETENTION_TRANSPORT: 'cli',
        },
      },
    );

    assert.equal(result.status, 3, result.stderr);
    assert.equal(JSON.parse(result.stdout).drift, true);
    assert.match(
      result.stderr,
      /retry operation=get-object-tagging key=releases\/active\/a\.xml attempt=1\/5/,
    );
    assert.match(
      result.stderr,
      /summary operation=audit outcome=success total=1 protected=1 eligible=0 drift=1 .*retries=1/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

// #662 — release-retention.mjs spawns one `aws` CLI process per object, which
// is process-spawn bound: measured 1.15 obj/s at --concurrency 24
// (build-data-artifacts job 17864) and 1.19 obj/s at --concurrency 8
// (retrieval-health-check job 16150) on the same runner class. Three times the
// concurrency, identical throughput. Moving the S3 calls onto the AWS SDK
// removes the spawn entirely, so this asserts the SDK is actually resolvable
// from these scripts in every environment they run in — the CI image, and a
// workstation. A missing dependency must fail here, loudly, rather than at
// 03:00 inside a retention reconcile.
test('the AWS SDK S3 client is resolvable from the retention scripts', async () => {
  const module = await import('@aws-sdk/client-s3');
  assert.equal(typeof module.S3Client, 'function');
});

// --- #662 SDK transport -----------------------------------------------------
// These cover the three things that would degrade SILENTLY rather than fail
// when the transport changed: the LastModified type, retry classification, and
// the error-message shape runbooks grep for.

function fakeSdk() {
  const make = (type) =>
    class {
      constructor(input) {
        this.type = type;
        this.input = input;
      }
    };
  return {
    S3Client: class {
      constructor(config) {
        this.config = config;
      }
    },
    ListObjectsV2Command: make('list'),
    GetObjectTaggingCommand: make('get'),
    PutObjectTaggingCommand: make('put'),
  };
}

function sdkTransport(handler, options = {}) {
  const sent = [];
  const client = {
    async send(command) {
      sent.push(command);
      return handler(command, sent.length);
    },
  };
  const runtime = { retries: 0, stderr: () => {}, nowMs: () => 0 };
  const aws = new AwsS3Sdk(
    { region: 'eu-central-1', profile: '', ...options },
    runtime,
    fakeSdk(),
    client,
  );
  return { aws, sent, runtime };
}

test('isoSecondsUtc renders a Date exactly as the aws CLI renders S3 timestamps', () => {
  // The CLI emits 2026-07-28T16:46:33+00:00 — whole seconds, numeric offset.
  assert.equal(
    isoSecondsUtc(new Date('2026-07-28T16:46:33.000Z')),
    '2026-07-28T16:46:33+00:00',
  );
  // Already-a-string (the CLI transport) passes through untouched.
  assert.equal(
    isoSecondsUtc('2026-07-28T16:46:33+00:00'),
    '2026-07-28T16:46:33+00:00',
  );
});

test('SDK listObjects normalises LastModified so classifyObject does not produce NaN ages', async () => {
  const { aws } = sdkTransport(() => ({
    Contents: [
      { Key: 'releases/a', LastModified: new Date('2026-04-01T00:00:00.000Z') },
    ],
    IsTruncated: false,
  }));
  const [object] = await aws.listObjects('bucket', 'releases/');
  assert.equal(typeof object.LastModified, 'string');
  const classification = classifyObject(
    object,
    [],
    [],
    new Date('2026-04-11T00:00:00Z'),
  );
  assert.equal(classification.age_days, 10);
  assert.equal(classification.last_modified, '2026-04-01T00:00:00+00:00');
});

test('SDK listObjects follows continuation tokens', async () => {
  const { aws, sent } = sdkTransport((command, callNumber) =>
    callNumber === 1
      ? {
          Contents: [{ Key: 'a', LastModified: new Date(0) }],
          IsTruncated: true,
          NextContinuationToken: 'T',
        }
      : {
          Contents: [{ Key: 'b', LastModified: new Date(0) }],
          IsTruncated: false,
        },
  );
  const objects = await aws.listObjects('bucket', 'releases/');
  assert.deepEqual(
    objects.map((object) => object.Key),
    ['a', 'b'],
  );
  assert.equal(sent[0].input.ContinuationToken, undefined);
  assert.equal(sent[1].input.ContinuationToken, 'T');
});

test('SDK getTags and putTags preserve the TagSet shape AwsCli returns', async () => {
  const { aws, sent } = sdkTransport((command) =>
    command.type === 'get'
      ? { TagSet: [{ Key: RETENTION_TAG_KEY, Value: PINNED }] }
      : {},
  );
  assert.deepEqual(await aws.getTags('bucket', 'key'), [
    { Key: RETENTION_TAG_KEY, Value: PINNED },
  ]);
  await aws.putTags('bucket', 'key', [
    { Key: RETENTION_TAG_KEY, Value: UNPINNED },
  ]);
  assert.deepEqual(sent[1].input.Tagging, {
    TagSet: [{ Key: RETENTION_TAG_KEY, Value: UNPINNED }],
  });
});

test('an SDK object with no tags reads as an empty TagSet, not undefined', async () => {
  const { aws } = sdkTransport(() => ({}));
  assert.deepEqual(await aws.getTags('bucket', 'key'), []);
});

test('a 5xx carried only in $metadata is still classified retryable', () => {
  // SDK errors have no stderr; without $metadata in errorText a 503 would
  // silently stop being retried when the transport changed.
  const error = Object.assign(new Error('We encountered an internal error'), {
    name: 'InternalError',
    $metadata: { httpStatusCode: 503 },
  });
  assert.equal(isRetryableAwsError(error), true);
  const notFound = Object.assign(
    new Error('The specified key does not exist'),
    {
      name: 'NoSuchKey',
      $metadata: { httpStatusCode: 404 },
    },
  );
  assert.equal(isRetryableAwsError(notFound), false);
});

test('SDK transport retries a throttle and reports it like the CLI transport does', async () => {
  const { aws, runtime } = sdkTransport((command, callNumber) => {
    if (callNumber === 1) {
      return Promise.reject(
        Object.assign(new Error('Please reduce your request rate'), {
          name: 'SlowDown',
          $metadata: { httpStatusCode: 503 },
        }),
      );
    }
    return { TagSet: [] };
  });
  assert.deepEqual(await aws.getTags('bucket', 'releases/a'), []);
  assert.equal(runtime.retries, 1);
});

test('SDK failures keep the AwsCli error message shape that runbooks grep for', async () => {
  const { aws } = sdkTransport(() =>
    Promise.reject(
      Object.assign(new Error('Access Denied'), {
        name: 'AccessDenied',
        $metadata: { httpStatusCode: 403 },
      }),
    ),
  );
  await assert.rejects(
    () => aws.getTags('my-bucket', 'releases/a'),
    /get-object-tagging failed for bucket my-bucket key releases\/a after 1 attempt: AccessDenied/,
  );
});

test('a missing @aws-sdk/client-s3 fails with an actionable message, not a bare import error', async () => {
  // The dependency lives in .gitlab/ci/scripts/package.json, which every job
  // running this module installs. If someone adds a caller and forgets the
  // install, the failure must name the fix rather than surfacing
  // ERR_MODULE_NOT_FOUND from inside a 03:00 retention reconcile.
  const source = readFileSync(SCRIPT, 'utf8');
  assert.match(source, /requires @aws-sdk\/client-s3/);
  assert.match(source, /npm ci --prefix \.gitlab\/ci\/scripts/);
  assert.match(source, /RELEASE_RETENTION_TRANSPORT=cli/);
});
