#!/usr/bin/env bash
# upload-data-artifacts.sh
# Content-gated upload of seed corpus (XML brochures + Markdown Merkblätter) to a
# versioned S3 prefix. Runs inside the build-data-artifacts CI job after OIDC
# role assumption.
#
# Decision D1: upload + reprocess ONLY when corpus content changed.
# Decision D2: fail toward reprocess — any doubt (missing/unreadable hash) → proceed.
# Decision D3: rotate data-artifact-version-previous before writing new version.
# Hash is written LAST so a mid-run failure forces a re-run rather than skipping.
#
# Portability: the CI image (node-aws) ships no python3, so manifest generation
# and the tombstone diff are done in pure shell (bash + coreutils: sed/grep/comm/
# tr/sort). No python3 or jq dependency.
#
# Required env: NEW_TAG, GITLAB_OIDC_TOKEN (already consumed by CI job),
#               AWS credentials exported by the CI job before calling this script.
set -euo pipefail

REGION="eu-central-1"
BASE="cdk/seed-data/source"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/qa-retrieval-polling.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-polling.sh"
# #590: dotenv consumed via artifacts:reports:dotenv by build-data-artifacts,
# so deploy-etl:dev / etl-readiness-data:dev can gate on whether a data
# ingestion pass is in flight. Emitted on BOTH the early-exit-unchanged path
# and the changed/uploaded path (Decision D7).
DATA_ARTIFACT_ENV_FILE="${DATA_ARTIFACT_ENV_FILE:-data-artifact.env}"
: >"$DATA_ARTIFACT_ENV_FILE"

# Readiness baseline — captured immediately before the S3 upload that fires
# the unfiltered ObjectCreated → SQS → Transform → docs/*.md → KB ingestion
# reprocess (see project-overview.md "Data artifact flow"). Mirrors the fix
# already applied to deploy-and-verify-etl-dev.sh (#590 issues #3/#7):
# etl-readiness-check.sh filters ListIngestionJobs for a job that started
# AT/AFTER --start-ts. Capturing that timestamp only after this script
# returns (the previous etl-readiness-data:dev behavior) is too late — the
# reprocess this upload triggers is typically fast enough to start AND
# complete before build-data-artifacts itself finishes, so a start-ts taken
# by the caller after this job ends would reject the real ingestion job as
# stale and poll forever until timeout. Emitted here, before any upload, so
# etl-readiness-data:dev can pass it straight through to
# etl-readiness-check.sh instead of defaulting to "capture now".
# Resolve an OPTIONAL SSM parameter, distinguishing three outcomes so the
# readiness handoff can be skipped ONLY for a genuinely absent parameter —
# never for a permission/credential/service error:
#   stdout=value, return 0  → parameter read succeeded (value may be empty)
#   return 10 (no stdout)    → ParameterNotFound (legit: ETL stack not deployed
#                              yet in this environment)
#   return 1  (stderr diag)  → ANY other failure (AccessDenied, throttling,
#                              expired creds, network). MUST fail loud.
# The former `2>/dev/null || echo ""` collapsed all three into "" and let an
# AccessDenied masquerade as "not deployed": the data-artifacts CI role could
# read the data-artifact params but not the ETL DLQ ARNs, so the baseline was
# silently skipped, etl-readiness-data:dev captured its own too-late start-ts,
# and the gate timed out on an ingestion that had actually succeeded — the
# exact race MR !972 set out to fix, reproduced via its own escape hatch
# (pipeline #3770).
_resolve_readiness_arn_param() {
  local name="$1" stderr_file value status
  stderr_file=$(mktemp)
  if value=$(aws ssm get-parameter --name "$name" \
      --query Parameter.Value --output text --region "$REGION" 2>"$stderr_file"); then
    rm -f "$stderr_file"
    printf '%s' "$value"
    return 0
  else
    status=$?
    if grep -q 'ParameterNotFound' "$stderr_file"; then
      rm -f "$stderr_file"
      return 10
    fi
    echo "ERROR: failed to read SSM parameter ${name} (exit ${status}) — this" \
      "is NOT a ParameterNotFound:" >&2
    cat "$stderr_file" >&2
    rm -f "$stderr_file"
    return 1
  fi
}

