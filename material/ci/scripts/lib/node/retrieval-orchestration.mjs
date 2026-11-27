#!/usr/bin/env node
// @ts-check
// #630 — pure decision functions for the QA retrieval blue/green promotion
// state machine, extracted out of deploy-qa-retrieval-candidate.sh,
// activate-qa-retrieval.sh, and rollback-qa-retrieval.sh so the decisions
// (which slot, chatbot-only vs full-retrieval, recovery arming, selector
// write ordering, rollback coherence, retention-cleanup selection) are
// unit-testable without AWS. All AWS I/O, traps, interactive prompts, and
// retention-cleanup *execution* stay in Bash; this module only decides.
//
// Dependency-free, matching retrieval-release.mjs. Types here are
// advisory/editor-time only (// @ts-check, no CI type-checker) — adding one
// would reintroduce a TypeScript build dependency this CI-scripts area
// deliberately does not have.
import fs from 'node:fs';

import {
  deriveArtifactFingerprint,
  deriveArtifactId,
  deriveReleaseId,
  validateManifest,
} from './retrieval-release.mjs';

function fail(message) {
  throw new Error(message);
}

/**
 * Resolve which manifest-managed slot (blue/green) is currently active vs inactive from
 * the active manifest's knowledge_base_id. Mirrors the `case "$ACTIVE_KB_ID"`
 * block in deploy-qa-retrieval-candidate.sh.
 *
 * @param {{activeKbId: string, blueKbId: string, greenKbId: string}} input
 * @returns {{activeSlot: 'blue'|'green', inactiveSlot: 'blue'|'green'}}
 */
export function resolveSlots({ activeKbId, blueKbId, greenKbId }) {
  if (activeKbId === blueKbId)
    return { activeSlot: 'blue', inactiveSlot: 'green' };
  if (activeKbId === greenKbId)
    return { activeSlot: 'green', inactiveSlot: 'blue' };
  fail('active manifest does not select a provisioned retrieval slot');
}

/**
 * Decide whether this promotion is chatbot-only (retrieval artifact
 * unchanged) or full-retrieval (new data/ETL/tokenizer build required).
 * Mirrors the CHATBOT_ONLY block in deploy-qa-retrieval-candidate.sh: all
 * five conditions must hold, including the active manifest already being at
 * schema_version >= 3 (chatbot-only reuses the active manifest's fields
 * verbatim, which only exist from v3 onward).
 *
 * @param {{data_artifact_version: string, etl_version: string, schema_version: number}} activeManifest
 * @param {string} activeTokenizer
 * @param {string} activeArtifactId
 * @param {{dataArtifactVersion: string, etlVersion: string, tokenizerRevision: string, retrievalArtifactId: string}} coords
 * @returns {'chatbot-only'|'full-retrieval'}
 */
export function decidePromotionPath(
  activeManifest,
  activeTokenizer,
  activeArtifactId,
  coords,
) {
  const chatbotOnly =
    activeManifest.data_artifact_version === coords.dataArtifactVersion &&
    activeManifest.etl_version === coords.etlVersion &&
    activeTokenizer === coords.tokenizerRevision &&
    Number(activeManifest.schema_version) >= 3 &&
    activeArtifactId === coords.retrievalArtifactId;
  return chatbotOnly ? 'chatbot-only' : 'full-retrieval';
}

/**
 * Decide whether the previous-slot recovery arm should be armed for this
 * candidate build, and if so, the coordinates to restore. Mirrors the
 * RECOVERY_ARMED block: only armed when a previous manifest exists AND
 * targets the exact same KB + processed bucket as the candidate build is
 * about to mutate (i.e. the previous release lives in the slot we're about
 * to overwrite). Returns {armed:false} rather than throwing for the
 * no-previous / different-slot cases — those are normal, not errors.
 *
 * @param {{knowledge_base_id: string, processed_bucket: string, processed_prefix: string, data_source_id: string}|null} previousManifest
 * @param {{candidateKbId: string, candidateBucket: string}} candidate
 * @returns {{armed: false} | {armed: true, bucket: string, prefix: string, kbId: string, dataSourceId: string}}
 */
export function armRecovery(
  previousManifest,
  { candidateKbId, candidateBucket },
) {
  if (
    previousManifest &&
    previousManifest.knowledge_base_id === candidateKbId &&
    previousManifest.processed_bucket === candidateBucket
  ) {
    return {
      armed: true,
      bucket: candidateBucket,
      prefix: previousManifest.processed_prefix,
      kbId: previousManifest.knowledge_base_id,
      dataSourceId: previousManifest.data_source_id,
    };
  }
  return { armed: false };
}

