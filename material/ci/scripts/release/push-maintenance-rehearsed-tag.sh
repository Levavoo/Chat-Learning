#!/usr/bin/env bash
set -euo pipefail
# push-maintenance-rehearsed-tag.sh
# Push `maintenance-rehearsed-qa-<version>-<pipeline_id>` git tag on origin
# after a completed maintenance-switch:qa disable (an enable→disable
# rehearsal cycle). Read by `assert_maintenance_rehearsed` in lib/deploy.sh
# so preprod may only enable maintenance for a version that was rehearsed at
# least twice on qa. See TKT-MM-04 and
# docs/architecture/rfc/rfc-maintenance-mode.md.
#
# Idempotent: silently skips if the tag already exists on origin.
# Hard-fail on push errors — a missing tag would silently block the preprod
# rehearsal gate for a version that actually was rehearsed.
#
# Required CI variables: CI_SERVER_HOST, CI_PROJECT_PATH, CI_JOB_TOKEN, CI_PIPELINE_ID

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

: "${CI_SERVER_HOST:?CI_SERVER_HOST is required}"
: "${CI_PROJECT_PATH:?CI_PROJECT_PATH is required}"
: "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"
: "${CI_PIPELINE_ID:?CI_PIPELINE_ID is required}"

QA_PIN="${REPO_ROOT}/deployments/qa/version.yaml"
[[ -f "$QA_PIN" ]] || { echo "qa pin not found: $QA_PIN" >&2; exit 1; }

VERSION=$(read_pin_version "$QA_PIN")
[[ -n "$VERSION" ]] || { echo "Could not parse version from $QA_PIN" >&2; exit 1; }

TAG="maintenance-rehearsed-qa-${VERSION}-${CI_PIPELINE_ID}"
ORIGIN_URL="https://gitlab-ci-token:${CI_JOB_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"

if git ls-remote --tags --exit-code "$ORIGIN_URL" "refs/tags/${TAG}" >/dev/null 2>&1; then
  echo "Tag ${TAG} already exists on origin — skipping"
  exit 0
fi

echo "Pushing tag ${TAG} to origin"
# Lightweight tag, same rationale as push-qa-deployed-tag.sh:
# assert_maintenance_rehearsed only checks ref existence/count via
# `git ls-remote`, and the runner has no git identity configured for an
# annotated tag's commit object.
git tag "$TAG"
git push "$ORIGIN_URL" "refs/tags/${TAG}"
echo "Tag ${TAG} pushed"
