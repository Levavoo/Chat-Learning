#!/usr/bin/env node
// Dependency-free #492 identity, validation, and inventory helper for CI.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const SHA_ID = /^sha256-[0-9a-f]{64}$/;
const SHA_DIGEST = /^sha256:[0-9a-f]{64}$/;
const APP_VERSION = /^v?\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$/;
const PROMOTED_VERSION = /^v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$/;
const BUCKET = /^(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const COORDINATE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
const V2_FIELDS = new Set([
  'schema_version',
  'release_id',
  'version',
  'data_artifact_version',
  'etl_version',
  'knowledge_base_id',
  'data_source_id',
  'raw_bucket',
  'raw_prefix',
  'processed_bucket',
  'processed_prefix',
  'bm25_bucket',
  'bm25_key',
  'bm25_tokenizer_revision',
  'etl_image_digest',
]);
const V3_FIELDS = new Set([
  ...V2_FIELDS,
  'retrieval_artifact_id',
  'retrieval_artifact_fingerprint',
  'chatbot_image_digest',
]);

function digest(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

export function deriveReleaseId(version, data, etl) {
  return `sha256-${digest(`version=${version}\ndata_artifact_version=${data}\netl_version=${etl}\n`)}`;
}

function artifactDigest(data, etl, tokenizer) {
  return digest(
    `data_artifact_version=${data}\netl_version=${etl}\n` +
      `bm25_tokenizer_revision=${tokenizer}\n`,
  );
}

export function deriveArtifactId(data, etl, tokenizer) {
  return `sha256-${artifactDigest(data, etl, tokenizer)}`;
}

export function deriveArtifactFingerprint(data, etl, tokenizer) {
  return `sha256:${artifactDigest(data, etl, tokenizer)}`;
}

function fail(message) {
  throw new Error(message);
}

export function validateManifest(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    fail('retrieval manifest must be a JSON object');
  }
  if (
    ![2, 3].includes(payload.schema_version) ||
    !Number.isInteger(payload.schema_version)
  ) {
    fail(
      `unsupported retrieval manifest schema_version: ${JSON.stringify(payload.schema_version)}`,
    );
  }
  const expected = payload.schema_version === 3 ? V3_FIELDS : V2_FIELDS;
  const actual = new Set(Object.keys(payload));
  const missing = [...expected].filter((field) => !actual.has(field));
  const unknown = [...actual].filter((field) => !expected.has(field));
  if (missing.length)
    fail(`retrieval manifest is missing fields: ${missing.sort().join(', ')}`);
  if (unknown.length)
    fail(`retrieval manifest has unknown fields: ${unknown.sort().join(', ')}`);
  for (const field of expected) {
    if (
      field !== 'schema_version' &&
      (typeof payload[field] !== 'string' || payload[field].length === 0)
    ) {
      fail(`retrieval manifest field ${field} must be a non-empty string`);
    }
  }
  if (!APP_VERSION.test(payload.version))
    fail('version must be a semantic version');
  for (const field of ['data_artifact_version', 'etl_version']) {
    if (!PROMOTED_VERSION.test(payload[field]))
      fail(`${field} must be an immutable v-prefixed semantic version`);
  }
  if (!SHA_ID.test(payload.release_id)) fail('invalid release_id');
  const release = deriveReleaseId(
    payload.version,
    payload.data_artifact_version,
    payload.etl_version,
  );
  if (payload.release_id !== release)
    fail(`release_id does not match promoted coordinates; expected ${release}`);
  for (const field of [
    'knowledge_base_id',
    'data_source_id',
    'bm25_tokenizer_revision',
  ]) {
    if (!COORDINATE.test(payload[field]))
      fail(`${field} contains unsupported characters`);
  }
  for (const field of ['raw_bucket', 'processed_bucket', 'bm25_bucket']) {
    if (!BUCKET.test(payload[field]))
      fail(`${field} is not a valid S3 bucket name`);
  }
  if (payload.processed_bucket !== payload.bm25_bucket)
    fail('processed_bucket must equal bm25_bucket');
  const rawPrefix = `releases/${payload.data_artifact_version}/`;
  if (payload.raw_prefix !== rawPrefix)
    fail(`raw_prefix must equal ${rawPrefix}`);
  let storageId = payload.release_id;
  if (payload.schema_version === 3) {
    const artifact = deriveArtifactId(
      payload.data_artifact_version,
      payload.etl_version,
      payload.bm25_tokenizer_revision,
    );
    const fingerprint = deriveArtifactFingerprint(
      payload.data_artifact_version,
      payload.etl_version,
      payload.bm25_tokenizer_revision,
    );
    if (payload.retrieval_artifact_id !== artifact)
      fail(`retrieval_artifact_id must equal ${artifact}`);
    if (payload.retrieval_artifact_fingerprint !== fingerprint) {
      fail(`retrieval_artifact_fingerprint must equal ${fingerprint}`);
    }
    if (!SHA_DIGEST.test(payload.chatbot_image_digest))
      fail('invalid chatbot_image_digest');
    storageId = artifact;
  }
  const processedPrefix = `processed/releases/${storageId}/`;
  const bm25Key = `bm25_index/releases/${storageId}/index.json`;
  if (payload.processed_prefix !== processedPrefix)
    fail(`processed_prefix must equal ${processedPrefix}`);
  if (payload.bm25_key !== bm25Key) fail(`bm25_key must equal ${bm25Key}`);
  if (!SHA_DIGEST.test(payload.etl_image_digest))
    fail('invalid etl_image_digest');
  return payload;
}

function walk(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const item = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...walk(item));
    else if (entry.isFile()) files.push(item);
  }
  return files.sort();
}

