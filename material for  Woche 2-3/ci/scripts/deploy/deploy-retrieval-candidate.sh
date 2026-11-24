#!/usr/bin/env bash
# Build and verify the inactive retrieval candidate for #492 (qa) / #643
# (preprod). Environment-parameterized: stack, roles, selectors, artifact
# basenames, and the #631 raw-source authority all come from
# retrieval-environment.mjs so one code path serves qa and preprod.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: deploy-retrieval-candidate.sh <qa|preprod|prod> [--dry-run]}"
shift
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 <qa|preprod|prod> [--dry-run]" >&2
  exit 2
fi

# shellcheck source=lib/qa-retrieval-common.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-common.sh"
# shellcheck source=lib/qa-retrieval-auth.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-auth.sh"
# shellcheck source=lib/qa-retrieval-polling.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-polling.sh"
# shellcheck source=lib/qa-retrieval-s3.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-s3.sh"
# shellcheck source=lib/qa-retrieval-validation.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-validation.sh"
qa_retrieval_init_env "$ENV"

PROMOTION_ENV="${PROMOTION_ENV:-${REPO_ROOT}/${RETRIEVAL_ARTIFACT_PREFIX}.env}"
OUTPUT_ENV="${OUTPUT_ENV:-${REPO_ROOT}/${ENV}-candidate.env}"
OUTPUT_MANIFEST="${OUTPUT_MANIFEST:-${REPO_ROOT}/${ENV}-candidate-manifest.json}"
ACTIVE_BEFORE_FILE="${ACTIVE_BEFORE_FILE:-${REPO_ROOT}/${ENV}-active-before.json}"
PREVIOUS_BEFORE_FILE="${PREVIOUS_BEFORE_FILE:-${REPO_ROOT}/${ENV}-previous-before.json}"
ETL_STACK="$RETRIEVAL_ETL_STACK"
# Also needed for the dry-run CDK synth path check below.
CHATBOT_STACK="$RETRIEVAL_CHATBOT_STACK"

[[ -f "$PROMOTION_ENV" ]] || { echo "Missing ${PROMOTION_ENV}" >&2; exit 1; }
# shellcheck disable=SC1090
source "$PROMOTION_ENV"

TMP_DIR=$(mktemp -d)
mkdir -p "$TMP_DIR/dev-raw/brochure" "$TMP_DIR/dev-raw/faq" "$TMP_DIR/candidate-docs"

CANDIDATE_LIVE_MUTATED=false
RECOVERY_ARMED=false
RECOVERY_BUCKET=""
RECOVERY_PREFIX=""
RECOVERY_KB_ID=""
RECOVERY_DATA_SOURCE_ID=""

restore_previous_slot() {
  local recovery_start transform_dlq_baseline bm25_dlq_baseline

  echo >&2
  echo "== Restore previous inactive-slot corpus after candidate failure ==" >&2
  qa_retrieval_assert_selectors_unchanged \
    "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE" || return 1
  # A replay can fail after earlier ObjectCreated events have already reached
  # the transform queue. Let those workers finish before replacing live docs;
  # otherwise a late transform can delete part of the restored corpus.
  qa_retrieval_wait_queue_empty \
    "$QA_TRANSFORM_QUEUE" "QA transform queue before recovery" \
    "${QA_RETRIEVAL_TIMEOUT_SECONDS:-3600}" || return 1
  recovery_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  transform_dlq_baseline=$(qa_retrieval_queue_depth "$QA_TRANSFORM_DLQ") || return 1
  bm25_dlq_baseline=$(qa_retrieval_queue_depth "$CANDIDATE_BM25_DLQ") || return 1
  qa_retrieval_restore_immutable_corpus \
    "$RECOVERY_BUCKET" "$RECOVERY_PREFIX" \
    "$TMP_DIR/recovery-corpus" || return 1

  # Event notifications can begin scanning before a bulk copy finishes. Wait
  # through any conflict and explicitly start one final complete-corpus scan.
  qa_retrieval_start_kb_sync \
    "$CANDIDATE_KB_SYNC" "$RECOVERY_BUCKET" || return 1
  "${SCRIPT_DIR}/../verify/etl-readiness-check.sh" \
    --transform-queue-arn "$QA_TRANSFORM_QUEUE" \
    --transform-dlq-arn "$QA_TRANSFORM_DLQ" \
    --bm25-queue-arn "$CANDIDATE_BM25_QUEUE" \
    --bm25-dlq-arn "$CANDIDATE_BM25_DLQ" \
    --knowledge-base-id "$RECOVERY_KB_ID" \
    --data-source-id "$RECOVERY_DATA_SOURCE_ID" \
    --start-ts "$recovery_start" \
    --transform-dlq-baseline "$transform_dlq_baseline" \
    --bm25-dlq-baseline "$bm25_dlq_baseline" \
    --timeout-seconds "${QA_RETRIEVAL_TIMEOUT_SECONDS:-3600}" || return 1

  echo "Previous inactive-slot corpus restored and re-ingested." >&2
}

candidate_exit() {
  local status="$1" recovery_status=0
  trap - EXIT INT TERM
  if [[ "$status" -ne 0 && "$RECOVERY_ARMED" == true ]]; then
    if [[ "$CANDIDATE_LIVE_MUTATED" == true ]]; then
      set +e
      restore_previous_slot
      recovery_status=$?
      set -e
      if [[ "$recovery_status" -ne 0 ]]; then
        echo "CRITICAL: automatic previous-slot recovery failed; do not activate the previous selector." >&2
        # #628: marker intentionally left SET — the degraded window is genuinely
        # still open (the previous slot's live corpus was not restored).
      else
        qa_retrieval_clear_rollback_degraded_marker
      fi
    else
      # #628: the marker was set (RECOVERY_ARMED) but the job died before the
      # first live mutation ran — no window ever actually opened. Clear the
      # false marker (a no-op if the set itself never landed).
      qa_retrieval_clear_rollback_degraded_marker
    fi
  fi
  rm -rf "$TMP_DIR"
  exit "$status"
}

