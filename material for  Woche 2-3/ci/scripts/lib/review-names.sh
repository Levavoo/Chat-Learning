#!/usr/bin/env bash
# Shared review-environment resource naming.
# Source this file after exporting CI_COMMIT_REF_SLUG.
# Sets: FUNC_PREFIX, MAX_SLUG_LEN, safe_slug(), SLUG, FUNC, API_NAME,
#       DDB_PREFIX, DDB_TABLE_DEFAULT
# shellcheck disable=SC2034  # variables used by callers

: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"

FUNC_PREFIX="renate-chat-review-"
MAX_SLUG_LEN=$((64 - ${#FUNC_PREFIX}))

safe_slug() {
  local slug="$1"
  if [ "${#slug}" -le "${MAX_SLUG_LEN}" ]; then
    printf '%s' "${slug}"
    return
  fi
  local hash
  hash=$(printf '%s' "${slug}" | sha256sum | cut -c1-8)
  local keep=$((MAX_SLUG_LEN - 9))
  printf '%s-%s' "${slug:0:keep}" "${hash}"
}

# review_langfuse_tag — compute a Langfuse-valid trace tag for this branch.
# Constraints: ^(?!langfuse)[a-z0-9-_]+$ and max 40 chars.
# "review-" prefix = 7 chars → 33 chars available for the slug portion.
review_langfuse_tag() {
  local slug
  slug=$(printf '%s' "${CI_COMMIT_REF_SLUG}" | tr -cd 'a-z0-9-_')
  local max_slug=33
  if [ "${#slug}" -le "${max_slug}" ]; then
    printf 'review-%s' "${slug}"
    return
  fi
  local hash
  hash=$(printf '%s' "${CI_COMMIT_REF_SLUG}" | sha256sum | cut -c1-8)
  local keep=$((max_slug - 9)) # 9 = "-" + 8 hash chars
  printf 'review-%s-%s' "${slug:0:keep}" "${hash}"
}

SLUG="$(safe_slug "${CI_COMMIT_REF_SLUG}")"
FUNC="${FUNC_PREFIX}${SLUG}"
API_NAME="review-${SLUG}"
DDB_PREFIX="review/${CI_COMMIT_REF_SLUG}#"
DDB_TABLE_DEFAULT="renate-conversations-dev"
# Disposable per-branch Cognito test user (created on deploy, deleted on cleanup).
# Must match the derivation in review-deploy-backend.sh / review-cleanup.sh.
REVIEW_TEST_USER="review-$(printf '%s' "${CI_COMMIT_REF_SLUG}" | sha256sum | cut -c1-12)@drv-bund.de"
# Langfuse trace tag for this branch (max 40 chars, Langfuse env regex compliant).
REVIEW_LANGFUSE_TAG="$(review_langfuse_tag)"
