#!/usr/bin/env node

import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

export const RETENTION_TAG_KEY = 'renate:retention';
export const PINNED = 'pinned';
export const UNPINNED = 'unpinned';
export const RETENTION_DAYS = 90;
export const DEFAULT_CONCURRENCY = 8;
export const MAX_CONCURRENCY = 64;
export const MAX_ATTEMPTS = 5;
export const RETRY_BASE_DELAY_MS = 250;
export const RETRY_MAX_DELAY_MS = 5_000;

function usage(message) {
  if (message) process.stderr.write(`ERROR: ${message}\n\n`);
  process.stderr.write(`Usage:
  release-retention.mjs pin|unpin --bucket BUCKET --prefix PREFIX [--prefix PREFIX] [--dry-run] [--concurrency N]
  release-retention.mjs reconcile --bucket BUCKET --managed-prefix PREFIX --protected-prefix PREFIX [--protected-prefix PREFIX] [--dry-run] [--concurrency N]
  release-retention.mjs audit --bucket BUCKET --managed-prefix PREFIX [--protected-prefix PREFIX] [--now ISO-8601] [--fail-on-drift] [--concurrency N]

All commands accept --region REGION, --profile PROFILE, and --concurrency N
(default 8, range 1-64). Reconcile validates all protected prefixes, pins and
verifies protected objects first, and only then unpins the remaining objects
under the managed prefix.

S3 calls go through the AWS SDK (#662). Set RELEASE_RETENTION_TRANSPORT=cli to
fall back to the per-object \`aws\` CLI transport, which is roughly 20x slower
because it spawns a process per object.
`);
  process.exit(message ? 2 : 0);
}

export function mergeRetentionTag(tagSet, state) {
  if (![PINNED, UNPINNED].includes(state)) {
    throw new Error(`invalid retention state: ${state}`);
  }
  const unrelated = tagSet.filter((tag) => tag.Key !== RETENTION_TAG_KEY);
  return [...unrelated, { Key: RETENTION_TAG_KEY, Value: state }];
}

export function retentionState(tagSet) {
  return tagSet.find((tag) => tag.Key === RETENTION_TAG_KEY)?.Value ?? null;
}

export function classifyObject(
  object,
  tagSet,
  protectedPrefixes,
  now = new Date(),
) {
  const state = retentionState(tagSet);
  const protectedObject = protectedPrefixes.some((prefix) =>
    object.Key.startsWith(prefix),
  );
  const ageMs = now.getTime() - new Date(object.LastModified).getTime();
  const ageDays = Math.floor(ageMs / 86_400_000);
  const desiredState = protectedObject ? PINNED : UNPINNED;
  return {
    key: object.Key,
    last_modified: object.LastModified,
    age_days: ageDays,
    retention: state ?? 'missing',
    protected: protectedObject,
    eligible:
      !protectedObject && state === UNPINNED && ageDays >= RETENTION_DAYS,
    drift: state !== desiredState,
  };
}

export function desiredRetentionState(key, protectedPrefixes) {
  return protectedPrefixes.some((prefix) => key.startsWith(prefix))
    ? PINNED
    : UNPINNED;
}

export function reconciliationPhases(objects, protectedPrefixes) {
  return {
    pin: objects.filter(
      (object) =>
        desiredRetentionState(object.Key, protectedPrefixes) === PINNED,
    ),
    unpin: objects.filter(
      (object) =>
        desiredRetentionState(object.Key, protectedPrefixes) === UNPINNED,
    ),
  };
}

