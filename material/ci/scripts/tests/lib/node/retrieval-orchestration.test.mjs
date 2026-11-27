import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  armRecovery,
  buildCandidateManifest,
  buildChatbotOnlyManifest,
  buildFullRetrievalManifest,
  confirmRollbackTarget,
  decidePromotionPath,
  resolveSlots,
  selectorTransition,
  serializeManifest,
  tokenizerCoherence,
} from '../../../lib/node/retrieval-orchestration.mjs';
import {
  deriveArtifactFingerprint,
  deriveArtifactId,
  deriveReleaseId,
} from '../../../lib/node/retrieval-release.mjs';

const SCRIPT = fileURLToPath(
  new URL('../../../lib/node/retrieval-orchestration.mjs', import.meta.url),
);

function digestFor(seed) {
  // Deterministic 64-hex-char fixture digest, independent of node:crypto so
  // the test data stays readable; matches SHA_DIGEST's shape requirement.
  return `sha256:${seed.repeat(64).slice(0, 64)}`;
}

function fullManifestInputs(overrides = {}) {
  const data = 'v1.0.0-data.1';
  const etl = 'v1.0.0';
  const tokenizer = 'tok-1';
  const version = '1.0.0';
  const releaseId = deriveReleaseId(version, data, etl);
  const artifactId = deriveArtifactId(data, etl, tokenizer);
  const fingerprint = deriveArtifactFingerprint(data, etl, tokenizer);
  return {
    releaseId,
    retrievalArtifactId: artifactId,
    retrievalArtifactFingerprint: fingerprint,
    chatbotVersion: version,
    dataArtifactVersion: data,
    etlVersion: etl,
    candidateKbId: 'kb-123',
    candidateDataSourceId: 'ds-123',
    rawBucket: 'raw-bucket',
    rawPrefix: `releases/${data}/`,
    candidateBucket: 'processed-bucket',
    processedPrefix: `processed/releases/${artifactId}/`,
    bm25Key: `bm25_index/releases/${artifactId}/index.json`,
    tokenizerRevision: tokenizer,
    etlImageDigest: digestFor('d'),
    chatbotImageDigest: digestFor('c'),
    ...overrides,
  };
}

// --- resolveSlots -----------------------------------------------------------

test('resolveSlots', async (t) => {
  const cases = [
    {
      name: 'active matches blue',
      input: {
        activeKbId: 'kb-blue',
        blueKbId: 'kb-blue',
        greenKbId: 'kb-green',
      },
      expected: { activeSlot: 'blue', inactiveSlot: 'green' },
    },
    {
      name: 'active matches green',
      input: {
        activeKbId: 'kb-green',
        blueKbId: 'kb-blue',
        greenKbId: 'kb-green',
      },
      expected: { activeSlot: 'green', inactiveSlot: 'blue' },
    },
  ];
  for (const { name, input, expected } of cases) {
    await t.test(name, () => {
      assert.deepEqual(resolveSlots(input), expected);
    });
  }

  await t.test('active matches neither slot throws (fail-closed)', () => {
    assert.throws(
      () =>
        resolveSlots({
          activeKbId: 'kb-orphan',
          blueKbId: 'kb-blue',
          greenKbId: 'kb-green',
        }),
      /does not select a provisioned retrieval slot/,
    );
  });
});

// --- decidePromotionPath -----------------------------------------------------

