#!/usr/bin/env bash
# #493 — Standalone operator rollback for the hybrid retrieval selector.
# Environment-parameterized (#643): selectors, chatbot stack, promotion role,
# degraded marker, and diagnostic source tag come from
# retrieval-environment.mjs so the same code serves qa and preprod.
#
# Unlike activate-retrieval.sh's ERR trap (which only fires on a failed
# activation), this script is triggered independently: a bad release passed
# activation diagnostics but is discovered later in normal use. It rolls back
# retrieval ONLY — no CDK deploy, no rebuild, no Lambda restart. If the
# chatbot application code itself also needs rollback, use the existing
# /<env>/renate/image-tag-previous + CDK deploy procedure separately; see the
# coherence gate below for why this script refuses to paper over that case.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: rollback-retrieval.sh <qa|preprod|prod>}"

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

CHATBOT_STACK="$RETRIEVAL_CHATBOT_STACK"
ACTIVE_SELECTOR="$RETRIEVAL_ACTIVE_SELECTOR"
PREVIOUS_SELECTOR="$RETRIEVAL_PREVIOUS_SELECTOR"
RTO_SECONDS="${QA_RETRIEVAL_RTO_SECONDS:-120}"
DRY_RUN="${DRY_RUN:-false}"
FORCE="${FORCE:-false}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

[[ "$DRY_RUN" == true || "$DRY_RUN" == false ]] || qa_retrieval_fail "DRY_RUN must be true or false"
[[ "$FORCE" == true || "$FORCE" == false ]] || qa_retrieval_fail "FORCE must be true or false"

# --- 1. Auth ---------------------------------------------------------------
# CI runs with GITLAB_OIDC_TOKEN and assumes the promotion role. An operator
# workstation has no OIDC token and instead relies on its own SSO/profile
# credentials (already exported into the environment) — do not attempt OIDC.
if [[ -n "${GITLAB_OIDC_TOKEN:-}" ]]; then
  qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" retrieval-rollback
  echo "Authenticated via OIDC role ${RETRIEVAL_PROMOTION_ROLE_ARN}." >&2
else
  aws sts get-caller-identity --output json >/dev/null || \
    qa_retrieval_fail "no GITLAB_OIDC_TOKEN and no usable AWS credentials on this workstation"
  echo "Authenticated via existing AWS credentials (workstation path)." >&2
fi

# --- 2. Concurrency ----------------------------------------------------------
# In CI this job shares the env's deploy resource_group with activation, so
# GitLab itself serializes the two. On a workstation there is no such lock; the
# best available guard is re-checking the selectors immediately before the
# write (step 7) and refusing if they moved. Warn up front regardless.
echo "Do NOT run this while a ${ENV} promotion/activation pipeline is in progress." >&2
echo "(CI serializes via resource_group: ${RETRIEVAL_RESOURCE_GROUP}; on a workstation, check the pipeline list yourself.)" >&2

# --- 3. Capture --------------------------------------------------------------
ACTIVE_BEFORE_FILE="${WORKDIR}/active-before.json"
PREVIOUS_BEFORE_FILE="${WORKDIR}/previous-before.json"
qa_retrieval_capture_selector "$ACTIVE_SELECTOR" "$ACTIVE_BEFORE_FILE"
qa_retrieval_capture_selector "$PREVIOUS_SELECTOR" "$PREVIOUS_BEFORE_FILE"
[[ -s "$ACTIVE_BEFORE_FILE" ]] || qa_retrieval_fail "no active retrieval manifest is configured; nothing to roll back"
[[ -s "$PREVIOUS_BEFORE_FILE" ]] || qa_retrieval_fail "no previous retrieval manifest is configured; nothing to roll back to"

qa_retrieval_validate_manifest "$ACTIVE_BEFORE_FILE"
qa_retrieval_validate_manifest "$PREVIOUS_BEFORE_FILE"

