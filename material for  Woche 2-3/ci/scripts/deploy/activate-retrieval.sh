#!/usr/bin/env bash
# Atomically activate a ready manifest, verify all retrieval modes, and roll
# back on failure. Environment-parameterized (#643): selectors, chatbot stack,
# promotion role, image-tag parameters, smoke, and diagnostic source tag come
# from retrieval-environment.mjs so the same code serves qa and preprod.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: activate-retrieval.sh <qa|preprod|prod>}"

# shellcheck source=../lib/qa-retrieval-common.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-common.sh"
# shellcheck source=../lib/qa-retrieval-auth.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-auth.sh"
# shellcheck source=../lib/qa-retrieval-polling.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-polling.sh"
# shellcheck source=../lib/qa-retrieval-s3.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-s3.sh"
# shellcheck source=../lib/qa-retrieval-validation.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-validation.sh"
qa_retrieval_init_env "$ENV"

CANDIDATE_ENV="${CANDIDATE_ENV:-${REPO_ROOT}/${ENV}-candidate.env}"
CANDIDATE_MANIFEST="${CANDIDATE_MANIFEST:-${REPO_ROOT}/${ENV}-candidate-manifest.json}"
ACTIVE_BEFORE_FILE="${ACTIVE_BEFORE_FILE:-${REPO_ROOT}/${ENV}-active-before.json}"
PREVIOUS_BEFORE_FILE="${PREVIOUS_BEFORE_FILE:-${REPO_ROOT}/${ENV}-previous-before.json}"
CHATBOT_STACK="$RETRIEVAL_CHATBOT_STACK"
ACTIVE_SELECTOR="$RETRIEVAL_ACTIVE_SELECTOR"
PREVIOUS_SELECTOR="$RETRIEVAL_PREVIOUS_SELECTOR"
IMAGE_TAG_PARAM="/${ENV}/renate/image-tag"
IMAGE_TAG_PREVIOUS_PARAM="/${ENV}/renate/image-tag-previous"
RTO_SECONDS="${QA_RETRIEVAL_RTO_SECONDS:-120}"

for required in "$CANDIDATE_ENV" "$CANDIDATE_MANIFEST" "$ACTIVE_BEFORE_FILE"; do
  [[ -f "$required" ]] || { echo "Missing ${required}" >&2; exit 1; }
done
# shellcheck disable=SC1090
source "$CANDIDATE_ENV"
: "${OUTGOING_CHATBOT_IMAGE_DIGEST:?candidate evidence lacks outgoing chatbot digest}"
: "${OUTGOING_ETL_IMAGE_DIGEST:?candidate evidence lacks outgoing ETL digest}"

qa_retrieval_validate_manifest "$CANDIDATE_MANIFEST"
qa_retrieval_validate_manifest "$ACTIVE_BEFORE_FILE"
OLD_CHATBOT_VERSION=$(jq -r .version "$ACTIVE_BEFORE_FILE")
OLD_SCHEMA_VERSION=$(jq -r .schema_version "$ACTIVE_BEFORE_FILE")
OLD_RELEASE_ID=$(jq -r .release_id "$ACTIVE_BEFORE_FILE")
OLD_PROCESSED_BUCKET=$(jq -r .processed_bucket "$ACTIVE_BEFORE_FILE")
OLD_PROCESSED_PREFIX=$(jq -r .processed_prefix "$ACTIVE_BEFORE_FILE")
OLD_BM25_KEY=$(jq -r .bm25_key "$ACTIVE_BEFORE_FILE")
OLD_CONTROL_KEYS=("${OLD_PROCESSED_PREFIX}inventory.json" "$OLD_BM25_KEY")
if [[ "$OLD_SCHEMA_VERSION" -ge 3 ]]; then
  OLD_CONTROL_KEYS+=("retrieval-manifests/releases/${OLD_RELEASE_ID}.json")
fi

qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"
OLD_IMAGE_POINTER=$(qa_retrieval_optional_ssm "$IMAGE_TAG_PARAM" || true)
OLD_IMAGE_PREVIOUS=$(qa_retrieval_optional_ssm "$IMAGE_TAG_PREVIOUS_PARAM" || true)

CHAT_FUNCTION=$(qa_retrieval_resolve_chat_function "$CHATBOT_STACK" "$ACTIVE_SELECTOR")

restore_parameter() {
  local name="$1" file="$2"
  if [[ -s "$file" ]]; then
    aws ssm put-parameter --name "$name" --type String \
      --value "file://${file}" --overwrite >/dev/null
  else
    aws ssm delete-parameter --name "$name" >/dev/null 2>&1 || true
  fi
}