_readiness_baseline() {
  local transform_dlq_arn bm25_dlq_arn rc_transform rc_bm25

  if transform_dlq_arn=$(_resolve_readiness_arn_param "/dev/renate/etl-dlq-arn"); then
    rc_transform=0
  else
    rc_transform=$?
  fi
  if bm25_dlq_arn=$(_resolve_readiness_arn_param "/dev/renate/bm25-rebuild-dlq-arn"); then
    rc_bm25=0
  else
    rc_bm25=$?
  fi

  # Hard error on either read (AccessDenied / throttling / expired creds /
  # network — anything that is NOT a clean ParameterNotFound) → fail loud,
  # BEFORE the upload. Skipping here would drop the start-ts handoff and
  # reproduce the #3770 race; failing surfaces the misconfiguration (e.g. a
  # missing ssm:GetParameter grant on the data-artifacts role) so it is fixed
  # rather than silently degrading the readiness gate into a false timeout.
  if [ "$rc_transform" -eq 1 ] || [ "$rc_bm25" -eq 1 ]; then
    echo "❌ Could not read the ETL readiness SSM parameters (see error" \
      "above). Refusing to skip the data-artifact readiness baseline: a silent" \
      "skip makes etl-readiness-data:dev capture its own too-late start-ts and" \
      "time out on an ingestion that actually succeeded (the MR !972 race)." \
      "Grant the data-artifacts role ssm:GetParameter on /dev/renate/etl-dlq-arn" \
      "and /dev/renate/bm25-rebuild-dlq-arn, then retry." >&2
    return 1
  fi

  # ParameterNotFound (rc 10) or an empty value → ETL stack not deployed yet in
  # this environment. Legit skip: no reprocess wiring exists, so
  # etl-readiness-data:dev's own no-op/capture path is correct here.
  if [ -z "$transform_dlq_arn" ] || [ -z "$bm25_dlq_arn" ]; then
    echo "⏭ ETL stack not yet deployed (no queue ARNs in SSM) — skipping" \
      "readiness baseline capture; etl-readiness-data:dev will capture its own."
    return 0
  fi

  local start_ts transform_dlq_baseline bm25_dlq_baseline
  start_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  transform_dlq_baseline=$(qa_retrieval_dlq_depth "$transform_dlq_arn")
  bm25_dlq_baseline=$(qa_retrieval_dlq_depth "$bm25_dlq_arn")
  echo "Captured readiness baseline (pre-upload): start_ts=${start_ts}" \
    "transform_dlq=${transform_dlq_baseline} bm25_dlq=${bm25_dlq_baseline}"
  {
    echo "DATA_ARTIFACT_READINESS_START_TS=${start_ts}"
    echo "DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE=${transform_dlq_baseline}"
    echo "DATA_ARTIFACT_BM25_DLQ_BASELINE=${bm25_dlq_baseline}"
  } >>"$DATA_ARTIFACT_ENV_FILE"
}

_run_retention() {
  if [ -n "${RELEASE_RETENTION_STUB:-}" ]; then
    "$RELEASE_RETENTION_STUB" "$@"
  else
    node "${SCRIPT_DIR}/../lib/node/release-retention.mjs" "$@"
  fi
}

_reconcile_data_retention() {
  local active_version="$1" previous_version="${2:-}" candidate_version="${3:-}"
  local args=(
    reconcile
    --bucket "$BUCKET"
    --managed-prefix "releases/v"
    --protected-prefix "releases/${active_version}/"
    --region "$REGION"
  )
  if [ -n "$previous_version" ] && [ "$previous_version" != "$active_version" ]; then
    args+=(--protected-prefix "releases/${previous_version}/")
  fi
  if [ -n "$candidate_version" ] \
      && [ "$candidate_version" != "$active_version" ] \
      && [ "$candidate_version" != "$previous_version" ]; then
    args+=(--protected-prefix "releases/${candidate_version}/")
  fi
  _run_retention "${args[@]}"
}

# ── 1. Resolve version and bucket ────────────────────────────────────────────
VERSION="v${NEW_TAG}"