BAD_RELEASE_ID=$(jq -r .release_id "$ACTIVE_BEFORE_FILE")
TARGET_RELEASE_ID=$(jq -r .release_id "$PREVIOUS_BEFORE_FILE")
BAD_TOKENIZER=$(jq -r .bm25_tokenizer_revision "$ACTIVE_BEFORE_FILE")
TARGET_TOKENIZER=$(jq -r .bm25_tokenizer_revision "$PREVIOUS_BEFORE_FILE")
TARGET_SCHEMA_VERSION=$(jq -r .schema_version "$PREVIOUS_BEFORE_FILE")
TARGET_KB_ID=$(jq -r .knowledge_base_id "$PREVIOUS_BEFORE_FILE")
TARGET_PROCESSED_BUCKET=$(jq -r .processed_bucket "$PREVIOUS_BEFORE_FILE")
TARGET_PROCESSED_PREFIX=$(jq -r .processed_prefix "$PREVIOUS_BEFORE_FILE")
TARGET_BM25_KEY=$(jq -r .bm25_key "$PREVIOUS_BEFORE_FILE")

[[ "$BAD_RELEASE_ID" != "$TARGET_RELEASE_ID" ]] || \
  qa_retrieval_fail "active and previous manifests already name the same release ${BAD_RELEASE_ID}; nothing to roll back"

echo "Capture: active ${BAD_RELEASE_ID} , previous (rollback target) ${TARGET_RELEASE_ID}" >&2

# --- 3b. Degraded-rollback marker guard (#628) ------------------------------
# If a candidate build is currently overwriting the inactive slot's live corpus
# (exactly the slot previous-manifest names), this fast selector-only rollback
# would land on partially-ingested candidate content instead of the previous
# release — and nothing below (preflight's pin checks, the coherence gate, even
# a successful diagnostic poll) would catch that, because they only verify the
# still-pinned immutable control objects, not the live docs/ tree. Check before
# preflight/coherence/DRY_RUN so a dry run also reports this.
DEGRADED_MARKER_VALUE="$(qa_retrieval_optional_ssm "$RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER" || true)"
if [[ -n "$DEGRADED_MARKER_VALUE" && "$FORCE" != true ]]; then
  qa_retrieval_fail \
    "a candidate build is mutating the inactive slot; fast rollback is degraded." \
    "See the 493 runbook \u203a \"Rollback while a candidate build is running\"." \
    "A selector-only flip will not restore service right now." \
    "Re-run with FORCE=true only if you understand the restore is manual." \
    "Marker: ${DEGRADED_MARKER_VALUE}"
fi
[[ -z "$DEGRADED_MARKER_VALUE" ]] || \
  echo "WARNING: proceeding with FORCE=true while the degraded-rollback marker is set: ${DEGRADED_MARKER_VALUE}" >&2

# --- 4. Preflight ------------------------------------------------------------
TARGET_CONTROL_KEYS=("${TARGET_PROCESSED_PREFIX}inventory.json" "$TARGET_BM25_KEY")
if [[ "$TARGET_SCHEMA_VERSION" -ge 3 ]]; then
  TARGET_CONTROL_KEYS+=("retrieval-manifests/releases/${TARGET_RELEASE_ID}.json")
fi

echo "Preflight: verifying rollback target's KB and pinned control objects..." >&2
KB_CHECK_ERROR="${WORKDIR}/kb-check.err"
if ! aws bedrock-agent get-knowledge-base --knowledge-base-id "$TARGET_KB_ID" \
    --output json >/dev/null 2>"$KB_CHECK_ERROR"; then
  if grep -qi 'AccessDenied' "$KB_CHECK_ERROR"; then
    qa_retrieval_fail \
      "cannot verify rollback target Bedrock Knowledge Base ${TARGET_KB_ID}: access denied." \
      "The caller's role is missing bedrock-agent:GetKnowledgeBase (see #493 bootstrap" \
      "dependency renate/bootstrap!23) — this is an IAM problem, not evidence the KB is gone."
  elif grep -qi 'ResourceNotFound' "$KB_CHECK_ERROR"; then
    qa_retrieval_fail \
      "rollback target Bedrock Knowledge Base ${TARGET_KB_ID} does not exist (ResourceNotFoundException)."
  else
    cat "$KB_CHECK_ERROR" >&2
    qa_retrieval_fail "rollback target Bedrock Knowledge Base ${TARGET_KB_ID} check failed; see error above."
  fi