rollback() {
  local trap_rc=$?
  local original_rc="${1:-$trap_rc}"
  trap - ERR
  set +e
  echo "${ENV} retrieval activation failed; restoring the previous coherent release." >&2
  restore_parameter "$ACTIVE_SELECTOR" "$ACTIVE_BEFORE_FILE"
  restore_parameter "$PREVIOUS_SELECTOR" "$PREVIOUS_BEFORE_FILE"

  (
    cd "$REPO_ROOT/cdk"
    npx cdk deploy "$CHATBOT_STACK" \
      --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
      --context "env=${ENV}" \
      --context "etlImageTag=${OUTGOING_ETL_IMAGE_DIGEST}" \
      --context "retrievalCandidateSlot=${ACTIVE_SLOT}" \
      --context "blueEtlImageTag=${OUTGOING_ETL_IMAGE_DIGEST}" \
      --context "greenEtlImageTag=${OUTGOING_ETL_IMAGE_DIGEST}" \
      --context "chatbotImageTag=${OUTGOING_CHATBOT_IMAGE_DIGEST}" \
      --require-approval never
  )
  chatbot_rollback_rc=$?

  if [[ -n "$OLD_IMAGE_POINTER" ]]; then
    aws ssm put-parameter --name "$IMAGE_TAG_PARAM" --type String \
      --value "$OLD_IMAGE_POINTER" --overwrite >/dev/null
  fi
  if [[ -n "$OLD_IMAGE_PREVIOUS" ]]; then
    aws ssm put-parameter --name "$IMAGE_TAG_PREVIOUS_PARAM" --type String \
      --value "$OLD_IMAGE_PREVIOUS" --overwrite >/dev/null
  else
    aws ssm delete-parameter --name "$IMAGE_TAG_PREVIOUS_PARAM" >/dev/null 2>&1 || true
  fi
  if [[ "$chatbot_rollback_rc" -ne 0 ]]; then
    echo "CRITICAL: selector rollback succeeded but chatbot code rollback failed." >&2
  else
    echo "Rollback complete: ${OLD_CHATBOT_VERSION} + $(jq -r .release_id "$ACTIVE_BEFORE_FILE")" >&2
  fi
  exit "$original_rc"
}
trap rollback ERR

echo "Verifying outgoing and incoming rollback artifacts are protected..."
qa_retrieval_assert_objects_pinned "$OLD_PROCESSED_BUCKET" "${OLD_CONTROL_KEYS[@]}"
qa_retrieval_assert_objects_pinned "$CANDIDATE_BUCKET" \
  "${PROCESSED_PREFIX}inventory.json" \
  "$BM25_KEY" \
  "retrieval-manifests/releases/${RELEASE_ID}.json"
qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"

CANDIDATE_RELEASE_ID=$(jq -r .release_id "$CANDIDATE_MANIFEST")

# #671 invariant: `previous-manifest` must name the release we can roll back
# to, which by definition differs from the currently active one. A config-only
# promotion (no version/data/etl bump) reaches this script with a candidate
# whose release_id already equals the active release_id -- there is nothing to
# rotate into previous. Rotating anyway copies active into previous and
# destroys the invariant, tripping assert-prod-retrieval-monitoring-ready on
# every subsequent prod pipeline. So we skip the previous-manifest rotation
# and the release-convergence wait when the release itself is unchanged.
#
# release_id only hashes version/data_artifact_version/etl_version, so a
# candidate manifest can still differ from the active one in other fields
# (bucket/prefix, bm25 key, chatbot image digest, ...) even when release_id
# matches -- e.g. a genuine config-only change. That content, and the
# image-tag pointers (which track CHATBOT_VERSION, not release_id), are
# refreshed independently below so a config-only promotion isn't silently
# dropped.
RELEASE_UNCHANGED=false
if [[ "$CANDIDATE_RELEASE_ID" == "$OLD_RELEASE_ID" ]]; then
  RELEASE_UNCHANGED=true
  echo "Candidate release ${CANDIDATE_RELEASE_ID} equals the currently active release; previous-manifest rotation and convergence wait are a no-op."