BUCKET=$(aws ssm get-parameter \
  --name "/dev/renate/etl-source-bucket-name" \
  --query Parameter.Value --output text \
  --region "$REGION")

echo "Publishing data artifact ${VERSION} to s3://${BUCKET}/releases/${VERSION}/"

# ── 2. Compute corpus hash (null-delimited — filenames may contain spaces) ───
# Covers the exact file set that will be uploaded: *.xml and *.md only.
# Merkblatt *.pdf stays in the repo as the Textract input for
# extract_merkblaetter.py, but the KB artifact is now the rendered *.md (#501).
HASH=$(find "$BASE" -type f \( -name '*.xml' -o -name '*.md' \) \
  -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)

echo "Corpus hash: ${HASH}"

# ── 3. Content gate (Decision D1 + D2) ───────────────────────────────────────
PREV_HASH=$(aws ssm get-parameter \
  --name "/dev/renate/data-artifact-content-hash" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")

if [ -n "$PREV_HASH" ] && [ "$PREV_HASH" = "$HASH" ]; then
  echo "seed corpus unchanged (${HASH}) — skipping upload/reprocess"
  # #590: emit DATA_ARTIFACT_CHANGED=false + the (unchanged) active version on
  # the early-exit path too, so deploy-etl:dev / etl-readiness-data:dev can
  # decide whether to wait for a data-ingestion pass without re-deriving state.
  CURRENT_VERSION=$(aws ssm get-parameter \
    --name "/dev/renate/data-artifact-version" \
    --query Parameter.Value --output text \
    --region "$REGION" 2>/dev/null || echo "")
  if [ -z "$CURRENT_VERSION" ]; then
    echo "ERROR: matching content hash has no active data-artifact-version" >&2
    exit 1
  fi
  CURRENT_PREVIOUS_VERSION=$(aws ssm get-parameter \
    --name "/dev/renate/data-artifact-version-previous" \
    --query Parameter.Value --output text \
    --region "$REGION" 2>/dev/null || echo "")
  _reconcile_data_retention "$CURRENT_VERSION" "$CURRENT_PREVIOUS_VERSION"
  {
    echo "DATA_ARTIFACT_CHANGED=false"
    echo "DATA_ARTIFACT_VERSION=${CURRENT_VERSION}"
  } >>"$DATA_ARTIFACT_ENV_FILE"
  exit 0
fi

echo "Corpus changed (prev=${PREV_HASH:-<none>}) — uploading..."

# ── 3b. Capture the readiness baseline BEFORE the triggering upload ─────────
_readiness_baseline

# ── 4. Upload seed corpus to versioned prefix ─────────────────────────────────
# Fresh prefix per data release → no --delete needed.
aws s3 cp "$BASE/" "s3://${BUCKET}/releases/${VERSION}/xml/" \
  --recursive --exclude "*" --include "*.xml" \
  --region "$REGION"

aws s3 cp "$BASE/" "s3://${BUCKET}/releases/${VERSION}/md/" \
  --recursive --exclude "*" --include "*.md" \
  --region "$REGION"

echo "Upload complete: s3://${BUCKET}/releases/${VERSION}/"

# ── 4b. Compute this release's file/stem set (pure shell) ────────────────────
# Stems = basename without extension and without spaces (matches the ETL
# _compute_stem logic). Filenames may contain spaces (e.g. "FB 28.xml"), so we
# read them a whole line at a time — brochure filenames never contain newlines.
xml_names=$(find "$BASE" -maxdepth 1 -type f -name '*.xml' -exec basename {} \; \
  | LC_ALL=C sort)
md_names=$(find "$BASE" -maxdepth 1 -type f -name '*.md' -exec basename {} \; \
  | LC_ALL=C sort)
stems=$(printf '%s\n%s\n' "$xml_names" "$md_names" \
  | sed -e '/^$/d' -e 's/\.[^.]*$//' -e 's/ //g' \
  | LC_ALL=C sort -u)

# Emit a JSON array body (one quoted element per line, comma-separated) from
# newline-delimited stdin. $1 = element indent. Always returns 0.
emit_json_array() {
  local indent=${1:-} first=1 item
  while IFS= read -r item; do
    [ -z "$item" ] && continue
    item=${item//\\/\\\\}
    item=${item//\"/\\\"}
    if [ "$first" -eq 1 ]; then first=0; else printf ',\n'; fi
    printf '%s"%s"' "$indent" "$item"
  done
  [ "$first" -eq 0 ] && printf '\n'
  return 0
}

# ── 4c. Write the release manifest (records active stems + files) ────────────
MANIFEST_FILE="$(mktemp)"
{
  printf '{\n'
  printf '  "version": "%s",\n' "$VERSION"
  printf '  "stems": [\n'
  printf '%s\n' "$stems" | emit_json_array '    '
  printf '  ],\n'
  printf '  "files": {\n'
  printf '    "xml": [\n'
  printf '%s\n' "$xml_names" | sed '/^$/d; s|^|xml/|' | emit_json_array '      '
  printf '    ],\n'
  printf '    "md": [\n'
  printf '%s\n' "$md_names" | sed '/^$/d; s|^|md/|' | emit_json_array '      '
  printf '    ]\n'
  printf '  }\n'
  printf '}\n'
} >"$MANIFEST_FILE"

aws s3 cp "$MANIFEST_FILE" "s3://${BUCKET}/releases/${VERSION}/manifest.json" \
  --content-type "application/json" \
  --region "$REGION"
rm -f "$MANIFEST_FILE"
echo "Manifest uploaded: s3://${BUCKET}/releases/${VERSION}/manifest.json"

# ── 4d. Manifest-diff tombstones — clean up removed stems (bug 2 fix) ────────
# For any stem in the previous active release but absent from this one, upload an
# empty tombstone object releases/{VERSION}/deletes/{stem}. The ETL Lambda
# intercepts these ObjectCreated events and deletes docs/{stem}/… without running
# any pipeline. Previous stems are parsed from the previous manifest.json with
# sed/grep (no python3/jq): flatten newlines, capture the "stems" array body,
# then pull the quoted values.
#
# Intentionally NOT gated on PREV_HASH: the tombstone diff must run whenever a
# previous version + manifest exist, regardless of why the content gate opened
# (missing hash, unreadable hash, or genuine content change).  Using PREV_HASH
# as the outer guard would silently skip tombstones on the hash-missing path —
# the new release is uploaded and the hash is written, so stale docs/ entries
# would persist and every subsequent run would skip the tombstone diff entirely.
PREV_VERSION_FOR_DIFF=$(aws ssm get-parameter \
  --name "/dev/renate/data-artifact-version" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")
ROLLBACK_VERSION=$(aws ssm get-parameter \
  --name "/dev/renate/data-artifact-version-previous" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")

if [ -z "$PREV_VERSION_FOR_DIFF" ]; then
  echo "No previous data-artifact-version in SSM — first run, no tombstones."
else
  PREV_MANIFEST_FILE="$(mktemp)"
  if aws s3 cp "s3://${BUCKET}/releases/${PREV_VERSION_FOR_DIFF}/manifest.json" \
      "$PREV_MANIFEST_FILE" --region "$REGION" 2>/dev/null \
      && [ -s "$PREV_MANIFEST_FILE" ]; then
    prev_stems=$( { tr -d '\n' <"$PREV_MANIFEST_FILE" \
      | sed -n 's/.*"stems" *: *\[\([^]]*\)\].*/\1/p' \
      | grep -oE '"[^"]*"' \
      | sed 's/^"//; s/"$//'; } || true)

    removed_stems=$(comm -23 \
      <(printf '%s\n' "$prev_stems" | sed '/^$/d' | LC_ALL=C sort -u) \
      <(printf '%s\n' "$stems" | sed '/^$/d' | LC_ALL=C sort -u))

    if [ -n "$removed_stems" ]; then
      echo "Removed stems detected — uploading tombstones:"
      TOMBSTONE_TMP="$(mktemp)"
      : >"$TOMBSTONE_TMP"
      while IFS= read -r stem; do
        [ -z "$stem" ] && continue
        echo "  tombstone: releases/${VERSION}/deletes/${stem}"
        aws s3 cp "$TOMBSTONE_TMP" \
          "s3://${BUCKET}/releases/${VERSION}/deletes/${stem}" \
          --region "$REGION"
      done <<<"$removed_stems"
      rm -f "$TOMBSTONE_TMP"
      echo "Tombstones uploaded."
    else
      echo "No removed stems — no tombstones needed."
    fi
  else
    echo "Previous manifest not found for ${PREV_VERSION_FOR_DIFF} — skipping tombstone diff."
  fi
  rm -f "$PREV_MANIFEST_FILE"
fi

# New release objects become lifecycle-visible only through an explicit tag.
# Missing tags are intentionally safe, but a successfully staged candidate is
# marked unpinned before the pin-first pointer transition. A retry of the
# already-active coordinate never temporarily unpins that live release.
if [ "$VERSION" != "$PREV_VERSION_FOR_DIFF" ]; then
  _run_retention unpin \
    --bucket "$BUCKET" \
    --prefix "releases/${VERSION}/" \
    --region "$REGION"
fi

# Protect the candidate plus both currently protected coordinates before any
# SSM pointer changes. Reconcile pins the protected phase completely before it
# unpins stale releases.
PRE_PIN_ACTIVE="$PREV_VERSION_FOR_DIFF"
if [ -z "$PRE_PIN_ACTIVE" ]; then
  PRE_PIN_ACTIVE="$VERSION"
fi
_reconcile_data_retention "$PRE_PIN_ACTIVE" "$ROLLBACK_VERSION" "$VERSION"

# ── 5. Rotate SSM pointers (hash written LAST — it is the skip gate) ─────────
# Capture outgoing version (empty on first run — best-effort, ignore failure).
PREV_VERSION=$(aws ssm get-parameter \
  --name "/dev/renate/data-artifact-version" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")

# AWS SSM rejects empty-string values (min length 1). On the very first run
# data-artifact-version does not yet exist, so PREV_VERSION is empty — skip
# the -previous write rather than crashing the job. If a prior attempt already
# advanced the active pointer to this candidate, preserve its existing rollback
# pointer instead of collapsing active and previous to the same version.
if [ "${PREV_VERSION}" = "${VERSION}" ]; then
  echo "Resuming partially committed ${VERSION}; preserving version-previous."
elif [ -n "${PREV_VERSION}" ]; then
  aws ssm put-parameter \
    --name "/dev/renate/data-artifact-version-previous" \
    --value "${PREV_VERSION}" \
    --type String --overwrite \
    --region "$REGION"
else
  echo "First run — no previous data-artifact-version; skipping version-previous SSM write."
fi

aws ssm put-parameter \
  --name "/dev/renate/data-artifact-version" \
  --value "${VERSION}" \
  --type String --overwrite \
  --region "$REGION"

# Read back the committed rollback coordinate. This is deliberately not inferred
# from PREV_VERSION: on an idempotent retry PREV_VERSION is already the candidate,
# while version-previous still names the real rollback release.
COMMITTED_PREVIOUS_VERSION=$(aws ssm get-parameter \
  --name "/dev/renate/data-artifact-version-previous" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")

# Converge to the new active/previous union before writing the content-hash
# commit marker. A failure leaves the candidate/outgoing coordinates pinned and
# forces a retry instead of allowing the next run to skip reconciliation.
_reconcile_data_retention "$VERSION" "$COMMITTED_PREVIOUS_VERSION"

# Written last: if anything above failed the job exits before reaching this
# line, so the next run will not see an up-to-date hash and will re-upload.
aws ssm put-parameter \
  --name "/dev/renate/data-artifact-content-hash" \
  --value "${HASH}" \
  --type String --overwrite \
  --region "$REGION"

echo "SSM pointers updated: data-artifact-version=${VERSION}"

# #590: emit DATA_ARTIFACT_CHANGED=true + the new version on the
# changed/uploaded path (Decision D7).
{
  echo "DATA_ARTIFACT_CHANGED=true"
  echo "DATA_ARTIFACT_VERSION=${VERSION}"
} >>"$DATA_ARTIFACT_ENV_FILE"
