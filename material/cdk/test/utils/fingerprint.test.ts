import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import {
  fingerprintSources,
  fingerprintFiles,
} from '../../lib/utils/fingerprint';

describe('fingerprintSources', () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fingerprint-test-'));
    fs.writeFileSync(path.join(dir, 'module.py'), 'x = 1\n');
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test('is stable when only transient build artifacts are added', () => {
    const before = fingerprintSources(dir);

    // These appear on dev machines (after `make backend-test`) and on macOS but
    // not in a fresh CI checkout — they must never perturb the fingerprint.
    fs.mkdirSync(path.join(dir, '__pycache__'));
    fs.writeFileSync(
      path.join(dir, '__pycache__', 'module.cpython-314.pyc'),
      'compiled-bytecode-that-varies-per-checkout',
    );
    fs.writeFileSync(path.join(dir, '.DS_Store'), 'macos-finder-metadata');

    expect(fingerprintSources(dir)).toBe(before);
  });

  test('changes when real source content changes', () => {
    const before = fingerprintSources(dir);

    // CDK caches file content hashes by inode, mtime, and size. Keep this
    // fixture size-changing so fast filesystems cannot reuse the prior hash.
    fs.writeFileSync(path.join(dir, 'module.py'), 'x = 22\n');

    expect(fingerprintSources(dir)).not.toBe(before);
  });

  test('mixes in extraHash so combined directories produce distinct hashes', () => {
    expect(fingerprintSources(dir, 'A')).not.toBe(fingerprintSources(dir, 'B'));
  });
});

describe('fingerprintFiles', () => {
  let dir: string;
  let fileA: string;
  let fileB: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fingerprint-files-test-'));
    fileA = path.join(dir, 'uv.lock');
    fileB = path.join(dir, 'pyproject.toml');
    fs.writeFileSync(fileA, 'lock-content-v1\n');
    fs.writeFileSync(fileB, 'pyproject-content-v1\n');
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test('changes when any listed file changes (#590 review fix — dependency bump must trigger reprocess)', () => {
    const before = fingerprintFiles([fileA, fileB]);

    fs.writeFileSync(fileA, 'lock-content-v2-different-deps\n');

    expect(fingerprintFiles([fileA, fileB])).not.toBe(before);
  });

  test('is independent of the order files are passed in', () => {
    expect(fingerprintFiles([fileA, fileB])).toBe(
      fingerprintFiles([fileB, fileA]),
    );
  });

  test('mixes in extraHash so it can be chained after fingerprintSources', () => {
    const sourceHash = fingerprintSources(dir);
    expect(fingerprintFiles([fileA], sourceHash)).not.toBe(
      fingerprintFiles([fileA]),
    );
  });

  test('chained with fingerprintSources, changes if either the directory or a loose file changes', () => {
    const srcDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fingerprint-src-'));
    fs.writeFileSync(path.join(srcDir, 'handler.py'), 'x = 1\n');

    const combined = () =>
      fingerprintFiles([fileA, fileB], fingerprintSources(srcDir));
    const before = combined();

    // Change only the loose file (simulates a uv.lock dependency bump with no
    // backend/src/etl source change) — the combined hash must still move.
    fs.writeFileSync(fileA, 'lock-content-v3\n');
    expect(combined()).not.toBe(before);

    fs.rmSync(srcDir, { recursive: true, force: true });
  });
});