function parseOptions(argv) {
  const options = {
    bucket: '',
    region:
      process.env.AWS_DEFAULT_REGION ||
      process.env.AWS_REGION ||
      'eu-central-1',
    profile: '',
    prefixes: [],
    managedPrefixes: [],
    protectedPrefixes: [],
    concurrency: DEFAULT_CONCURRENCY,
    dryRun: false,
    failOnDrift: false,
    now: new Date(),
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const value = () => {
      index += 1;
      if (index >= argv.length) usage(`${arg} requires a value`);
      return argv[index];
    };
    switch (arg) {
      case '--bucket':
        options.bucket = value();
        break;
      case '--region':
        options.region = value();
        break;
      case '--profile':
        options.profile = value();
        break;
      case '--prefix':
        options.prefixes.push(value());
        break;
      case '--managed-prefix':
        options.managedPrefixes.push(value());
        break;
      case '--protected-prefix':
        options.protectedPrefixes.push(value());
        break;
      case '--concurrency': {
        const concurrency = value();
        if (!/^[0-9]+$/.test(concurrency)) {
          usage('--concurrency must be an integer from 1 to 64');
        }
        options.concurrency = Number(concurrency);
        if (options.concurrency < 1 || options.concurrency > MAX_CONCURRENCY) {
          usage('--concurrency must be an integer from 1 to 64');
        }
        break;
      }
      case '--now':
        options.now = new Date(value());
        if (Number.isNaN(options.now.getTime()))
          usage('--now must be an ISO-8601 timestamp');
        break;
      case '--dry-run':
        options.dryRun = true;
        break;
      case '--fail-on-drift':
        options.failOnDrift = true;
        break;
      case '--help':
      case '-h':
        usage();
        break;
      default:
        usage(`unknown argument: ${arg}`);
    }
  }
  if (!options.bucket) usage('--bucket is required');
  for (const prefix of [
    ...options.prefixes,
    ...options.managedPrefixes,
    ...options.protectedPrefixes,
  ]) {
    if (!prefix || prefix.startsWith('/') || prefix.includes('..')) {
      usage(`unsafe S3 prefix: ${prefix || '<empty>'}`);
    }
  }
  return options;
}

function errorText(error) {
  return [
    error?.code,
    error?.name,
    error?.message,
    error?.stderr,
    // #662: SDK errors carry no stderr — the retryable signal is the HTTP
    // status (\b5\d\d\b below) and the error name. Without this a 503 from S3
    // would silently stop being retryable when the transport changed.
    error?.$metadata?.httpStatusCode,
  ]
    .filter(Boolean)
    .join(' ');
}

function oneLineError(error) {
  return errorText(error).replace(/\s+/g, ' ').trim();
}

export function isRetryableAwsError(error) {
  return /(?:SlowDown|Throttl|TooManyRequests|RequestLimitExceeded|InternalError|InternalFailure|ServiceUnavailable|RequestTimeout|PriorRequestNotComplete|ECONNRESET|ECONNREFUSED|EPIPE|ETIMEDOUT|EAI_AGAIN|ENETUNREACH|temporary failure in name resolution|could not connect to the endpoint URL|connection (?:was )?(?:closed|reset)|read timeout|timed? out|HTTP[^\n]*\b5\d\d\b|status code[^\n]*\b5\d\d\b|\b5\d\d\b)/i.test(
    errorText(error),
  );
}

export async function retryOperation(operation, options = {}) {
  const maxAttempts = options.maxAttempts ?? MAX_ATTEMPTS;
  const baseDelayMs = options.baseDelayMs ?? RETRY_BASE_DELAY_MS;
  const maxDelayMs = options.maxDelayMs ?? RETRY_MAX_DELAY_MS;
  const sleep =
    options.sleep ??
    ((delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)));
  const random = options.random ?? Math.random;
  const isRetryable = options.isRetryable ?? isRetryableAwsError;
  const onRetry = options.onRetry ?? (() => {});

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await operation(attempt);
    } catch (error) {
      if (attempt === maxAttempts || !isRetryable(error)) {
        error.attempts = attempt;
        throw error;
      }
      const ceiling = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      const delayMs = Math.floor(random() * ceiling);
      onRetry({ attempt, delayMs, error, maxAttempts });
      await sleep(delayMs);
    }
  }
  throw new Error('retry operation exhausted unexpectedly');
}

export async function mapBounded(items, concurrency, worker, onComplete) {
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error('concurrency must be a positive integer');
  }
  const results = new Array(items.length);
  let nextIndex = 0;
  let firstError = null;

  async function runWorker() {
    while (!firstError) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) return;
      try {
        results[index] = await worker(items[index], index);
        onComplete?.(results[index], index);
      } catch (error) {
        firstError ??= error;
      }
    }
  }

  const workerCount = Math.min(concurrency, items.length);
  await Promise.all(Array.from({ length: workerCount }, () => runWorker()));
  if (firstError) throw firstError;
  return results;
}

function defaultRuntime(overrides = {}) {
  overrides.stdout ??= (value) => process.stdout.write(value);
  overrides.stderr ??= (value) => process.stderr.write(value);
  overrides.nowMs ??= () => Date.now();
  overrides.retries ??= 0;
  overrides.metrics ??= {
    objects_listed: 0,
    objects_scanned: 0,
    retention_tag_reads: 0,
    retention_tag_writes: 0,
    verification_reads: 0,
    s3_error_codes: [],
  };
  return overrides;
}