trap 'candidate_exit $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log_section() { printf '\n== %s ==\n' "$1"; }
log_value() { printf '%-30s %s\n' "$1" "$2"; }

log_section "Resolve selectors and retrieval slots"
qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
qa_retrieval_capture_selector "$RETRIEVAL_ACTIVE_SELECTOR" "$ACTIVE_BEFORE_FILE"
qa_retrieval_capture_selector "$RETRIEVAL_PREVIOUS_SELECTOR" "$PREVIOUS_BEFORE_FILE"
[[ -s "$ACTIVE_BEFORE_FILE" ]] || qa_retrieval_fail \
  "#492/#642 requires the completed active-manifest selector"
qa_retrieval_validate_manifest "$ACTIVE_BEFORE_FILE"
[[ ! -s "$PREVIOUS_BEFORE_FILE" ]] || qa_retrieval_validate_manifest "$PREVIOUS_BEFORE_FILE"

BLUE_KB_ID=$(qa_retrieval_required_ssm "${RETRIEVAL_BASE_PATH}/slots/blue/knowledge-base-id")
GREEN_KB_ID=$(qa_retrieval_required_ssm "${RETRIEVAL_BASE_PATH}/slots/green/knowledge-base-id")
ACTIVE_KB_ID=$(jq -r .knowledge_base_id "$ACTIVE_BEFORE_FILE")
jq -n --arg active "$ACTIVE_KB_ID" --arg blue "$BLUE_KB_ID" --arg green "$GREEN_KB_ID" \
  '{activeKbId:$active, blueKbId:$blue, greenKbId:$green}' >"$TMP_DIR/resolve-slots-input.json"
SLOTS_JSON=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" resolve-slots \
  "$TMP_DIR/resolve-slots-input.json") || qa_retrieval_fail \
  "active manifest does not select a provisioned ${ENV} slot"
ACTIVE_SLOT=$(jq -r .activeSlot <<<"$SLOTS_JSON")
INACTIVE_SLOT=$(jq -r .inactiveSlot <<<"$SLOTS_JSON")
OUTGOING_ETL_IMAGE_DIGEST=$(jq -r .etl_image_digest "$ACTIVE_BEFORE_FILE")
ACTIVE_TOKENIZER=$(jq -r .bm25_tokenizer_revision "$ACTIVE_BEFORE_FILE")
ACTIVE_ARTIFACT_ID=$(jq -r '.retrieval_artifact_id // .release_id' "$ACTIVE_BEFORE_FILE")

# Capture the exact chatbot bytes currently serving this environment while the
# promotion role is active. Schema v2 has no chatbot_image_digest, so the live
# Lambda is the only truthful rollback source. Schema v3 records one and must
# agree with the running stack.
OUTGOING_CHATBOT_IMAGE_DIGEST=$(
  qa_retrieval_resolve_stack_image_digest "$CHATBOT_STACK"
)
ACTIVE_MANIFEST_CHATBOT_DIGEST=$(
  jq -r '.chatbot_image_digest // empty' "$ACTIVE_BEFORE_FILE"
)
if [[ -n "$ACTIVE_MANIFEST_CHATBOT_DIGEST" &&
      "$ACTIVE_MANIFEST_CHATBOT_DIGEST" != "$OUTGOING_CHATBOT_IMAGE_DIGEST" ]]; then
  qa_retrieval_fail \
    "active manifest chatbot digest ${ACTIVE_MANIFEST_CHATBOT_DIGEST} does not" \
    "match live stack digest ${OUTGOING_CHATBOT_IMAGE_DIGEST}"
fi

log_value "active slot:" "$ACTIVE_SLOT"
log_value "inactive slot:" "$INACTIVE_SLOT"
log_value "active release:" "$(jq -r .release_id "$ACTIVE_BEFORE_FILE")"
log_value "live chatbot digest:" "$OUTGOING_CHATBOT_IMAGE_DIGEST"

log_section "Resolve immutable dev image inputs"
# Chatbot/ETL image metadata always originates in dev; both qa and preprod
# read it with the dev reader (RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN). The
# dev source bucket name is only consumed by the origin-mode dev fallback
# below; reading it here is harmless for preprod (never used in downstream mode).
qa_retrieval_assume_oidc "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN" image-metadata
DEV_SOURCE_BUCKET=$(qa_retrieval_required_ssm /dev/renate/etl-source-bucket-name)
CHATBOT_METADATA=$(qa_retrieval_required_ssm "/dev/renate/image-metadata/chatbot/${CHATBOT_VERSION}")
ETL_METADATA=$(qa_retrieval_required_ssm "/dev/renate/image-metadata/etl/${ETL_VERSION}")
printf '%s\n' "$CHATBOT_METADATA" >"$TMP_DIR/chatbot-metadata.json"
printf '%s\n' "$ETL_METADATA" >"$TMP_DIR/etl-metadata.json"

jq -e --arg tag "$CHATBOT_VERSION" '
  .schema_version == 1 and .image_kind == "chatbot" and .image_tag == $tag
  and (.image_digest | test("^sha256:[0-9a-f]{64}$"))
  and (.bm25_tokenizer_revision | type == "string" and length > 0)
  and (.retrieval_manifest_schema_versions | index(3))
  and (.bm25_index_schema_versions | index(2))
' "$TMP_DIR/chatbot-metadata.json" >/dev/null || qa_retrieval_fail "invalid chatbot image metadata"
jq -e --arg tag "$ETL_VERSION" '
  .schema_version == 1 and .image_kind == "etl" and .image_tag == $tag
  and (.image_digest | test("^sha256:[0-9a-f]{64}$"))
  and (.bm25_tokenizer_revision | type == "string" and length > 0)
  and (.retrieval_manifest_schema_versions | index(3))
  and (.bm25_index_schema_versions | index(2))
' "$TMP_DIR/etl-metadata.json" >/dev/null || qa_retrieval_fail "invalid ETL image metadata"