fi
qa_retrieval_assert_objects_pinned "$TARGET_PROCESSED_BUCKET" "${TARGET_CONTROL_KEYS[@]}"
echo "Preflight passed: rollback target ${TARGET_RELEASE_ID} is complete and pinned." >&2

# --- 5. Coherence gate (tokenizer) -------------------------------------------
# The running chatbot's tokenizer matches the currently active manifest's
# tokenizer (enforced at promotion time). A selector-only flip to a manifest
# with a DIFFERENT tokenizer would make the runtime's own compatibility check
# (_validate_runtime_compatibility) fail closed — i.e. this "rollback" would
# take retrieval down, not restore it. That combination needs a full
# application rollback (chatbot image + retrieval together), which is out of
# scope for this fast path.
jq -n --arg bad "$BAD_TOKENIZER" --arg target "$TARGET_TOKENIZER" \
  '{badTokenizer:$bad, targetTokenizer:$target}' >"${WORKDIR}/tokenizer-coherence-input.json"
if ! COHERENCE_JSON=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" tokenizer-coherence \
  "${WORKDIR}/tokenizer-coherence-input.json"); then
  echo "Coherence FAILED: $(jq -r .reason <<<"$COHERENCE_JSON")" >&2
  echo "ABORT: a selector-only rollback would fail closed at runtime. Use a full" >&2
  echo "application rollback (previous chatbot image + retrieval) instead." >&2
  exit 1
fi
echo "Coherence: tokenizer ${TARGET_TOKENIZER} matches the running release — OK." >&2

if [[ "$DRY_RUN" == true ]]; then
  echo "[DRY RUN] Preflight and coherence checks passed. Rollback is armed. No parameters written." >&2
  exit 0
fi

# --- 6. Confirmation guard (double-rollback) --------------------------------
# After one rollback, previous-manifest holds the bad release. An unconfirmed
# second run would silently roll FORWARD back onto it. Require the operator
# (or CI variable) to name the expected target explicitly.
if [[ -n "${GITLAB_OIDC_TOKEN:-}" ]]; then
  : "${EXPECTED_TARGET_RELEASE_ID:?EXPECTED_TARGET_RELEASE_ID is required in CI to confirm the rollback target}"
  jq -n --arg expected "$EXPECTED_TARGET_RELEASE_ID" --arg target "$TARGET_RELEASE_ID" \
    '{expected:$expected, target:$target}' >"${WORKDIR}/confirm-rollback-input.json"
  if ! CONFIRM_JSON=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" confirm-rollback-target \
    "${WORKDIR}/confirm-rollback-input.json"); then
    qa_retrieval_fail "$(jq -r .reason <<<"$CONFIRM_JSON")"
  fi
else
  echo "Confirm: roll back ${BAD_RELEASE_ID} -> ${TARGET_RELEASE_ID} ? [type the target release_id to proceed]" >&2
  read -r -p "> " typed_confirmation
  jq -n --arg expected "$typed_confirmation" --arg target "$TARGET_RELEASE_ID" \
    '{expected:$expected, target:$target}' >"${WORKDIR}/confirm-rollback-input.json"
  if ! CONFIRM_JSON=$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" confirm-rollback-target \
    "${WORKDIR}/confirm-rollback-input.json"); then
    qa_retrieval_fail "$(jq -r .reason <<<"$CONFIRM_JSON") ; aborting without changes"
  fi
fi

CHAT_FUNCTION=$(qa_retrieval_resolve_chat_function "$CHATBOT_STACK" "$ACTIVE_SELECTOR")