function writeRecord(runtime, kind, fields) {
  const values = Object.entries(fields).map(
    ([key, value]) => `${key}=${value}`,
  );
  runtime.stderr(`${kind} ${values.join(' ')}\n`);
}

function progressReporter(runtime, operation, total) {
  const startedAt = runtime.nowMs();
  let completed = 0;
  if (total === 0) {
    writeRecord(runtime, 'progress', {
      operation,
      completed: 0,
      total: 0,
      elapsed_ms: 0,
    });
  }
  return () => {
    completed += 1;
    if (completed % 100 === 0 || completed === total) {
      writeRecord(runtime, 'progress', {
        operation,
        completed,
        total,
        elapsed_ms: Math.max(0, runtime.nowMs() - startedAt),
      });
    }
  };
}

async function mapWithProgress(runtime, operation, items, concurrency, worker) {
  const progress = progressReporter(runtime, operation, items.length);
  return mapBounded(items, concurrency, worker, progress);
}

class AwsCli {
  constructor(options, runtime, runExecFile = execFileAsync) {
    this.region = options.region;
    this.profile = options.profile;
    this.runtime = runtime;
    this.runExecFile = runExecFile;
  }

  async run(args, json = true, context = {}) {
    const globalArgs = ['--region', this.region, '--no-cli-pager'];
    if (this.profile) globalArgs.push('--profile', this.profile);
    let result;
    try {
      result = await retryOperation(
        () =>
          this.runExecFile('aws', [...args, ...globalArgs], {
            encoding: 'utf8',
            maxBuffer: 64 * 1024 * 1024,
            // Keep one retry budget here instead of multiplying these five
            // attempts by the AWS CLI's own retry loop.
            env: {
              ...process.env,
              AWS_RETRY_MODE: 'standard',
              AWS_MAX_ATTEMPTS: '1',
            },
          }),
        {
          onRetry: ({ attempt, delayMs, error, maxAttempts }) => {
            this.runtime.retries += 1;
            writeRecord(this.runtime, 'retry', {
              operation: context.operation ?? `${args[0]}/${args[1]}`,
              key: context.key ?? '-',
              attempt: `${attempt}/${maxAttempts}`,
              delay_ms: delayMs,
              error: JSON.stringify(oneLineError(error)),
            });
          },
        },
      );
    } catch (error) {
      const operation =
        context.operation ?? `aws ${args.slice(0, 2).join(' ')}`;
      const target = context.key ? ` key ${context.key}` : '';
      const attempts = error.attempts ?? 1;
      throw new Error(
        `${operation} failed for bucket ${context.bucket ?? '<unknown>'}${target} after ${attempts} ${attempts === 1 ? 'attempt' : 'attempts'}${oneLineError(error) ? `: ${oneLineError(error)}` : ''}`,
        { cause: error },
      );
    }
    const output = result.stdout ?? '';
    if (!json) return output;
    return output.trim() ? JSON.parse(output) : {};
  }

  async listObjects(bucket, prefix) {
    const objects = [];
    let continuationToken = '';
    do {
      const args = [
        's3api',
        'list-objects-v2',
        '--bucket',
        bucket,
        '--prefix',
        prefix,
        '--output',
        'json',
      ];
      if (continuationToken)
        args.push('--continuation-token', continuationToken);
      const page = await this.run(args, true, {
        operation: 'list-objects',
        bucket,
        key: prefix,
      });
      objects.push(...(page.Contents ?? []));
      continuationToken = page.IsTruncated ? page.NextContinuationToken : '';
    } while (continuationToken);
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.objects_listed += objects.length;
    return objects;
  }

  async getTags(bucket, key) {
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.retention_tag_reads += 1;
    try {
      return (
        (
          await this.run(
            [
              's3api',
              'get-object-tagging',
              '--bucket',
              bucket,
              '--key',
              key,
              '--output',
              'json',
            ],
            true,
            { operation: 'get-object-tagging', bucket, key },
          )
        ).TagSet ?? []
      );
    } catch (error) {
      const code = error?.code ?? error?.$metadata?.httpStatusCode ?? 'Unknown';
      if (!this.runtime.metrics.s3_error_codes.includes(code)) {
        this.runtime.metrics.s3_error_codes.push(code);
      }
      throw error;
    }
  }