CHATBOT_IMAGE_DIGEST=$(jq -r .image_digest "$TMP_DIR/chatbot-metadata.json")
ETL_IMAGE_DIGEST=$(jq -r .image_digest "$TMP_DIR/etl-metadata.json")
CHATBOT_TOKENIZER=$(jq -r .bm25_tokenizer_revision "$TMP_DIR/chatbot-metadata.json")
ETL_TOKENIZER=$(jq -r .bm25_tokenizer_revision "$TMP_DIR/etl-metadata.json")

# Image recoverability, incoming AND outgoing, while the image-metadata reader
# is still the active credential. Incoming: the transaction must not begin if an
# image it will deploy is absent, or it fails after mutation. Outgoing: a #493
# selector-flip rollback restores the previous manifest, which is only usable if
# that manifest's images still exist. Both run in the dry-run preflight and
# again under the lock, because an image can be reaped in between. The exact
# digests checked here are also the coordinates passed to CDK below.
log_section "Verify image recoverability (incoming and outgoing)"
# Run these under the PROMOTION role, not the image-metadata reader: the dev
# reader holds no ECR permission at all, while preprod's promotion role carries
# ecr:DescribeImages on both dev repos (bootstrap DevEcrPull) and the dev repo
# policies grant the qa/preprod account roots. qa's promotion role has no ECR
# grant yet, so qa reports UNVERIFIED until one is added. Safe to re-assume here:
# every later AWS call assumes its own role explicitly.
qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
qa_retrieval_assert_image_recoverable "incoming chatbot" \
  renate-chat-lambda "$CHATBOT_IMAGE_DIGEST"
qa_retrieval_assert_image_recoverable "incoming ETL" \
  renate-etl-lambda "$ETL_IMAGE_DIGEST"
qa_retrieval_assert_image_recoverable "outgoing chatbot" \
  renate-chat-lambda "$OUTGOING_CHATBOT_IMAGE_DIGEST"
qa_retrieval_assert_image_recoverable "outgoing ETL" \
  renate-etl-lambda "$OUTGOING_ETL_IMAGE_DIGEST"

# This is the complete tokenizer scope for #492: a compatibility gate before
# any AWS mutation. Deliberate tokenizer migrations remain outside this job.
[[ "$CHATBOT_TOKENIZER" == "$ETL_TOKENIZER" ]] || qa_retrieval_fail \
  "tokenizer mismatch: chatbot=${CHATBOT_TOKENIZER} ETL=${ETL_TOKENIZER}; no AWS resources changed"
[[ "$CHATBOT_TOKENIZER" == "$ACTIVE_TOKENIZER" ]] || qa_retrieval_fail \
  "normal zero-downtime promotion cannot bridge active tokenizer ${ACTIVE_TOKENIZER} to ${CHATBOT_TOKENIZER}; no AWS resources changed"
TOKENIZER_REVISION="$CHATBOT_TOKENIZER"

read -r RETRIEVAL_ARTIFACT_ID RETRIEVAL_ARTIFACT_FINGERPRINT < <(
  node "${SCRIPT_DIR}/../lib/node/retrieval-release.mjs" derive-artifact \
    "$DATA_ARTIFACT_VERSION" "$ETL_VERSION" "$TOKENIZER_REVISION"
)

jq -n \
  --slurpfile active "$ACTIVE_BEFORE_FILE" \
  --arg activeTokenizer "$ACTIVE_TOKENIZER" \
  --arg activeArtifactId "$ACTIVE_ARTIFACT_ID" \
  --arg data "$DATA_ARTIFACT_VERSION" \
  --arg etl "$ETL_VERSION" \
  --arg tokenizer "$TOKENIZER_REVISION" \
  --arg artifact "$RETRIEVAL_ARTIFACT_ID" '
    {
      activeManifest: $active[0],
      activeTokenizer: $activeTokenizer,
      activeArtifactId: $activeArtifactId,
      coords: {
        dataArtifactVersion: $data,
        etlVersion: $etl,
        tokenizerRevision: $tokenizer,
        retrievalArtifactId: $artifact
      }
    }
  ' >"$TMP_DIR/decide-path-input.json"
PROMOTION_PATH=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" decide-path \
  "$TMP_DIR/decide-path-input.json")
CHATBOT_ONLY=false
[[ "$PROMOTION_PATH" == chatbot-only ]] && CHATBOT_ONLY=true

log_value "chatbot digest:" "$CHATBOT_IMAGE_DIGEST"
log_value "ETL digest:" "$ETL_IMAGE_DIGEST"
log_value "tokenizer:" "$TOKENIZER_REVISION"
log_value "artifact ID:" "$RETRIEVAL_ARTIFACT_ID"
log_value "promotion path:" "$([[ "$CHATBOT_ONLY" == true ]] && echo chatbot-only || echo full-retrieval)"

if [[ "$CHATBOT_ONLY" == true ]]; then
  CANDIDATE_SLOT="$ACTIVE_SLOT"
  CANDIDATE_KB_ID=$(jq -r .knowledge_base_id "$ACTIVE_BEFORE_FILE")
  CANDIDATE_DATA_SOURCE_ID=$(jq -r .data_source_id "$ACTIVE_BEFORE_FILE")
  QA_SOURCE_BUCKET=$(jq -r .raw_bucket "$ACTIVE_BEFORE_FILE")
  CANDIDATE_BUCKET=$(jq -r .processed_bucket "$ACTIVE_BEFORE_FILE")
  PROCESSED_PREFIX=$(jq -r .processed_prefix "$ACTIVE_BEFORE_FILE")
  BM25_KEY=$(jq -r .bm25_key "$ACTIVE_BEFORE_FILE")
  RAW_PREFIX=$(jq -r .raw_prefix "$ACTIVE_BEFORE_FILE")
  BLUE_ETL_IMAGE_DIGEST="$OUTGOING_ETL_IMAGE_DIGEST"
  GREEN_ETL_IMAGE_DIGEST="$OUTGOING_ETL_IMAGE_DIGEST"

  jq -n --slurpfile active "$ACTIVE_BEFORE_FILE" \
    --arg release "$RELEASE_ID" \
    --arg version "$CHATBOT_VERSION" \
    --arg digest "$CHATBOT_IMAGE_DIGEST" '
      {
        path: "chatbot-only",
        activeManifest: $active[0],
        inputs: {releaseId:$release, chatbotVersion:$version, chatbotImageDigest:$digest}
      }
    ' >"$TMP_DIR/build-manifest-input.json"
  node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" build-manifest \
    "$TMP_DIR/build-manifest-input.json" >"$OUTPUT_MANIFEST"

  if [[ "$DRY_RUN" == false ]]; then
    qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
    MANIFEST_KEY="retrieval-manifests/releases/${RELEASE_ID}.json"
    qa_retrieval_put_write_once "$CANDIDATE_BUCKET" "$MANIFEST_KEY" \
      "$OUTPUT_MANIFEST" application/json pinned
    qa_retrieval_assert_objects_pinned "$CANDIDATE_BUCKET" \
      "${PROCESSED_PREFIX}inventory.json" "$BM25_KEY" "$MANIFEST_KEY"
    qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"
  fi