/**
 * Build the chatbot-only candidate manifest: clone the (already schema >= 3)
 * active manifest and override exactly the 4 fields that change, preserving
 * every other v3 field verbatim. Mirrors the `jq -cS '.schema_version=3 |
 * .release_id=... | .version=... | .chatbot_image_digest=...'` build.
 *
 * @param {object} activeManifest
 * @param {{releaseId: string, chatbotVersion: string, chatbotImageDigest: string}} overrides
 * @returns {object}
 */
export function buildChatbotOnlyManifest(
  activeManifest,
  { releaseId, chatbotVersion, chatbotImageDigest },
) {
  return {
    ...activeManifest,
    schema_version: 3,
    release_id: releaseId,
    version: chatbotVersion,
    chatbot_image_digest: chatbotImageDigest,
  };
}

/**
 * Build the full-retrieval candidate manifest from scratch. Mirrors the
 * `jq -cnS '{...18 fields...}'` build.
 *
 * @param {{
 *   releaseId: string, retrievalArtifactId: string, retrievalArtifactFingerprint: string,
 *   chatbotVersion: string, dataArtifactVersion: string, etlVersion: string,
 *   candidateKbId: string, candidateDataSourceId: string, rawBucket: string, rawPrefix: string,
 *   candidateBucket: string, processedPrefix: string, bm25Key: string, tokenizerRevision: string,
 *   etlImageDigest: string, chatbotImageDigest: string,
 * }} inputs
 * @returns {object}
 */
export function buildFullRetrievalManifest(inputs) {
  return {
    schema_version: 3,
    release_id: inputs.releaseId,
    retrieval_artifact_id: inputs.retrievalArtifactId,
    retrieval_artifact_fingerprint: inputs.retrievalArtifactFingerprint,
    version: inputs.chatbotVersion,
    data_artifact_version: inputs.dataArtifactVersion,
    etl_version: inputs.etlVersion,
    knowledge_base_id: inputs.candidateKbId,
    data_source_id: inputs.candidateDataSourceId,
    raw_bucket: inputs.rawBucket,
    raw_prefix: inputs.rawPrefix,
    processed_bucket: inputs.candidateBucket,
    processed_prefix: inputs.processedPrefix,
    bm25_bucket: inputs.candidateBucket,
    bm25_key: inputs.bm25Key,
    bm25_tokenizer_revision: inputs.tokenizerRevision,
    etl_image_digest: inputs.etlImageDigest,
    chatbot_image_digest: inputs.chatbotImageDigest,
  };
}

/**
 * Build and validate the candidate manifest for either promotion path, and
 * serialize it exactly as activation's read-back `cmp` requires: single-line
 * compact JSON terminated by exactly one trailing newline (mirrors
 * `retrieval-release.mjs inventory`, which writes
 * `${JSON.stringify(...)}\n`). Key ordering is irrelevant to that cmp (it
 * compares byte-for-byte against what THIS function wrote); the newline is
 * not.
 *
 * @param {'chatbot-only'|'full-retrieval'} path
 * @param {object} activeManifest
 * @param {object} overridesOrInputs
 * @returns {object}
 */
export function buildCandidateManifest(
  path,
  activeManifest,
  overridesOrInputs,
) {
  const manifest =
    path === 'chatbot-only'
      ? buildChatbotOnlyManifest(activeManifest, overridesOrInputs)
      : buildFullRetrievalManifest(overridesOrInputs);
  validateManifest(manifest);
  return manifest;
}

/** Serialize a manifest to the exact bytes activation's `cmp` expects. */
export function serializeManifest(manifest) {
  return `${JSON.stringify(manifest)}\n`;
}

/**
 * Decide the ordered SSM selector-write plan for activation or rollback.
 * Bash executes `aws ssm put-parameter` in the returned order — this
 * function only decides the order, never performs I/O.
 *
 * Activation writes previous-manifest first because the CURRENT active
 * value is already known-good: if the script dies between the two writes,
 * active is still the old (good) release and only previous lags.
 * Rollback writes active-manifest first because the CURRENT active value
 * is the BAD release: recovering active must happen first, so a mid-write
 * death still leaves the service healthy (only the forensic previous-write
 * is incomplete).
 *
 * @param {'activate'|'rollback'} kind
 * @param {{activeSelector: string, previousSelector: string, newActiveFile: string, newPreviousFile: string}} selectors
 * @returns {Array<{name: string, valueFile: string}>}
 */
export function selectorTransition(kind, selectors) {
  const { activeSelector, previousSelector, newActiveFile, newPreviousFile } =
    selectors;
  if (kind === 'activate') {
    return [
      { name: previousSelector, valueFile: newPreviousFile },
      { name: activeSelector, valueFile: newActiveFile },
    ];
  }
  if (kind === 'rollback') {
    return [
      { name: activeSelector, valueFile: newActiveFile },
      { name: previousSelector, valueFile: newPreviousFile },
    ];
  }
  fail(`unknown selector transition kind: ${kind}`);
}

