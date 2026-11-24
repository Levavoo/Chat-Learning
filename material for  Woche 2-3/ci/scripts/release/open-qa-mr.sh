#!/usr/bin/env bash
set -euo pipefail
# open-qa-mr.sh — promotes dev→qa.
# Source of truth for version: NEW_TAG (from cocogitto-release dotenv artifact)
# or DEV_PIN_FILE (deployments/dev/version.yaml in file-triggered pipelines).
# Uses lib/promote-mr.sh for the git+MR mechanics.
#
# Required: BUMPED, GL_TOKEN, CI_API_V4_URL, CI_PROJECT_ID,
#           CI_SERVER_HOST, CI_PROJECT_PATH, CI_JOB_TOKEN
# Version source (one of):
#   NEW_TAG + DATA_ARTIFACT_VERSION + ETL_VERSION (cocogitto pipeline)
#   DEV_PIN_FILE path (file-triggered pipeline — reads coords from pin file)
# Optional: SMOKE_TEST=true, PROMO_BRANCH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/promote-mr.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/promote-mr.sh"

if [[ "${BUMPED:-false}" != "true" ]]; then
  echo "No version bump — skipping QA promotion"
  exit 0
fi

# If a dev pin file is provided, read version coordinates from it.
if [[ -n "${DEV_PIN_FILE:-}" ]]; then
  PIN="${REPO_ROOT}/${DEV_PIN_FILE}"
  [[ -f "$PIN" ]] || { echo "DEV_PIN_FILE not found: $PIN" >&2; exit 1; }
  NEW_TAG=$(grep '^version:' "$PIN" | awk '{print $2}')
  DATA_ARTIFACT_VERSION=$(grep '^data_artifact_version:' "$PIN" | awk '{print $2}')
  ETL_VERSION=$(grep '^etl_version:' "$PIN" | awk '{print $2}')
fi

: "${NEW_TAG:?NEW_TAG is required}"
: "${DATA_ARTIFACT_VERSION:?DATA_ARTIFACT_VERSION is required}"
: "${ETL_VERSION:?ETL_VERSION is required}"
[[ "$DATA_ARTIFACT_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
  echo "Invalid DATA_ARTIFACT_VERSION: ${DATA_ARTIFACT_VERSION}" >&2
  exit 1
}
[[ "$ETL_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
  echo "Invalid ETL_VERSION: ${ETL_VERSION}" >&2
  exit 1
}

QA_VERSION=$(grep '^version:' "${REPO_ROOT}/deployments/qa/version.yaml" \
  | sed 's/version: //' | tr -d '[:space:]')
QA_DATA_ARTIFACT_VERSION=$(grep '^data_artifact_version:' \
  "${REPO_ROOT}/deployments/qa/version.yaml" \
  | sed 's/data_artifact_version: //' | tr -d '[:space:]' || true)
QA_ETL_VERSION=$(grep '^etl_version:' "${REPO_ROOT}/deployments/qa/version.yaml" \
  | sed 's/etl_version: //' | tr -d '[:space:]' || true)
if [[ "$QA_VERSION" == "$NEW_TAG" \
  && "$QA_DATA_ARTIFACT_VERSION" == "$DATA_ARTIFACT_VERSION" \
  && "$QA_ETL_VERSION" == "$ETL_VERSION" ]]; then
  echo "QA already at ${NEW_TAG} with data ${DATA_ARTIFACT_VERSION} and ETL ${ETL_VERSION} — nothing to do"
  exit 0
fi

echo "Promoting QA: ${QA_VERSION} → ${NEW_TAG}"

if [[ "${SMOKE_TEST:-false}" == "true" ]]; then
  PROMO_BRANCH="${PROMO_BRANCH:-chore/qa-promotion-smoke-$$}"
else
  PROMO_BRANCH="${PROMO_BRANCH:-chore/qa-promotion}"
fi

cd "$REPO_ROOT"
# dev→qa: the version comes from NEW_TAG (cocogitto), not a "dev" pin file.
# from_env="dev" is only a label; open_promotion_mr derives the MR's "from"
# version from the TARGET pin (deployments/qa/version.yaml) before overwriting.
open_promotion_mr "dev" "qa" "$NEW_TAG" "$PROMO_BRANCH" \
  "${SMOKE_TEST:-false}" "$DATA_ARTIFACT_VERSION" "$ETL_VERSION"
