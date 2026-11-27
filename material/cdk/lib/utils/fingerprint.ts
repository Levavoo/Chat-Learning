import * as crypto from 'crypto';
import * as fs from 'fs';

import * as cdk from 'aws-cdk-lib';

/** Glob patterns for transient build/cache artifacts that must never affect a content hash. */
const IGNORED_ARTIFACTS = [
  '**/__pycache__',
  '**/__pycache__/**',
  '**/*.pyc',
  '**/*.pyo',
  '**/.pytest_cache',
  '**/.pytest_cache/**',
  '**/.mypy_cache',
  '**/.mypy_cache/**',
  '**/.ruff_cache',
  '**/.ruff_cache/**',
  '**/.DS_Store',
];

/**
 * Content fingerprint of a source directory, stable across checkouts/machines
 * (transient build artifacts are excluded). Use as a custom-resource trigger so
 * it only changes when the actual source content changes — NOT on every deploy.
 *
 * `cdk.FileSystem.fingerprint` has no default excludes and does not read
 * `.gitignore`, so without `IGNORED_ARTIFACTS` a stray `__pycache__/*.pyc` or
 * `.DS_Store` present at synth time would perturb the hash between environments.
 *
 * Combine multiple directories into one hash by passing a prior fingerprint as
 * `extraHash`.
 */
export function fingerprintSources(dir: string, extraHash?: string): string {
  return cdk.FileSystem.fingerprint(dir, {
    exclude: IGNORED_ARTIFACTS,
    ignoreMode: cdk.IgnoreMode.GLOB,
    extraHash,
  });
}

/**
 * Content fingerprint of a fixed list of individual files (not a whole
 * directory) — for loose dependency manifests like `uv.lock`/`pyproject.toml`
 * that live outside the source tree being fingerprinted by
 * {@link fingerprintSources}. `cdk.FileSystem.fingerprint` operates on
 * directories only and has no include-list option, so this hashes file
 * contents directly with Node's `crypto` instead.
 *
 * Combine with a prior fingerprint (e.g. from {@link fingerprintSources}) by
 * passing it as `extraHash` — same chaining convention as that function.
 */
export function fingerprintFiles(
  filePaths: string[],
  extraHash?: string,
): string {
  const hash = crypto.createHash('sha256');
  // Sort for stability — the caller's array order must not affect the hash.
  for (const filePath of [...filePaths].sort()) {
    hash.update(filePath);
    hash.update(fs.readFileSync(filePath));
  }
  if (extraHash) {
    hash.update(extraHash);
  }
  return hash.digest('hex');
}
