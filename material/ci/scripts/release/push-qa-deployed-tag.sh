#!/usr/bin/env bash
set -euo pipefail
# push-qa-deployed-tag.sh
# Push a triple-specific qa-deployed-<version>--data-<data>--etl-<etl> tag on
# origin after a successful qa deploy + smoke-eval. Read by assert_pin_on_qa
# so preprod/prod can deploy an exact QA-tested rollback triple. See #560.
#
# Idempotent: silently skips if the tag already exists on origin.
# Hard-fail on push errors — a missing tag would silently block future
# preprod deploys of this version.
#
# Required CI variables: CI_SERVER_HOST, CI_PROJECT_PATH, CI_JOB_TOKEN

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

: "${CI_SERVER_HOST:?CI_SERVER_HOST is required}"
: "${CI_PROJECT_PATH:?CI_PROJECT_PATH is required}"
: "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"

QA_PIN="${REPO_ROOT}/deployments/qa/version.yaml"
validate_promotion_pin "$QA_PIN"
TAG=$(promotion_pin_attestation_tag "$QA_PIN")
# #643 D3 — also attest WHICH deployment implementation validated this triple.
# The triple proves the release inputs; this proves the retrieval CDK + CI
# implementation that exercised them, so a later change (including a #626
# stack-only one that moves no coordinate) cannot silently ride a stale
# QA attestation into preprod.
IMPL_TAG=$("${SCRIPT_DIR}/../validate/retrieval-implementation-fingerprint.sh" --tag)
ORIGIN_URL="https://gitlab-ci-token:${CI_JOB_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"

# Lightweight tags (no `-m`, no metadata object): the consumers
# (assert_pin_on_qa, prepare-retrieval-promotion.sh) only check ref existence
# via `git ls-remote --exit-code`, so a message is dead weight. Lightweight
# tags also avoid needing a git identity (user.name/email) on the CI runner,
# which is not configured for this job. See Atlassian's guidance: annotated
# tags = public releases, lightweight tags = internal/private markers.
#
# NOTE: `qa-deployed-*` / `qa-attested-impl-*` wildcard tag-protection rules in
# GitLab project settings are planned as a follow-up to #560/#643. Until they
# land, treat these tags as audit signals, not hard security guarantees — the
# promotion MR review remains the primary gate.
#
# Idempotent per tag: silently skips one that already exists on origin. Hard-
# fail on push errors — a missing tag would silently block future preprod
# deploys of this version.
push_tag_if_absent() {
  local tag="$1"
  if git ls-remote --tags --exit-code "$ORIGIN_URL" "refs/tags/${tag}" >/dev/null 2>&1; then
    echo "Tag ${tag} already exists on origin — skipping"
    return 0
  fi
  echo "Pushing tag ${tag} to origin"
  git tag "$tag"
  git push "$ORIGIN_URL" "refs/tags/${tag}"
  echo "Tag ${tag} pushed"
}

push_tag_if_absent "$TAG"
push_tag_if_absent "$IMPL_TAG"