test('decidePromotionPath', async (t) => {
  const active = {
    data_artifact_version: 'v1.0.0-data.1',
    etl_version: 'v1.0.0',
    schema_version: 3,
  };
  const matchingCoords = {
    dataArtifactVersion: 'v1.0.0-data.1',
    etlVersion: 'v1.0.0',
    tokenizerRevision: 'tok-1',
    retrievalArtifactId: 'sha256-same',
  };

  const cases = [
    {
      name: 'all five conditions hold -> chatbot-only',
      active,
      activeTokenizer: 'tok-1',
      activeArtifactId: 'sha256-same',
      coords: matchingCoords,
      expected: 'chatbot-only',
    },
    {
      name: 'data_artifact_version differs -> full-retrieval',
      active: { ...active, data_artifact_version: 'v1.0.0-data.2' },
      activeTokenizer: 'tok-1',
      activeArtifactId: 'sha256-same',
      coords: matchingCoords,
      expected: 'full-retrieval',
    },
    {
      name: 'etl_version differs -> full-retrieval',
      active: { ...active, etl_version: 'v1.0.1' },
      activeTokenizer: 'tok-1',
      activeArtifactId: 'sha256-same',
      coords: matchingCoords,
      expected: 'full-retrieval',
    },
    {
      name: 'tokenizer differs -> full-retrieval',
      active,
      activeTokenizer: 'tok-2',
      activeArtifactId: 'sha256-same',
      coords: matchingCoords,
      expected: 'full-retrieval',
    },
    {
      name: 'schema_version < 3 -> full-retrieval even if coordinates match',
      active: { ...active, schema_version: 2 },
      activeTokenizer: 'tok-1',
      activeArtifactId: 'sha256-same',
      coords: matchingCoords,
      expected: 'full-retrieval',
    },
    {
      name: 'artifact id differs -> full-retrieval',
      active,
      activeTokenizer: 'tok-1',
      activeArtifactId: 'sha256-different',
      coords: matchingCoords,
      expected: 'full-retrieval',
    },
  ];
  for (const {
    name,
    active: activeManifest,
    activeTokenizer,
    activeArtifactId,
    coords,
    expected,
  } of cases) {
    await t.test(name, () => {
      assert.equal(
        decidePromotionPath(
          activeManifest,
          activeTokenizer,
          activeArtifactId,
          coords,
        ),
        expected,
      );
    });
  }
});

// --- armRecovery -------------------------------------------------------------

test('armRecovery', async (t) => {
  await t.test('no previous manifest -> not armed', () => {
    assert.deepEqual(
      armRecovery(null, { candidateKbId: 'kb-1', candidateBucket: 'bucket-1' }),
      { armed: false },
    );
  });

  await t.test('previous manifest targets a different KB -> not armed', () => {
    const previous = {
      knowledge_base_id: 'kb-other',
      processed_bucket: 'bucket-1',
      processed_prefix: 'processed/releases/x/',
      data_source_id: 'ds-other',
    };
    assert.deepEqual(
      armRecovery(previous, {
        candidateKbId: 'kb-1',
        candidateBucket: 'bucket-1',
      }),
      {
        armed: false,
      },
    );
  });

  await t.test(
    'previous manifest targets a different bucket -> not armed',
    () => {
      const previous = {
        knowledge_base_id: 'kb-1',
        processed_bucket: 'bucket-other',
        processed_prefix: 'processed/releases/x/',
        data_source_id: 'ds-1',
      };
      assert.deepEqual(
        armRecovery(previous, {
          candidateKbId: 'kb-1',
          candidateBucket: 'bucket-1',
        }),
        {
          armed: false,
        },
      );
    },
  );

  await t.test(
    'previous manifest matches candidate KB+bucket -> armed with restore coordinates',
    () => {
      const previous = {
        knowledge_base_id: 'kb-1',
        processed_bucket: 'bucket-1',
        processed_prefix: 'processed/releases/x/',
        data_source_id: 'ds-1',
      };
      assert.deepEqual(
        armRecovery(previous, {
          candidateKbId: 'kb-1',
          candidateBucket: 'bucket-1',
        }),
        {
          armed: true,
          bucket: 'bucket-1',
          prefix: 'processed/releases/x/',
          kbId: 'kb-1',
          dataSourceId: 'ds-1',
        },
      );
    },
  );
});

// --- buildCandidateManifest (both shapes) -----------------------------------

test('buildFullRetrievalManifest', async (t) => {
  await t.test('produces a schema-valid manifest with all 18 fields', () => {
    const manifest = buildFullRetrievalManifest(fullManifestInputs());
    assert.equal(manifest.schema_version, 3);
    assert.equal(Object.keys(manifest).length, 18);
  });

  await t.test(
    'round-trips through buildCandidateManifest(full-retrieval) and validates',
    () => {
      const inputs = fullManifestInputs();
      const manifest = buildCandidateManifest('full-retrieval', null, inputs);
      assert.equal(manifest.retrieval_artifact_id, inputs.retrievalArtifactId);
      assert.equal(manifest.chatbot_image_digest, inputs.chatbotImageDigest);
    },
  );
});