else
  CANDIDATE_SLOT="$INACTIVE_SLOT"
  BLUE_ETL_IMAGE_DIGEST="$OUTGOING_ETL_IMAGE_DIGEST"
  GREEN_ETL_IMAGE_DIGEST="$OUTGOING_ETL_IMAGE_DIGEST"
  if [[ "$CANDIDATE_SLOT" == blue ]]; then
    BLUE_ETL_IMAGE_DIGEST="$ETL_IMAGE_DIGEST"
  else
    GREEN_ETL_IMAGE_DIGEST="$ETL_IMAGE_DIGEST"
  fi
  RAW_PREFIX="releases/${DATA_ARTIFACT_VERSION}/"
  PROCESSED_PREFIX="processed/releases/${RETRIEVAL_ARTIFACT_ID}/"
  BM25_KEY="bm25_index/releases/${RETRIEVAL_ARTIFACT_ID}/index.json"

  # #631/#619 raw corpus authority (rawSourceMode):
  #  - origin (qa): prefer THIS env's own durable write-once copy, read via the
  #    promotion role; fall back to dev (read via the dev/image-metadata reader)
  #    only on a coordinate's FIRST promotion. The env's own copy is durable
  #    (write-once, untagged bulk objects never expire) so a coordinate still
  #    pinned downstream can never fail to promote because dev's 90-day
  #    retention (#489) already expired it.
  #  - downstream (preprod): read ONLY from the upstream (QA) durable copy via
  #    the source-reader role — never self, never dev (#631). The upstream
  #    bucket name is discovered from the upstream's own coordinate parameter
  #    using that same role, so discovery never exceeds the entitlement.
  # A non-empty prefix is not "complete": a first promotion aborted mid-sync
  # can leave a truncated tree; qa_retrieval_composite_manifest_complete
  # verifies the declared file set against each pinned manifest_sha256.
  COMPOSITE_MANIFEST="$TMP_DIR/composite-manifest.json"
  if [[ "$RETRIEVAL_RAW_SOURCE_MODE" == downstream ]]; then
    # Resolve the upstream source bucket from the upstream's own coordinate
    # parameter, using the very role that entitles us to read the corpus. The
    # name is therefore never configured in CI: it cannot drift, and preprod
    # cannot be aimed at a bucket the upstream never sanctioned. Requires
    # ssm:GetParameter on that one parameter in the source-reader role
    # (renate/bootstrap accounts/qa/retrieval_source_reader.tf,
    # sid ReadPromotionCoordinates) — mirrors the dev reader's grant.
    qa_retrieval_assume_oidc "$RETRIEVAL_SOURCE_READER_ROLE_ARN" source-reader
    RAW_READ_BUCKET=$(aws ssm get-parameter \
      --name "$RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER" \
      --query Parameter.Value --output text 2>"$TMP_DIR/upstream-bucket.err") || {
      sed 's/^/  /' "$TMP_DIR/upstream-bucket.err" >&2 || true
      qa_retrieval_fail \
        "could not read ${RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER} from the" \
        "${RETRIEVAL_UPSTREAM_ENVIRONMENT} account with" \
        "${RETRIEVAL_SOURCE_READER_ROLE_ARN}; if this is AccessDenied the" \
        "source-reader role predates the ssm:GetParameter grant — apply" \
        "renate/bootstrap accounts/${RETRIEVAL_UPSTREAM_ENVIRONMENT}/retrieval_source_reader.tf;" \
        "see docs/architecture/runbooks/643-preprod-retrieval-promotion.md"
    }
    [[ -n "$RAW_READ_BUCKET" && "$RAW_READ_BUCKET" != "None" ]] || \
      qa_retrieval_fail \
        "${RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER} is empty in the" \
        "${RETRIEVAL_UPSTREAM_ENVIRONMENT} account; the upstream has not" \
        "published its source bucket coordinate"
    RAW_SOURCE="upstream"
    log_value "upstream source bucket:" "$RAW_READ_BUCKET (from ${RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER})"
    qa_retrieval_composite_manifest_complete \
      "$RAW_READ_BUCKET" "$RAW_PREFIX" "$COMPOSITE_MANIFEST" || \
      qa_retrieval_fail \
        "upstream raw release ${DATA_ARTIFACT_VERSION} is absent or incomplete in" \
        "s3://${RAW_READ_BUCKET}/${RAW_PREFIX}; downstream promotion sources only from QA (#631)"
    log_value "raw corpus source:" "$RAW_SOURCE"
    jq -e --arg coordinate "$DATA_ARTIFACT_VERSION" '
      .schema_version == 1 and .coordinate == $coordinate
      and (.components.brochure.bucket | type == "string" and length > 0)
      and .components.brochure.bucket == .components.faq.bucket
      and (.components.brochure.prefix | startswith("releases/"))
      and (.components.faq.prefix | startswith("releases/faq/"))
    ' "$COMPOSITE_MANIFEST" >/dev/null || qa_retrieval_fail "invalid composite data manifest"
  else
    qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
    SELF_SOURCE_BUCKET=$(qa_retrieval_required_ssm "/${ENV}/renate/etl-source-bucket-name")
    RAW_SOURCE="dev"
    if qa_retrieval_composite_manifest_complete \
        "$SELF_SOURCE_BUCKET" "$RAW_PREFIX" "$COMPOSITE_MANIFEST"; then
      RAW_SOURCE="self"
      RAW_READ_BUCKET="$SELF_SOURCE_BUCKET"
    else
      self_completeness_status=$?
      [[ "$self_completeness_status" -le 1 ]] || \
        qa_retrieval_fail "could not inspect existing ${ENV} raw release for ${DATA_ARTIFACT_VERSION}"
    fi
    log_value "raw corpus source:" "$RAW_SOURCE"

    if [[ "$RAW_SOURCE" == self ]]; then
      # Composite manifest provenance: `.components.*.bucket` still names the
      # ORIGIN (dev) bucket the coordinate was first promoted from — it is not
      # a fetch target here. Assert internal coherence (both components share
      # one origin) instead of equality against the bucket we are reading from.
      jq -e --arg coordinate "$DATA_ARTIFACT_VERSION" '
        .schema_version == 1 and .coordinate == $coordinate
        and (.components.brochure.bucket | type == "string" and length > 0)
        and .components.brochure.bucket == .components.faq.bucket
        and (.components.brochure.prefix | startswith("releases/"))
        and (.components.faq.prefix | startswith("releases/faq/"))
      ' "$COMPOSITE_MANIFEST" >/dev/null || qa_retrieval_fail "invalid composite data manifest"
    else
      # First promotion (or a truncated prior attempt): dev remains a
      # non-authoritative cache, consulted only on this hop. Assert the
      # coordinate actually exists in dev before assuming its role/reading its
      # data. The self check above ran under the promotion role; re-assume the
      # dev reader before touching the dev bucket, or the sync fails
      # AccessDenied — the dev bucket policy grants no access to the env's
      # promotion role. See
      # docs/architecture/runbooks/492-atomic-qa-retrieval-promotion.md.
      qa_retrieval_assume_oidc "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN" dev
      RAW_READ_BUCKET="$DEV_SOURCE_BUCKET"
      if ! qa_retrieval_prefix_has_objects "$RAW_READ_BUCKET" "$RAW_PREFIX"; then
        dev_precheck_status=$?
        if [[ "$dev_precheck_status" -gt 1 ]]; then
          qa_retrieval_fail "could not inspect dev raw release ${DATA_ARTIFACT_VERSION}"
        fi
        qa_retrieval_fail \
          "dev raw release ${DATA_ARTIFACT_VERSION} not found (expired or never" \
          "published) and no complete copy exists in the ${ENV} source bucket; see" \
          "docs/architecture/runbooks/492-atomic-qa-retrieval-promotion.md" \
          "'QA raw corpus sourcing (#631)' for recovery guidance"
      fi
      aws s3 cp "s3://${RAW_READ_BUCKET}/${RAW_PREFIX}manifest.json" \
        "$COMPOSITE_MANIFEST" --only-show-errors
      jq -e --arg coordinate "$DATA_ARTIFACT_VERSION" --arg bucket "$RAW_READ_BUCKET" '
        .schema_version == 1 and .coordinate == $coordinate
        and .components.brochure.bucket == $bucket
        and .components.faq.bucket == $bucket
        and (.components.brochure.prefix | startswith("releases/"))
        and (.components.faq.prefix | startswith("releases/faq/"))
      ' "$COMPOSITE_MANIFEST" >/dev/null || qa_retrieval_fail "invalid composite data manifest"
    fi
  fi
  BROCHURE_PREFIX=$(jq -r .components.brochure.prefix "$COMPOSITE_MANIFEST")
  FAQ_PREFIX=$(jq -r .components.faq.prefix "$COMPOSITE_MANIFEST")
  aws s3 sync "s3://${RAW_READ_BUCKET}/${BROCHURE_PREFIX}" \
    "$TMP_DIR/dev-raw/brochure/" --only-show-errors
  aws s3 sync "s3://${RAW_READ_BUCKET}/${FAQ_PREFIX}" \
    "$TMP_DIR/dev-raw/faq/" --only-show-errors
  # #630 defect 1: a piped `find | grep -q` under `set -o pipefail` can report
  # a spurious failure — grep exits on the first match, SIGPIPE-killing find,
  # and pipefail then fails the whole pipeline even though a match existed.
  # `-print -quit` stops at the first hit with no pipe, so this is structurally
  # impossible.
  # New coordinates contain DITA XML plus structured Merkblatt Markdown (#501).
  # Keep PDF support so older immutable coordinates remain promotable with their
  # pinned pre-#501 ETL image.
  brochure_src=$(find "$TMP_DIR/dev-raw/brochure" -type f \
    \( -name '*.xml' -o -name '*.md' -o -name '*.pdf' -o -path '*/deletes/*' \) -print -quit)
  [[ -n "$brochure_src" ]] || \
    qa_retrieval_fail "brochure component contains no processable source"
  faq_src=$(find "$TMP_DIR/dev-raw/faq" -type f -name '*.html' -print -quit)
  [[ -n "$faq_src" ]] || \
    qa_retrieval_fail "FAQ component contains no HTML source"

  if [[ "$DRY_RUN" == true ]]; then
    log_section "Dry-run plan"
    log_value "would deploy ETL slot:" "$CANDIDATE_SLOT"
    log_value "would process data:" "$DATA_ARTIFACT_VERSION"
    log_value "would source raw corpus from:" "$RAW_SOURCE"
    log_value "would build artifact:" "$RETRIEVAL_ARTIFACT_ID"
    log_value "selectors:" "unchanged"

    # CDK path check: synthesize both stacks the transaction will deploy, with
    # the exact contexts the real jobs pass. A context or template error must
    # surface here, before approval — not after the lock is held and the ETL
    # candidate slot has already been mutated. Synth only; no AWS mutation, and
    # `cdk diff` is deliberately not run here because it requires the deploy
    # role this zero-write preflight does not assume.
    log_section "Dry-run CDK synth (${RETRIEVAL_ETL_STACK}, ${RETRIEVAL_CHATBOT_STACK})"
    (
      cd "$REPO_ROOT/cdk"
      npx cdk synth "$ETL_STACK" "$CHATBOT_STACK" --exclusively \
        --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
        --context "env=${ENV}" \
        --context "etlImageTag=${ETL_IMAGE_DIGEST}" \
        --context "retrievalCandidateSlot=${CANDIDATE_SLOT}" \
        --context "blueEtlImageTag=${BLUE_ETL_IMAGE_DIGEST}" \
        --context "greenEtlImageTag=${GREEN_ETL_IMAGE_DIGEST}" \
        --context "chatbotImageTag=${CHATBOT_IMAGE_DIGEST}" \
        >/dev/null
    ) || qa_retrieval_fail \
      "cdk synth failed for ${ETL_STACK}/${CHATBOT_STACK} with the exact" \
      "promotion contexts; the transaction would have failed after acquiring" \
      "the lock. No AWS resources changed"
    log_value "cdk synth:" "ok (both stacks, exact promotion contexts)"
    exit 0
  fi

  log_section "Deploy exact ETL image to inactive slot"
  qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
  (
    cd "$REPO_ROOT/cdk"
    npx cdk deploy "$ETL_STACK" \
      --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
      --context "env=${ENV}" \
      --context "etlImageTag=${ETL_IMAGE_DIGEST}" \
      --context "retrievalCandidateSlot=${CANDIDATE_SLOT}" \
      --context "blueEtlImageTag=${BLUE_ETL_IMAGE_DIGEST}" \
      --context "greenEtlImageTag=${GREEN_ETL_IMAGE_DIGEST}" \
      --require-approval never
  )

  CANDIDATE_BASE="${RETRIEVAL_BASE_PATH}/slots/${CANDIDATE_SLOT}"
  CANDIDATE_KB_ID=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/knowledge-base-id")
  CANDIDATE_DATA_SOURCE_ID=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/data-source-id")
  CANDIDATE_BUCKET=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/processed-bucket-name")
  CANDIDATE_BUILDER=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/bm25-builder-function-name")
  CANDIDATE_BM25_QUEUE=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/bm25-rebuild-queue-arn")
  CANDIDATE_BM25_DLQ=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/bm25-rebuild-dlq-arn")
  CANDIDATE_KB_SYNC=$(qa_retrieval_required_ssm "${CANDIDATE_BASE}/kb-sync-function-name")
  QA_SOURCE_BUCKET=$(qa_retrieval_required_ssm "/${ENV}/renate/etl-source-bucket-name")
  QA_TRANSFORM_QUEUE=$(qa_retrieval_required_ssm "/${ENV}/renate/etl-queue-arn")
  QA_TRANSFORM_DLQ=$(qa_retrieval_required_ssm "/${ENV}/renate/etl-dlq-arn")

  [[ "$(aws lambda get-function --function-name "$CANDIDATE_BUILDER" \
    --query Code.ResolvedImageUri --output text)" == *@"$ETL_IMAGE_DIGEST" ]] || \
    qa_retrieval_fail "candidate BM25 builder does not run pinned ETL digest"
  qa_retrieval_assert_queue_empty "$QA_TRANSFORM_QUEUE" "QA transform queue"
  qa_retrieval_assert_queue_empty "$QA_TRANSFORM_DLQ" "QA transform DLQ"
  qa_retrieval_assert_queue_empty "$CANDIDATE_BM25_QUEUE" "candidate BM25 queue"
  qa_retrieval_assert_queue_empty "$CANDIDATE_BM25_DLQ" "candidate BM25 DLQ"
  qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"

  if [[ -s "$PREVIOUS_BEFORE_FILE" ]]; then
    jq -n --slurpfile previous "$PREVIOUS_BEFORE_FILE" \
      --arg kbId "$CANDIDATE_KB_ID" --arg bucket "$CANDIDATE_BUCKET" '
        {previousManifest: $previous[0], candidate: {candidateKbId:$kbId, candidateBucket:$bucket}}
      ' >"$TMP_DIR/arm-recovery-input.json"
  else
    jq -n --arg kbId "$CANDIDATE_KB_ID" --arg bucket "$CANDIDATE_BUCKET" '
      {previousManifest: null, candidate: {candidateKbId:$kbId, candidateBucket:$bucket}}
    ' >"$TMP_DIR/arm-recovery-input.json"
  fi
  # #630: the recovery-arming DECISION runs and is fully parsed before any
  # live mutation below (CANDIDATE_LIVE_MUTATED=true) is set. armRecovery
  # never throws for the normal no-previous/different-slot cases (it returns
  # {armed:false}); a node/parse failure here aborts under set -e, closed,
  # before any AWS write.
  RECOVERY_JSON=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" arm-recovery \
    "$TMP_DIR/arm-recovery-input.json")
  RECOVERY_ARMED=$(jq -r .armed <<<"$RECOVERY_JSON")
  if [[ "$RECOVERY_ARMED" == true ]]; then
    RECOVERY_BUCKET=$(jq -r .bucket <<<"$RECOVERY_JSON")
    RECOVERY_PREFIX=$(jq -r .prefix <<<"$RECOVERY_JSON")
    RECOVERY_KB_ID=$(jq -r .kbId <<<"$RECOVERY_JSON")
    RECOVERY_DATA_SOURCE_ID=$(jq -r .dataSourceId <<<"$RECOVERY_JSON")
  fi

  log_section "Process pinned raw corpus into inactive live prefix"
  if [[ "$RECOVERY_ARMED" == true ]]; then
    log_section "Signal degraded-rollback window"
    qa_retrieval_set_rollback_degraded_marker \
      "$RELEASE_ID" "$CANDIDATE_SLOT" "${CI_JOB_URL:-local}" "${CI_PIPELINE_URL:-local}"
    log_value "rollback-degraded:" "SET (fast #493 rollback unavailable until activation)"
    log_value "marker release:" "$RELEASE_ID"
  fi
  CANDIDATE_LIVE_MUTATED=true
  aws s3 rm "s3://${CANDIDATE_BUCKET}/docs/" --recursive --only-show-errors
  START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  TRANSFORM_DLQ_BASELINE=$(qa_retrieval_queue_depth "$QA_TRANSFORM_DLQ")
  BM25_DLQ_BASELINE=$(qa_retrieval_queue_depth "$CANDIDATE_BM25_DLQ")
  qa_retrieval_put_write_once "$QA_SOURCE_BUCKET" \
    "${RAW_PREFIX}manifest.json" "$COMPOSITE_MANIFEST" application/json pinned
  BROCHURE_ALREADY_PRESENT=false
  FAQ_ALREADY_PRESENT=false
  if qa_retrieval_prefix_has_objects "$QA_SOURCE_BUCKET" "$BROCHURE_PREFIX"; then
    BROCHURE_ALREADY_PRESENT=true
  elif [[ "$?" -ne 1 ]]; then
    qa_retrieval_fail "could not inspect existing raw brochure component"
  fi
  if qa_retrieval_prefix_has_objects "$QA_SOURCE_BUCKET" "$FAQ_PREFIX"; then
    FAQ_ALREADY_PRESENT=true
  elif [[ "$?" -ne 1 ]]; then
    qa_retrieval_fail "could not inspect existing raw FAQ component"
  fi
  qa_retrieval_sync_tree_write_once "$TMP_DIR/dev-raw/brochure" \
    "$QA_SOURCE_BUCKET" "$BROCHURE_PREFIX" "raw brochure component"
  qa_retrieval_sync_tree_write_once "$TMP_DIR/dev-raw/faq" \
    "$QA_SOURCE_BUCKET" "$FAQ_PREFIX" "raw FAQ component"
  qa_retrieval_set_object_retention "$QA_SOURCE_BUCKET" \
    "${BROCHURE_PREFIX}manifest.json" pinned
  qa_retrieval_set_object_retention "$QA_SOURCE_BUCKET" \
    "${FAQ_PREFIX}manifest.json" pinned
  if [[ "$BROCHURE_ALREADY_PRESENT" == true ]]; then
    qa_retrieval_replay_tree "$TMP_DIR/dev-raw/brochure" \
      "$QA_SOURCE_BUCKET" "$BROCHURE_PREFIX" \
      "${RETRIEVAL_ARTIFACT_ID}-${CI_JOB_ID:-local}" "raw brochure component"
  fi
  if [[ "$FAQ_ALREADY_PRESENT" == true ]]; then
    qa_retrieval_replay_tree "$TMP_DIR/dev-raw/faq" \
      "$QA_SOURCE_BUCKET" "$FAQ_PREFIX" \
      "${RETRIEVAL_ARTIFACT_ID}-${CI_JOB_ID:-local}" "raw FAQ component"
  fi

  "${SCRIPT_DIR}/../verify/etl-readiness-check.sh" \
    --transform-queue-arn "$QA_TRANSFORM_QUEUE" \
    --transform-dlq-arn "$QA_TRANSFORM_DLQ" \
    --bm25-queue-arn "$CANDIDATE_BM25_QUEUE" \
    --bm25-dlq-arn "$CANDIDATE_BM25_DLQ" \
    --knowledge-base-id "$CANDIDATE_KB_ID" \
    --data-source-id "$CANDIDATE_DATA_SOURCE_ID" \
    --start-ts "$START_TS" \
    --transform-dlq-baseline "$TRANSFORM_DLQ_BASELINE" \
    --bm25-dlq-baseline "$BM25_DLQ_BASELINE" \
    --timeout-seconds "${QA_RETRIEVAL_TIMEOUT_SECONDS:-3600}"

  log_section "Freeze and verify candidate corpus"
  aws s3 sync "s3://${CANDIDATE_BUCKET}/docs/" \
    "$TMP_DIR/candidate-docs/" --only-show-errors
  node "${SCRIPT_DIR}/../lib/node/retrieval-release.mjs" inventory \
    "$TMP_DIR/candidate-docs" "$TMP_DIR/inventory.json"
  MARKDOWN_COUNT=$(jq -r .markdown_count "$TMP_DIR/inventory.json")
  qa_retrieval_sync_tree_write_once "$TMP_DIR/candidate-docs" \
    "$CANDIDATE_BUCKET" "${PROCESSED_PREFIX}docs/" "immutable processed corpus"
  qa_retrieval_put_write_once "$CANDIDATE_BUCKET" \
    "${PROCESSED_PREFIX}inventory.json" "$TMP_DIR/inventory.json" application/json pinned

  jq -n \
    --arg release "$RELEASE_ID" \
    --arg artifact "$RETRIEVAL_ARTIFACT_ID" \
    --arg fingerprint "$RETRIEVAL_ARTIFACT_FINGERPRINT" \
    --arg version "$CHATBOT_VERSION" \
    --arg data "$DATA_ARTIFACT_VERSION" \
    --arg etl "$ETL_VERSION" \
    --arg kb "$CANDIDATE_KB_ID" \
    --arg ds "$CANDIDATE_DATA_SOURCE_ID" \
    --arg raw_bucket "$QA_SOURCE_BUCKET" \
    --arg raw_prefix "$RAW_PREFIX" \
    --arg bucket "$CANDIDATE_BUCKET" \
    --arg processed_prefix "$PROCESSED_PREFIX" \
    --arg bm25_key "$BM25_KEY" \
    --arg tokenizer "$TOKENIZER_REVISION" \
    --arg etl_digest "$ETL_IMAGE_DIGEST" \
    --arg chatbot_digest "$CHATBOT_IMAGE_DIGEST" '
      {
        path: "full-retrieval",
        activeManifest: null,
        inputs: {
          releaseId:$release,
          retrievalArtifactId:$artifact,
          retrievalArtifactFingerprint:$fingerprint,
          chatbotVersion:$version,
          dataArtifactVersion:$data,
          etlVersion:$etl,
          candidateKbId:$kb,
          candidateDataSourceId:$ds,
          rawBucket:$raw_bucket,
          rawPrefix:$raw_prefix,
          candidateBucket:$bucket,
          processedPrefix:$processed_prefix,
          bm25Key:$bm25_key,
          tokenizerRevision:$tokenizer,
          etlImageDigest:$etl_digest,
          chatbotImageDigest:$chatbot_digest
        }
      }
    ' >"$TMP_DIR/build-manifest-input.json"
  node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" build-manifest \
    "$TMP_DIR/build-manifest-input.json" >"$OUTPUT_MANIFEST"

  log_section "Build and validate immutable BM25 index"
  jq -cn --slurpfile manifest "$OUTPUT_MANIFEST" \
    '{retrieval_manifest:$manifest[0]}' >"$TMP_DIR/builder-payload.json"
  aws lambda invoke --function-name "$CANDIDATE_BUILDER" \
    --cli-binary-format raw-in-base64-out \
    --payload "fileb://${TMP_DIR}/builder-payload.json" \
    --cli-read-timeout 900 "$TMP_DIR/builder-response.json" \
    --output json >"$TMP_DIR/builder-invoke.json"
  [[ "$(jq -r '.FunctionError // empty' "$TMP_DIR/builder-invoke.json")" == "" ]] || {
    cat "$TMP_DIR/builder-response.json" >&2
    qa_retrieval_fail "candidate BM25 builder returned FunctionError"
  }
  jq -e --arg artifact "$RETRIEVAL_ARTIFACT_ID" --argjson count "$MARKDOWN_COUNT" '
    .RetrievalArtifactId == $artifact and .NumChunks == $count
  ' "$TMP_DIR/builder-response.json" >/dev/null || qa_retrieval_fail "BM25 builder count or artifact mismatch"
  aws s3 cp "s3://${CANDIDATE_BUCKET}/${BM25_KEY}" \
    "$TMP_DIR/index.json" --only-show-errors
  jq -e --arg artifact "$RETRIEVAL_ARTIFACT_ID" --arg tokenizer "$TOKENIZER_REVISION" \
    --argjson count "$MARKDOWN_COUNT" '
      .schema_version == 2 and .retrieval_artifact_id == $artifact
      and .bm25_tokenizer_revision == $tokenizer
      and (.corpus | length) == $count
      and (.chunk_ids | length) == $count
      and (.chunk_contents | length) == $count
      and (.chunk_metadata | length) == $count
    ' "$TMP_DIR/index.json" >/dev/null || qa_retrieval_fail "immutable BM25 index failed compatibility validation"
  qa_retrieval_set_object_retention "$CANDIDATE_BUCKET" "$BM25_KEY" pinned

  MANIFEST_KEY="retrieval-manifests/releases/${RELEASE_ID}.json"
  qa_retrieval_put_write_once "$CANDIDATE_BUCKET" "$MANIFEST_KEY" \
    "$OUTPUT_MANIFEST" application/json pinned
  # The immutable raw and processed trees are uploaded without an explicit
  # retention tag. The lifecycle rules match only `unpinned`, so those bulk
  # objects are fail-safe without thousands of per-object tag calls. Pin and
  # verify the small control set that identifies and inventories both trees.
  qa_retrieval_assert_objects_pinned "$QA_SOURCE_BUCKET" \
    "${RAW_PREFIX}manifest.json" \
    "${BROCHURE_PREFIX}manifest.json" \
    "${FAQ_PREFIX}manifest.json"
  qa_retrieval_assert_objects_pinned "$CANDIDATE_BUCKET" \
    "${PROCESSED_PREFIX}inventory.json" "$BM25_KEY" "$MANIFEST_KEY"
  qa_retrieval_assert_queue_empty "$QA_TRANSFORM_DLQ" "QA transform DLQ"
  qa_retrieval_assert_queue_empty "$CANDIDATE_BM25_DLQ" "candidate BM25 DLQ"
  qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"