else
  # #630: selector write ORDER is a decision (previous-first for activation --
  # the CURRENT active value is already known-good, so if the script dies
  # between the two writes, active still names the old good release and only
  # previous lags). The plan is decided in Node; Bash executes the SSM writes
  # in the returned order.
  SELECTOR_WORKDIR=$(mktemp -d)
  jq -n --arg active "$ACTIVE_SELECTOR" --arg previous "$PREVIOUS_SELECTOR" \
    --arg newActive "$CANDIDATE_MANIFEST" --arg newPrevious "$ACTIVE_BEFORE_FILE" '
      {
        kind: "activate",
        selectors: {
          activeSelector: $active,
          previousSelector: $previous,
          newActiveFile: $newActive,
          newPreviousFile: $newPrevious
        }
      }
    ' >"${SELECTOR_WORKDIR}/selector-transition-input.json"
  node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" selector-transition \
    "${SELECTOR_WORKDIR}/selector-transition-input.json" >"${SELECTOR_WORKDIR}/plan.json"
  while IFS=$'\t' read -r selector_name selector_value_file; do
    aws ssm put-parameter --name "$selector_name" --type String \
      --value "file://${selector_value_file}" --overwrite >/dev/null
  done < <(jq -r '.[] | [.name, .valueFile] | @tsv' "${SELECTOR_WORKDIR}/plan.json")
  rm -rf "$SELECTOR_WORKDIR"

  qa_retrieval_wait_for_release_convergence \
    "$CHAT_FUNCTION" "$RELEASE_ID" "${ENV}-retrieval-promotion" "$RTO_SECONDS" \
    || rollback "$?"

  ACTIVE_NOW=$(qa_retrieval_required_ssm "$ACTIVE_SELECTOR")
  PREVIOUS_NOW=$(qa_retrieval_required_ssm "$PREVIOUS_SELECTOR")
  cmp -s <(printf '%s\n' "$ACTIVE_NOW") "$CANDIDATE_MANIFEST" || \
    qa_retrieval_fail "active selector read-back differs from candidate manifest"
  cmp -s <(printf '%s\n' "$PREVIOUS_NOW") "$ACTIVE_BEFORE_FILE" || \
    qa_retrieval_fail "previous selector read-back differs from outgoing manifest"
fi

if [[ "$RELEASE_UNCHANGED" == true ]] && ! cmp -s "$CANDIDATE_MANIFEST" "$ACTIVE_BEFORE_FILE"; then
  echo "Candidate manifest content differs from active (release_id unchanged); refreshing active-manifest selector."
  aws ssm put-parameter --name "$ACTIVE_SELECTOR" --type String \
    --value "file://${CANDIDATE_MANIFEST}" --overwrite >/dev/null
  ACTIVE_NOW=$(qa_retrieval_required_ssm "$ACTIVE_SELECTOR")
  cmp -s <(printf '%s\n' "$ACTIVE_NOW") "$CANDIDATE_MANIFEST" || \
    qa_retrieval_fail "active selector read-back differs from candidate manifest"
fi

if [[ "$CHATBOT_VERSION" != "$OLD_CHATBOT_VERSION" ]]; then
  aws ssm put-parameter --name "$IMAGE_TAG_PREVIOUS_PARAM" --type String \
    --value "$OLD_CHATBOT_VERSION" --overwrite >/dev/null
  aws ssm put-parameter --name "$IMAGE_TAG_PARAM" --type String \
    --value "$CHATBOT_VERSION" --overwrite >/dev/null
fi

# Existing public health/frontend smoke remains part of the transaction.
"${SCRIPT_DIR}/../verify/smoke-eval-${ENV}.sh"
# The qa-deployed-<triple> attestation tag is a QA-only concept (#560): it lets
# downstream (preprod/prod) verify a triple was smoke-tested on qa. Preprod's
# own downstream attestation is out of scope for #643.
if [[ "$ENV" == qa ]]; then
  "${SCRIPT_DIR}/../release/push-qa-deployed-tag.sh"
fi

trap - ERR

# #628: the entire activation transaction (selector swap, read-back
# verification, image-tag writes, smoke-eval, deployed-tag push) has now
# succeeded — the candidate slot's corpus is live and the outgoing slot
# becomes the new, intact rollback target. Clear the degraded-rollback marker.
# Best-effort/fail-safe: a failed clear leaves it set (false alarm) and must
# not fail this already-healthy activation.
qa_retrieval_clear_rollback_degraded_marker

# Stale retention cleanup is owned by the RFC-0021 retrieval-reconciliation
# Lambda in renate/scheduled-jobs, which pins active/previous and unpins
# everything else stale on a daily cadence (02:00 UTC). This keeps the
# promotion transaction free of best-effort corpus mutation.
if [[ -s "$PREVIOUS_BEFORE_FILE" ]]; then
  echo "Deferred stale retrieval retention cleanup to the RFC-0021 Lambda; active and rollback artifacts remain protected." >&2
fi

if [[ "$RELEASE_UNCHANGED" == true ]]; then
  echo "Activated ${ENV} retrieval release ${RELEASE_ID} (config-only; release unchanged, previous-manifest left unchanged)."
else
  echo "Activated ${ENV} retrieval release ${RELEASE_ID}; previous is $(jq -r .release_id "$ACTIVE_BEFORE_FILE")."
fi