export function buildInventory(root) {
  const files = walk(root);
  const markdown = files.filter(
    (file) => file.endsWith('.md') && !file.endsWith('.md.metadata.json'),
  );
  const sidecars = files.filter((file) => file.endsWith('.md.metadata.json'));
  if (!markdown.length || markdown.length !== sidecars.length) {
    fail(
      `processed corpus mismatch: markdown=${markdown.length} sidecars=${sidecars.length}`,
    );
  }
  const missing = markdown.filter(
    (file) => !fs.existsSync(`${file}.metadata.json`),
  );
  if (missing.length)
    fail(
      `processed corpus has missing sidecars: ${missing.slice(0, 5).join(', ')}`,
    );
  const objects = files.map((file) => {
    const body = fs.readFileSync(file);
    return {
      key: `docs/${path.relative(root, file).split(path.sep).join('/')}`,
      bytes: body.length,
      sha256: crypto.createHash('sha256').update(body).digest('hex'),
    };
  });
  return {
    schema_version: 2,
    object_count: objects.length,
    markdown_count: markdown.length,
    metadata_count: sidecars.length,
    objects,
  };
}

function usage() {
  process.stderr.write(
    'Usage: retrieval-release.mjs derive-release V DATA ETL | derive-artifact DATA ETL TOKENIZER | validate FILE | inventory ROOT OUTPUT\n',
  );
  process.exit(2);
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  const [command, ...args] = process.argv.slice(2);
  try {
    if (command === 'derive-release' && args.length === 3) {
      process.stdout.write(`${deriveReleaseId(...args)}\n`);
    } else if (command === 'derive-artifact' && args.length === 3) {
      process.stdout.write(
        `${deriveArtifactId(...args)} ${deriveArtifactFingerprint(...args)}\n`,
      );
    } else if (command === 'validate' && args.length === 1) {
      validateManifest(JSON.parse(fs.readFileSync(args[0], 'utf8')));
    } else if (command === 'inventory' && args.length === 2) {
      fs.writeFileSync(args[1], `${JSON.stringify(buildInventory(args[0]))}\n`);
    } else {
      usage();
    }
  } catch (error) {
    process.stderr.write(`retrieval-release: ${error.message}\n`);
    process.exit(1);
  }
}