  async putTags(bucket, key, tagSet) {
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.retention_tag_writes += 1;
    try {
      await this.run(
        [
          's3api',
          'put-object-tagging',
          '--bucket',
          bucket,
          '--key',
          key,
          '--tagging',
          JSON.stringify({ TagSet: tagSet }),
        ],
        false,
        { operation: 'put-object-tagging', bucket, key },
      );
    } catch (error) {
      const code = error?.code ?? error?.$metadata?.httpStatusCode ?? 'Unknown';
      if (!this.runtime.metrics.s3_error_codes.includes(code)) {
        this.runtime.metrics.s3_error_codes.push(code);
      }
      throw error;
    }
  }
}

// #662 — the same three S3 operations AwsCli provides, over the AWS SDK.
//
// AwsCli spawns one `aws` process per object, which is process-spawn bound, not
// S3 bound: 1.15 objects/s at --concurrency 24 (build-data-artifacts job 17864)
// and 1.19 objects/s at --concurrency 8 (retrieval-health-check job 16150) on
// the same runner class — three times the concurrency for identical throughput.
// That put a 430-object reconcile at 368 s and a full 46857-object one out of
// reach of any job timeout. One client with connection reuse removes the spawn.
//
// AwsCli is deliberately left byte-for-byte unchanged and still reachable via
// RELEASE_RETENTION_TRANSPORT=cli, so a transport problem on this
// deletion-adjacent path is a one-variable rollback rather than a revert.
export class AwsS3Sdk {
  // `sdk` and `client` are injectable so tests exercise this class without
  // network or credentials, the same way AwsCli takes runExecFile.
  constructor(options, runtime, sdk = null, client = null) {
    this.options = options;
    this.runtime = runtime;
    this.sdk = sdk;
    this.client = client;
  }

  async load() {
    if (!this.sdk) {
      try {
        this.sdk = await import('@aws-sdk/client-s3');
      } catch (error) {
        throw new Error(
          'release-retention.mjs requires @aws-sdk/client-s3. Install it with ' +
            '`npm ci --prefix .gitlab/ci/scripts` (every CI job that runs this ' +
            'module does so in before_script), or set ' +
            'RELEASE_RETENTION_TRANSPORT=cli to fall back to the slow ' +
            'per-object aws CLI transport.',
          { cause: error },
        );
      }
    }
    if (!this.client) {
      // The CLI transport passes --profile explicitly; the SDK's default
      // credential chain reads AWS_PROFILE, so honour the same option here.
      if (this.options.profile) process.env.AWS_PROFILE = this.options.profile;
      this.client = new this.sdk.S3Client({
        region: this.options.region,
        // retryOperation below owns the single retry budget, exactly as the CLI
        // transport pins AWS_MAX_ATTEMPTS=1 so the two do not multiply.
        maxAttempts: 1,
      });
    }
    return this.sdk;
  }

  async send(build, context) {
    const sdk = await this.load();
    let result;
    try {
      result = await retryOperation(() => this.client.send(build(sdk)), {
        onRetry: ({ attempt, delayMs, error, maxAttempts }) => {
          this.runtime.retries += 1;
          writeRecord(this.runtime, 'retry', {
            operation: context.operation,
            key: context.key ?? '-',
            attempt: `${attempt}/${maxAttempts}`,
            delay_ms: delayMs,
            error: JSON.stringify(oneLineError(error)),
          });
        },
      });
    } catch (error) {
      // Same message shape as AwsCli.run, so runbooks and log greps that match
      // on it keep working across transports.
      const target = context.key ? ` key ${context.key}` : '';
      const attempts = error.attempts ?? 1;
      throw new Error(
        `${context.operation} failed for bucket ${context.bucket ?? '<unknown>'}${target} after ${attempts} ${attempts === 1 ? 'attempt' : 'attempts'}${oneLineError(error) ? `: ${oneLineError(error)}` : ''}`,
        { cause: error },
      );
    }
    return result;
  }