/**
 * Rollback's tokenizer coherence gate. A selector-only flip to a manifest
 * with a DIFFERENT tokenizer would make the running chatbot's own runtime
 * compatibility check fail closed — i.e. this "rollback" would take QA
 * retrieval down, not restore it. That combination needs a full application
 * rollback (chatbot image + retrieval together), out of scope for the
 * selector-only fast path.
 *
 * @param {string} badTokenizer the currently-active (bad) release's tokenizer
 * @param {string} targetTokenizer the rollback target's tokenizer
 * @returns {{ok: true} | {ok: false, reason: string}}
 */
export function tokenizerCoherence(badTokenizer, targetTokenizer) {
  if (badTokenizer !== targetTokenizer) {
    return {
      ok: false,
      reason:
        `previous tokenizer ${targetTokenizer} != running tokenizer ${badTokenizer}; ` +
        'a selector-only rollback would fail closed at runtime. Use a full application ' +
        'rollback (previous chatbot image + retrieval) instead.',
    };
  }
  return { ok: true };
}

/**
 * Rollback's double-rollback confirmation guard. In CI, the caller must
 * supply EXPECTED_TARGET_RELEASE_ID matching the actual rollback target
 * (previous-manifest's release_id) — there is no interactive prompt in CI.
 * On a workstation, Bash performs the interactive `read` itself and calls
 * this with the typed confirmation as `expected`.
 *
 * @param {{expected: string|undefined, target: string}} input
 * @returns {{ok: true} | {ok: false, reason: string}}
 */
export function confirmRollbackTarget({ expected, target }) {
  if (expected === target) return { ok: true };
  return {
    ok: false,
    reason: expected
      ? `confirmation ${expected} does not match rollback target ${target}`
      : `confirmation is required to match rollback target ${target}`,
  };
}

function usage() {
  process.stderr.write(
    'Usage: retrieval-orchestration.mjs <command> FILE\n' +
      '  commands: resolve-slots | decide-path | arm-recovery | build-manifest |\n' +
      '            selector-transition | tokenizer-coherence | confirm-rollback-target\n' +
      '  FILE is a JSON payload matching the command (use - for stdin).\n',
  );
  process.exit(2);
}

function readJsonArg(argPath) {
  const raw =
    argPath === '-'
      ? fs.readFileSync(0, 'utf8')
      : fs.readFileSync(argPath, 'utf8');
  return JSON.parse(raw);
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  const [command, ...args] = process.argv.slice(2);
  try {
    if (command === 'resolve-slots' && args.length === 1) {
      const input = readJsonArg(args[0]);
      process.stdout.write(`${JSON.stringify(resolveSlots(input))}\n`);
    } else if (command === 'decide-path' && args.length === 1) {
      const input = readJsonArg(args[0]);
      const path = decidePromotionPath(
        input.activeManifest,
        input.activeTokenizer,
        input.activeArtifactId,
        input.coords,
      );
      process.stdout.write(`${path}\n`);
    } else if (command === 'arm-recovery' && args.length === 1) {
      const input = readJsonArg(args[0]);
      process.stdout.write(
        `${JSON.stringify(armRecovery(input.previousManifest, input.candidate))}\n`,
      );
    } else if (command === 'build-manifest' && args.length === 1) {
      const input = readJsonArg(args[0]);
      const manifest = buildCandidateManifest(
        input.path,
        input.activeManifest,
        input.inputs,
      );
      process.stdout.write(serializeManifest(manifest));
    } else if (command === 'selector-transition' && args.length === 1) {
      const input = readJsonArg(args[0]);
      process.stdout.write(
        `${JSON.stringify(selectorTransition(input.kind, input.selectors))}\n`,
      );
    } else if (command === 'tokenizer-coherence' && args.length === 1) {
      const input = readJsonArg(args[0]);
      const result = tokenizerCoherence(
        input.badTokenizer,
        input.targetTokenizer,
      );
      process.stdout.write(`${JSON.stringify(result)}\n`);
      if (!result.ok) process.exitCode = 1;
    } else if (command === 'confirm-rollback-target' && args.length === 1) {
      const input = readJsonArg(args[0]);
      const result = confirmRollbackTarget(input);
      process.stdout.write(`${JSON.stringify(result)}\n`);
      if (!result.ok) process.exitCode = 1;
    } else if (command === 'derive-artifact-passthrough' && args.length === 3) {
      // Convenience re-export so callers only need to source this one file.
      process.stdout.write(
        `${deriveArtifactId(...args)} ${deriveArtifactFingerprint(...args)}\n`,
      );
    } else if (command === 'derive-release-passthrough' && args.length === 3) {
      process.stdout.write(`${deriveReleaseId(...args)}\n`);
    } else {
      usage();
    }
  } catch (error) {
    process.stderr.write(`retrieval-orchestration: ${error.message}\n`);
    process.exit(1);
  }
}