# --- 7. Swap — active first (crash-safe for the rollback direction) --------
# Mirrors, but does not repeat, activation's "previous first" order: on
# activation the CURRENT active value is already good, so writing previous
# first is safe. On rollback the CURRENT active value is the BAD release, so
# recovering active must happen first — if the script dies immediately after,
# the service is already healthy and only the forensic previous-write is
# incomplete (best-effort, does not fail the rollback).
qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"
echo "Swapping active -> previous manifest (previous kept for forensics)..." >&2
jq -n --arg active "$ACTIVE_SELECTOR" --arg previous "$PREVIOUS_SELECTOR" \
  --arg newActive "$PREVIOUS_BEFORE_FILE" --arg newPrevious "$ACTIVE_BEFORE_FILE" '
    {
      kind: "rollback",
      selectors: {
        activeSelector: $active,
        previousSelector: $previous,
        newActiveFile: $newActive,
        newPreviousFile: $newPrevious
      }
    }
  ' >"${WORKDIR}/selector-transition-input.json"
node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" selector-transition \
  "${WORKDIR}/selector-transition-input.json" >"${WORKDIR}/plan.json"
# First write (active, recovering the healthy release) must hard-fail the
# rollback; the second (previous, forensics-only) is best-effort per #493 —
# the service is already healthy once the first write lands.
FIRST_NAME=$(jq -r '.[0].name' "${WORKDIR}/plan.json")
FIRST_VALUE_FILE=$(jq -r '.[0].valueFile' "${WORKDIR}/plan.json")
SECOND_NAME=$(jq -r '.[1].name' "${WORKDIR}/plan.json")
SECOND_VALUE_FILE=$(jq -r '.[1].valueFile' "${WORKDIR}/plan.json")
aws ssm put-parameter --name "$FIRST_NAME" --type String \
  --value "file://${FIRST_VALUE_FILE}" --overwrite >/dev/null
if ! aws ssm put-parameter --name "$SECOND_NAME" --type String \
  --value "file://${SECOND_VALUE_FILE}" --overwrite >/dev/null; then
  echo "WARNING: active selector was restored to ${TARGET_RELEASE_ID}, but recording" >&2
  echo "the bad release ${BAD_RELEASE_ID} into previous-manifest failed. The service" >&2
  echo "is healthy; retry the previous-manifest write manually for forensics." >&2
fi

# --- 8. Verification ---------------------------------------------------------
echo "Verifying runtime convergence (RTO=${RTO_SECONDS}s)..." >&2
qa_retrieval_wait_for_release_convergence \
  "$CHAT_FUNCTION" "$TARGET_RELEASE_ID" "${ENV}-retrieval-rollback" "$RTO_SECONDS" "$WORKDIR"

ACTIVE_NOW=$(qa_retrieval_required_ssm "$ACTIVE_SELECTOR")
cmp -s <(printf '%s\n' "$ACTIVE_NOW") "$PREVIOUS_BEFORE_FILE" || \
  qa_retrieval_fail "active selector read-back differs from the rollback target"

# --- 9. Post-rollback pin check ---------------------------------------------
# The restored release's artifacts remain pinned (checked again for defense in
# depth). The bad release is left pinned too — this is forensics, not cleanup;
# retention reconciliation happens through the normal promotion/cleanup path.
qa_retrieval_assert_objects_pinned "$TARGET_PROCESSED_BUCKET" "${TARGET_CONTROL_KEYS[@]}"

echo "Rollback complete. Active release is now ${TARGET_RELEASE_ID} (was ${BAD_RELEASE_ID})." >&2
echo "The bad release ${BAD_RELEASE_ID} remains pinned in previous-manifest for forensics" >&2
echo "and forward re-activation. To restore it, re-run this script with the confirmation" >&2
echo "target set to ${BAD_RELEASE_ID} once the underlying issue is fixed or understood." >&2