fi

qa_retrieval_validate_manifest "$OUTPUT_MANIFEST"
cat >"$OUTPUT_ENV" <<EOF
CHATBOT_VERSION=${CHATBOT_VERSION}
DATA_ARTIFACT_VERSION=${DATA_ARTIFACT_VERSION}
ETL_VERSION=${ETL_VERSION}
RELEASE_ID=${RELEASE_ID}
RETRIEVAL_ARTIFACT_ID=${RETRIEVAL_ARTIFACT_ID}
RETRIEVAL_ARTIFACT_FINGERPRINT=${RETRIEVAL_ARTIFACT_FINGERPRINT}
TOKENIZER_REVISION=${TOKENIZER_REVISION}
CHATBOT_IMAGE_DIGEST=${CHATBOT_IMAGE_DIGEST}
ETL_IMAGE_DIGEST=${ETL_IMAGE_DIGEST}
OUTGOING_CHATBOT_IMAGE_DIGEST=${OUTGOING_CHATBOT_IMAGE_DIGEST}
OUTGOING_ETL_IMAGE_DIGEST=${OUTGOING_ETL_IMAGE_DIGEST}
ACTIVE_SLOT=${ACTIVE_SLOT}
CANDIDATE_SLOT=${CANDIDATE_SLOT}
BLUE_ETL_IMAGE_DIGEST=${BLUE_ETL_IMAGE_DIGEST}
GREEN_ETL_IMAGE_DIGEST=${GREEN_ETL_IMAGE_DIGEST}
CHATBOT_ONLY=${CHATBOT_ONLY}
CANDIDATE_BUCKET=${CANDIDATE_BUCKET}
PROCESSED_PREFIX=${PROCESSED_PREFIX}
BM25_KEY=${BM25_KEY}
EOF

echo
echo "${ENV} candidate ${RELEASE_ID} is ready; selectors remain unchanged."
