#!/usr/bin/env bash
# Non-mutating validation for the #642 preprod legacy blue baseline. No AWS:
# proves the three-line pin and that the deterministic schema-v2 baseline
# manifest (with the derived release_id and canonical prefixes) passes the real
# retrieval-release.mjs validator. Live digests/IDs are checked by the operator
# capture (scripts/capture-blue-baseline.sh); here they are shape placeholders.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
RETRIEVAL_RELEASE="${REPO_ROOT}/.gitlab/ci/scripts/lib/node/retrieval-release.mjs"
PIN="${PREPROD_VERSION_PIN:-${REPO_ROOT}/deployments/preprod/version.yaml}"

EXPECTED_VERSION="1.83.3"
EXPECTED_COORDINATE="v1.83.3-preprod-blue-baseline"

fail() { echo "validate-preprod-blue-baseline: $*" >&2; exit 1; }

[ -f "$PIN" ] || fail "missing ${PIN}"

# Exactly three keys, in the truthful order, and no extra lines.
mapfile -t LINES < <(grep -vE '^\s*$' "$PIN")
[ "${#LINES[@]}" -eq 3 ] || fail "pin must be exactly three lines, found ${#LINES[@]}"

VERSION=$(awk '$1=="version:"{print $2}' "$PIN")
DATA=$(awk '$1=="data_artifact_version:"{print $2}' "$PIN")
ETL=$(awk '$1=="etl_version:"{print $2}' "$PIN")

[ "$VERSION" = "$EXPECTED_VERSION" ] || fail "version must be ${EXPECTED_VERSION}, got '${VERSION}'"
[ "$DATA" = "$EXPECTED_COORDINATE" ] || fail "data_artifact_version must be ${EXPECTED_COORDINATE}, got '${DATA}'"
[ "$ETL" = "$EXPECTED_COORDINATE" ] || fail "etl_version must be ${EXPECTED_COORDINATE}, got '${ETL}'"

# The legacy ^version: parser must still yield the chatbot version.
PARSED=$(grep '^version:' "$PIN" | sed 's/version: //')
[ "$PARSED" = "$EXPECTED_VERSION" ] || fail "legacy ^version: parser yields '${PARSED}', expected ${EXPECTED_VERSION}"

RELEASE_ID="$(node "$RETRIEVAL_RELEASE" derive-release "$VERSION" "$DATA" "$ETL")"
echo "Derived release_id: ${RELEASE_ID}"

# Build the deterministic schema-v2 baseline manifest with shape placeholders
# for the live-discovered fields and validate it against the real gate.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
jq -n --arg rid "$RELEASE_ID" --arg v "$VERSION" --arg data "$DATA" --arg etl "$ETL" \
  --arg pp "processed/releases/${RELEASE_ID}/" --arg bm "bm25_index/releases/${RELEASE_ID}/index.json" \
  --arg raw "releases/${DATA}/" '
  {schema_version:2,release_id:$rid,version:$v,data_artifact_version:$data,etl_version:$etl,
   knowledge_base_id:"PLACEHOLDERKB",data_source_id:"PLACEHOLDERDS",
   raw_bucket:"renate-s3-etl-source-dev-000000",raw_prefix:$raw,
   processed_bucket:"renate-s3-kb-ingestion-bucket-dev-000000",processed_prefix:$pp,
   bm25_bucket:"renate-s3-kb-ingestion-bucket-dev-000000",bm25_key:$bm,
   bm25_tokenizer_revision:"cistem-decompound-v1",
   etl_image_digest:"sha256:0000000000000000000000000000000000000000000000000000000000000000"}' >"$TMP"
node "$RETRIEVAL_RELEASE" validate "$TMP"
echo "schema-v2 baseline manifest shape validated for ${RELEASE_ID}."