  async listObjects(bucket, prefix) {
    const objects = [];
    let continuationToken = undefined;
    do {
      const page = await this.send(
        (sdk) =>
          new sdk.ListObjectsV2Command({
            Bucket: bucket,
            Prefix: prefix,
            ContinuationToken: continuationToken,
          }),
        { operation: 'list-objects', bucket, key: prefix },
      );
      for (const object of page.Contents ?? []) {
        // classifyObject date-parses LastModified and audit output prints it
        // verbatim. The CLI emits an ISO string; the SDK emits a Date, which
        // would silently reformat every audit line. Normalise to the CLI's
        // exact rendering so the two transports are diffable.
        objects.push({
          ...object,
          LastModified: isoSecondsUtc(object.LastModified),
        });
      }
      continuationToken = page.IsTruncated
        ? page.NextContinuationToken
        : undefined;
    } while (continuationToken);
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.objects_listed += objects.length;
    return objects;
  }

  async getTags(bucket, key) {
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.retention_tag_reads += 1;
    try {
      const result = await this.send(
        (sdk) => new sdk.GetObjectTaggingCommand({ Bucket: bucket, Key: key }),
        { operation: 'get-object-tagging', bucket, key },
      );
      return result.TagSet ?? [];
    } catch (error) {
      const code = error?.$metadata?.httpStatusCode ?? error?.code ?? 'Unknown';
      if (!this.runtime.metrics.s3_error_codes.includes(code)) {
        this.runtime.metrics.s3_error_codes.push(code);
      }
      throw error;
    }
  }

  async putTags(bucket, key, tagSet) {
    this.runtime.metrics ??= { objects_listed: 0, objects_scanned: 0, retention_tag_reads: 0, retention_tag_writes: 0, verification_reads: 0, s3_error_codes: [] };
    this.runtime.metrics.retention_tag_writes += 1;
    try {
      await this.send(
        (sdk) =>
          new sdk.PutObjectTaggingCommand({
            Bucket: bucket,
            Key: key,
            Tagging: { TagSet: tagSet },
          }),
        { operation: 'put-object-tagging', bucket, key },
      );
    } catch (error) {
      const code = error?.$metadata?.httpStatusCode ?? error?.code ?? 'Unknown';
      if (!this.runtime.metrics.s3_error_codes.includes(code)) {
        this.runtime.metrics.s3_error_codes.push(code);
      }
      throw error;
    }
  }
}