test('buildChatbotOnlyManifest', async (t) => {
  const active = buildFullRetrievalManifest(fullManifestInputs());

  await t.test(
    'overrides exactly schema_version, release_id, version, chatbot_image_digest',
    () => {
      const newVersion = '1.0.1';
      const newRelease = deriveReleaseId(
        newVersion,
        active.data_artifact_version,
        active.etl_version,
      );
      const newDigest = digestFor('e');
      const manifest = buildChatbotOnlyManifest(active, {
        releaseId: newRelease,
        chatbotVersion: newVersion,
        chatbotImageDigest: newDigest,
      });
      const changedKeys = Object.keys(manifest).filter(
        (key) => manifest[key] !== active[key],
      );
      assert.deepEqual(
        changedKeys.sort(),
        ['chatbot_image_digest', 'release_id', 'version'].sort(),
      );
      assert.equal(manifest.schema_version, 3);
      assert.equal(
        manifest.retrieval_artifact_id,
        active.retrieval_artifact_id,
      );
      assert.equal(manifest.knowledge_base_id, active.knowledge_base_id);
    },
  );

  await t.test(
    'round-trips through buildCandidateManifest(chatbot-only) and validates',
    () => {
      const newVersion = '1.0.2';
      const newRelease = deriveReleaseId(
        newVersion,
        active.data_artifact_version,
        active.etl_version,
      );
      const manifest = buildCandidateManifest('chatbot-only', active, {
        releaseId: newRelease,
        chatbotVersion: newVersion,
        chatbotImageDigest: digestFor('f'),
      });
      assert.equal(manifest.version, newVersion);
    },
  );
});

test('buildCandidateManifest fails closed on an invalid manifest', () => {
  const inputs = fullManifestInputs({
    retrievalArtifactId: 'sha256-tampered-does-not-match-derivation',
  });
  assert.throws(
    () => buildCandidateManifest('full-retrieval', null, inputs),
    /retrieval_artifact_id must equal/,
  );
});

test('serializeManifest produces single-line JSON with exactly one trailing newline (B1 byte contract)', () => {
  const manifest = buildFullRetrievalManifest(fullManifestInputs());
  const serialized = serializeManifest(manifest);
  assert.equal(serialized.includes('\n', 0), true);
  assert.equal(
    serialized.indexOf('\n'),
    serialized.length - 1,
    'newline must be the last character only',
  );
  assert.deepEqual(JSON.parse(serialized), manifest);
});

// --- Golden manifest test: matches the pre-migration jq builds exactly -----

test('golden: full-retrieval manifest matches the exact field set the prior jq -cnS build produced', () => {
  const inputs = fullManifestInputs();
  const manifest = buildFullRetrievalManifest(inputs);
  assert.deepEqual(Object.keys(manifest).sort(), [
    'bm25_bucket',
    'bm25_key',
    'bm25_tokenizer_revision',
    'chatbot_image_digest',
    'data_artifact_version',
    'data_source_id',
    'etl_image_digest',
    'etl_version',
    'knowledge_base_id',
    'processed_bucket',
    'processed_prefix',
    'raw_bucket',
    'raw_prefix',
    'release_id',
    'retrieval_artifact_fingerprint',
    'retrieval_artifact_id',
    'schema_version',
    'version',
  ]);
});

test('golden: chatbot-only manifest preserves every v3 field except the 4 that change', () => {
  const active = buildFullRetrievalManifest(fullManifestInputs());
  const newVersion = '2.0.0';
  const newRelease = deriveReleaseId(
    newVersion,
    active.data_artifact_version,
    active.etl_version,
  );
  const manifest = buildChatbotOnlyManifest(active, {
    releaseId: newRelease,
    chatbotVersion: newVersion,
    chatbotImageDigest: digestFor('z'),
  });
  for (const key of Object.keys(active)) {
    if (['release_id', 'version', 'chatbot_image_digest'].includes(key))
      continue;
    assert.equal(
      manifest[key],
      active[key],
      `field ${key} must be preserved verbatim`,
    );
  }
});

// --- selectorTransition ------------------------------------------------------

test('selectorTransition', async (t) => {
  const selectors = {
    activeSelector: '/qa/renate/retrieval/active-manifest',
    previousSelector: '/qa/renate/retrieval/previous-manifest',
    newActiveFile: '/tmp/new-active.json',
    newPreviousFile: '/tmp/new-previous.json',
  };

  await t.test('activate writes previous-manifest first', () => {
    const plan = selectorTransition('activate', selectors);
    assert.equal(plan[0].name, selectors.previousSelector);
    assert.equal(plan[0].valueFile, selectors.newPreviousFile);
    assert.equal(plan[1].name, selectors.activeSelector);
    assert.equal(plan[1].valueFile, selectors.newActiveFile);
  });

  await t.test('rollback writes active-manifest first', () => {
    const plan = selectorTransition('rollback', selectors);
    assert.equal(plan[0].name, selectors.activeSelector);
    assert.equal(plan[1].name, selectors.previousSelector);
  });

  await t.test('unknown kind throws (fail-closed)', () => {
    assert.throws(
      () => selectorTransition('sideways', selectors),
      /unknown selector transition kind/,
    );
  });
});

// --- tokenizerCoherence -------------------------------------------------------

test('tokenizerCoherence', async (t) => {
  await t.test('matching tokenizers are coherent', () => {
    assert.deepEqual(tokenizerCoherence('tok-1', 'tok-1'), { ok: true });
  });

  await t.test('mismatched tokenizers fail with an explanatory reason', () => {
    const result = tokenizerCoherence('tok-bad', 'tok-good');
    assert.equal(result.ok, false);
    assert.match(result.reason, /tok-good.*tok-bad/);
    assert.match(result.reason, /full application rollback/);
  });
});

// --- confirmRollbackTarget ----------------------------------------------------

test('confirmRollbackTarget', async (t) => {
  await t.test('matching confirmation is ok', () => {
    assert.deepEqual(
      confirmRollbackTarget({ expected: 'sha256-good', target: 'sha256-good' }),
      { ok: true },
    );
  });

  await t.test(
    'mismatched confirmation fails with target in the reason',
    () => {
      const result = confirmRollbackTarget({
        expected: 'sha256-not-the-target',
        target: 'sha256-good',
      });
      assert.equal(result.ok, false);
      assert.match(result.reason, /sha256-good/);
    },
  );

  await t.test('missing confirmation fails distinctly from a wrong one', () => {
    const result = confirmRollbackTarget({
      expected: undefined,
      target: 'sha256-good',
    });
    assert.equal(result.ok, false);
    assert.match(result.reason, /required to match/);
  });
});


// --- CLI dispatcher (subprocess, mirrors release-retention.test.mjs style) --

function runCli(args, input) {
  const workdir = mkdtempSync(join(tmpdir(), 'retrieval-orchestration-cli-'));
  try {
    const inputPath = join(workdir, 'input.json');
    writeFileSync(inputPath, JSON.stringify(input));
    const result = spawnSync(process.execPath, [SCRIPT, ...args, inputPath], {
      encoding: 'utf8',
    });
    return result;
  } finally {
    rmSync(workdir, { recursive: true, force: true });
  }
}

test('CLI: resolve-slots reads JSON from a file path and prints the decision', () => {
  const result = runCli(['resolve-slots'], {
    activeKbId: 'kb-blue',
    blueKbId: 'kb-blue',
    greenKbId: 'kb-green',
  });
  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), {
    activeSlot: 'blue',
    inactiveSlot: 'green',
  });
});

test('CLI: tokenizer-coherence exits non-zero and prints the failure reason on mismatch', () => {
  const result = runCli(['tokenizer-coherence'], {
    badTokenizer: 'a',
    targetTokenizer: 'b',
  });
  assert.equal(result.status, 1);
  const parsed = JSON.parse(result.stdout);
  assert.equal(parsed.ok, false);
});

test('CLI: unknown command prints usage and exits 2', () => {
  const workdir = mkdtempSync(join(tmpdir(), 'retrieval-orchestration-cli-'));
  try {
    const inputPath = join(workdir, 'input.json');
    writeFileSync(inputPath, '{}');
    const result = spawnSync(
      process.execPath,
      [SCRIPT, 'not-a-real-command', inputPath],
      { encoding: 'utf8' },
    );
    assert.equal(result.status, 2);
    assert.match(result.stderr, /Usage: retrieval-orchestration\.mjs/);
  } finally {
    rmSync(workdir, { recursive: true, force: true });
  }
});