// The AWS CLI renders S3 timestamps as `2026-07-28T16:46:33+00:00` — UTC, whole
// seconds, numeric offset rather than `Z`. Date#toISOString gives
// `2026-07-28T16:46:33.000Z`, so strip the milliseconds and swap the suffix.
export function isoSecondsUtc(value) {
  if (!(value instanceof Date)) return value;
  return value.toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

async function uniqueObjects(aws, bucket, prefixes) {
  const byKey = new Map();
  for (const prefix of prefixes) {
    for (const object of await aws.listObjects(bucket, prefix))
      byKey.set(object.Key, object);
  }
  return [...byKey.values()].sort((left, right) =>
    left.Key.localeCompare(right.Key),
  );
}

function requireObjects(objects, prefixes, label) {
  if (objects.length === 0) throw new Error(`${label} contains no objects`);
  for (const prefix of prefixes) {
    if (!objects.some((object) => object.Key.startsWith(prefix))) {
      throw new Error(`${label} ${prefix} contains no objects`);
    }
  }
}

function withObjectContext(operation, options, object, error) {
  const message = error?.message ?? String(error);
  if (message.includes(object.Key)) return error;
  return new Error(
    `${operation} failed for s3://${options.bucket}/${object.Key}: ${message}`,
    { cause: error },
  );
}

export async function applyState(
  aws,
  options,
  objects,
  state,
  runtimeOverrides = {},
) {
  const runtime = defaultRuntime(runtimeOverrides);
  const operation = state === PINNED ? 'pin' : 'unpin';
  const current = await mapWithProgress(
    runtime,
    `${operation}/read`,
    objects,
    options.concurrency,
    async (object) => {
      try {
        runtime.metrics.objects_scanned += 1;
        return await aws.getTags(options.bucket, object.Key);
      } catch (error) {
        throw withObjectContext('get-object-tagging', options, object, error);
      }
    },
  );
  const changed = objects
    .map((object, index) => ({ object, tagSet: current[index] }))
    .filter(({ tagSet }) => retentionState(tagSet) !== state);

  if (options.dryRun) {
    for (const { object } of changed) {
      runtime.stdout(`would-tag\t${state}\t${object.Key}\n`);
    }
    return {
      total: objects.length,
      changed: changed.length,
      unchanged: objects.length - changed.length,
      verified: 0,
    };
  }

  await mapWithProgress(
    runtime,
    `${operation}/write`,
    changed,
    options.concurrency,
    async ({ object, tagSet }) => {
      try {
        await aws.putTags(
          options.bucket,
          object.Key,
          mergeRetentionTag(tagSet, state),
        );
      } catch (error) {
        throw withObjectContext('put-object-tagging', options, object, error);
      }
    },
  );

  // Objects already carrying the requested state were verified by the first
  // read. Only changed objects need an independent post-write read-back. This
  // keeps retries and idempotent promotion steps from paying for a redundant
  // second read across an entire immutable corpus.
  let verifiedCount = 0;
  await mapWithProgress(
    runtime,
    `${operation}/verify`,
    changed,
    options.concurrency,
    async ({ object }) => {
      let tagSet;
      try {
        runtime.metrics.verification_reads += 1;
        tagSet = await aws.getTags(options.bucket, object.Key);
      } catch (error) {
        throw withObjectContext(
          'verify-object-tagging',
          options,
          object,
          error,
        );
      }
      const actual = retentionState(tagSet);
      if (actual !== state) {
        throw new Error(
          `verify-object-tagging failed for s3://${options.bucket}/${object.Key}: expected ${state}, found ${actual ?? 'missing'}`,
        );
      }
      verifiedCount += 1;
    },
  );

  for (const { object } of changed) {
    runtime.stdout(`tag\t${state}\t${object.Key}\n`);
  }
  return {
    total: objects.length,
    changed: changed.length,
    unchanged: objects.length - changed.length,
    verified: (objects.length - changed.length) + verifiedCount,
  };
}

async function pinOrUnpin(command, aws, options, runtime) {
  if (options.prefixes.length === 0)
    usage(`${command} requires at least one --prefix`);
  const objects = await uniqueObjects(aws, options.bucket, options.prefixes);
  requireObjects(objects, options.prefixes, 'release prefix');
  return applyState(
    aws,
    options,
    objects,
    command === 'pin' ? PINNED : UNPINNED,
    runtime,
  );
}

export async function reconcileObjects(
  aws,
  options,
  objects,
  runtimeOverrides = {},
) {
  const runtime = defaultRuntime(runtimeOverrides);
  const phases = reconciliationPhases(objects, options.protectedPrefixes);

  // The protected phase observes every object and independently reads back
  // every write. A failed write or verification can therefore never be
  // followed by an unpin request.
  const pin = await applyState(aws, options, phases.pin, PINNED, runtime);
  const unpin = await applyState(aws, options, phases.unpin, UNPINNED, runtime);
  return { pin, unpin };
}

async function reconcile(aws, options, runtime) {
  if (options.managedPrefixes.length === 0)
    usage('reconcile requires --managed-prefix');
  if (options.protectedPrefixes.length === 0)
    usage('reconcile requires --protected-prefix');
  for (const prefix of options.protectedPrefixes) {
    if (
      !options.managedPrefixes.some((managed) => prefix.startsWith(managed))
    ) {
      throw new Error(
        `protected prefix ${prefix} is outside the managed prefixes`,
      );
    }
  }
  const objects = await uniqueObjects(
    aws,
    options.bucket,
    options.managedPrefixes,
  );
  requireObjects(objects, options.managedPrefixes, 'managed prefix');
  requireObjects(objects, options.protectedPrefixes, 'protected prefix');
  return reconcileObjects(aws, options, objects, runtime);
}

export async function auditObjects(
  aws,
  options,
  objects,
  runtimeOverrides = {},
) {
  const runtime = defaultRuntime(runtimeOverrides);
  const tagSets = await mapWithProgress(
    runtime,
    'audit/read',
    objects,
    options.concurrency,
    async (object) => {
      try {
        runtime.metrics.objects_scanned += 1;
        return await aws.getTags(options.bucket, object.Key);
      } catch (error) {
        throw withObjectContext('get-object-tagging', options, object, error);
      }
    },
  );
  const classifications = objects.map((object, index) =>
    classifyObject(
      object,
      tagSets[index],
      options.protectedPrefixes,
      options.now,
    ),
  );
  for (const classification of classifications) {
    runtime.stdout(`${JSON.stringify(classification)}\n`);
  }
  const driftCount = classifications.filter((item) => item.drift).length;
  return {
    classifications,
    total: classifications.length,
    protected: classifications.filter((item) => item.protected).length,
    eligible: classifications.filter((item) => item.eligible).length,
    drift: driftCount,
  };
}

async function audit(aws, options, runtime) {
  if (options.managedPrefixes.length === 0)
    usage('audit requires --managed-prefix');
  const objects = await uniqueObjects(
    aws,
    options.bucket,
    options.managedPrefixes,
  );
  requireObjects(objects, options.managedPrefixes, 'managed prefix');
  if (options.protectedPrefixes.length > 0) {
    requireObjects(objects, options.protectedPrefixes, 'protected prefix');
  }
  return auditObjects(aws, options, objects, runtime);
}

function successSummary(command, result, runtime) {
  const baseSummary = {};
  if (command === 'pin' || command === 'unpin') {
    baseSummary.total = result.total;
    baseSummary.changed = result.changed;
    baseSummary.unchanged = result.unchanged;
    baseSummary.verified = result.verified;
  } else if (command === 'reconcile') {
    baseSummary.total = result.pin.total + result.unpin.total;
    baseSummary.pinned = result.pin.total;
    baseSummary.pin_changed = result.pin.changed;
    baseSummary.unpinned = result.unpin.total;
    baseSummary.unpin_changed = result.unpin.changed;
    baseSummary.verified = result.pin.verified + result.unpin.verified;
  } else {
    baseSummary.total = result.total;
    baseSummary.protected = result.protected;
    baseSummary.eligible = result.eligible;
    baseSummary.drift = result.drift;
  }
  return {
    ...baseSummary,
    objects_listed: runtime.metrics.objects_listed,
    objects_scanned: runtime.metrics.objects_scanned,
    retention_tag_reads: runtime.metrics.retention_tag_reads,
    retention_tag_writes: runtime.metrics.retention_tag_writes,
    verification_reads: runtime.metrics.verification_reads,
    s3_error_codes: runtime.metrics.s3_error_codes.length > 0
      ? runtime.metrics.s3_error_codes.join(',')
      : 'none',
  };
}

export async function executeCommand(
  command,
  aws,
  options,
  runtimeOverrides = {},
) {
  const runtime = defaultRuntime(runtimeOverrides);
  const startedAt = runtime.nowMs();
  try {
    let result;
    if (command === 'pin' || command === 'unpin') {
      result = await pinOrUnpin(command, aws, options, runtime);
    } else if (command === 'reconcile') {
      result = await reconcile(aws, options, runtime);
    } else {
      result = await audit(aws, options, runtime);
    }
    writeRecord(runtime, 'summary', {
      operation: command,
      outcome: 'success',
      ...successSummary(command, result, runtime),
      retries: runtime.retries,
      elapsed_ms: Math.max(0, runtime.nowMs() - startedAt),
    });
    return result;
  } catch (error) {
    writeRecord(runtime, 'summary', {
      operation: command,
      outcome: 'failed',
      ...(() => {
        const metrics = runtime.metrics;
        return {
          objects_listed: metrics.objects_listed,
          objects_scanned: metrics.objects_scanned,
          retention_tag_reads: metrics.retention_tag_reads,
          retention_tag_writes: metrics.retention_tag_writes,
          verification_reads: metrics.verification_reads,
          s3_error_codes: metrics.s3_error_codes.length > 0
            ? metrics.s3_error_codes.join(',')
            : 'none',
        };
      })(),
      retries: runtime.retries,
      elapsed_ms: Math.max(0, runtime.nowMs() - startedAt),
    });
    throw error;
  }
}

export function commandExitCode(command, options, result) {
  return command === 'audit' && options.failOnDrift && result.drift > 0 ? 3 : 0;
}

async function main() {
  const [command, ...argv] = process.argv.slice(2);
  if (!command || ['--help', '-h'].includes(command)) usage();
  if (!['pin', 'unpin', 'reconcile', 'audit'].includes(command))
    usage(`unknown command: ${command}`);
  const options = parseOptions(argv);
  const runtime = defaultRuntime();
  // #662: the SDK transport is the default; `cli` is the documented rollback.
  const aws =
    (process.env.RELEASE_RETENTION_TRANSPORT ?? '').toLowerCase() === 'cli'
      ? new AwsCli(options, runtime)
      : new AwsS3Sdk(options, runtime);
  const result = await executeCommand(command, aws, options, runtime);
  process.exitCode = commandExitCode(command, options, result);
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`ERROR: ${error.message}\n`);
    process.exitCode = 1;
  });
}
