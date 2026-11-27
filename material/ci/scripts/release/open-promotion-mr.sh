#!/usr/bin/env bash
set -euo pipefail
# open-promotion-mr.sh <from-env> <to-env>
# Opens/updates a GitOps promotion MR bumping the <to-env> version pin
# (deployments/<to-env>/version.yaml for qa/preprod/prod).
#
# Usage in CI:
#   open-promotion-mr.sh qa preprod    (after smoke-eval:qa)
#   open-promotion-mr.sh dev qa        (replaces open-qa-mr.sh)
#
# Required CI variables: GL_TOKEN, CI_API_V4_URL, CI_PROJECT_ID,
#                        CI_SERVER_HOST, CI_PROJECT_PATH
# Optional: SMOKE_TEST=true (creates then immediately closes MR + deletes branch)
# Optional: PROMO_BRANCH (override branch name; default: chore/<to>-promotion)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/promote-mr.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/promote-mr.sh"

FROM_ENV="${1:-}"
TO_ENV="${2:-}"

[[ -n "$FROM_ENV" && -n "$TO_ENV" ]] \
  || { echo "Usage: open-promotion-mr.sh <from-env> <to-env>" >&2; exit 1; }

FROM_PIN="${REPO_ROOT}/deployments/${FROM_ENV}.yaml"
TO_PIN="${REPO_ROOT}/deployments/${TO_ENV}.yaml"
# qa/preprod/prod use subdir layout: deployments/<env>/version.yaml
case "$FROM_ENV" in qa | preprod | prod) FROM_PIN="${REPO_ROOT}/deployments/${FROM_ENV}/version.yaml" ;; esac
case "$TO_ENV" in qa | preprod | prod) TO_PIN="${REPO_ROOT}/deployments/${TO_ENV}/version.yaml" ;; esac

[[ -f "$FROM_PIN" ]] || { echo "Source pin file not found: $FROM_PIN" >&2; exit 1; }
[[ -f "$TO_PIN" ]]   || { echo "Target pin file not found: $TO_PIN" >&2; exit 1; }

NEW_VERSION=$(grep '^version:' "$FROM_PIN" | sed 's/version: //' | tr -d '[:space:]')
[[ -n "$NEW_VERSION" ]] \
  || { echo "Could not parse version from $FROM_PIN" >&2; exit 1; }
DATA_ARTIFACT_VERSION=$(grep '^data_artifact_version:' "$FROM_PIN" \
  | sed 's/data_artifact_version: //' | tr -d '[:space:]')
[[ "$DATA_ARTIFACT_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] \
  || { echo "Could not parse data_artifact_version from $FROM_PIN" >&2; exit 1; }
ETL_VERSION=$(grep '^etl_version:' "$FROM_PIN" \
  | sed 's/etl_version: //' | tr -d '[:space:]')
[[ "$ETL_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] \
  || { echo "Could not parse etl_version from $FROM_PIN" >&2; exit 1; }

CURRENT_TO=$(grep '^version:' "$TO_PIN" | sed 's/version: //' | tr -d '[:space:]')
CURRENT_DATA_ARTIFACT_VERSION=$(grep '^data_artifact_version:' "$TO_PIN" \
  | sed 's/data_artifact_version: //' | tr -d '[:space:]' || true)
CURRENT_ETL_VERSION=$(grep '^etl_version:' "$TO_PIN" \
  | sed 's/etl_version: //' | tr -d '[:space:]' || true)
if [[ "$CURRENT_TO" == "$NEW_VERSION" \
  && "$CURRENT_DATA_ARTIFACT_VERSION" == "$DATA_ARTIFACT_VERSION" \
  && "$CURRENT_ETL_VERSION" == "$ETL_VERSION" ]]; then
  echo "${TO_ENV^^} already at ${NEW_VERSION} with data ${DATA_ARTIFACT_VERSION} and ETL ${ETL_VERSION} — nothing to do"
  exit 0
fi

echo "Promoting ${TO_ENV^^}: ${CURRENT_TO} → ${NEW_VERSION}"

if [[ "${SMOKE_TEST:-false}" == "true" ]]; then
  PROMO_BRANCH="${PROMO_BRANCH:-chore/${TO_ENV}-promotion-smoke-$$}"
else
  PROMO_BRANCH="${PROMO_BRANCH:-chore/${TO_ENV}-promotion}"
fi

cd "$REPO_ROOT"
open_promotion_mr "$FROM_ENV" "$TO_ENV" "$NEW_VERSION" "$PROMO_BRANCH" \
  "${SMOKE_TEST:-false}" "$DATA_ARTIFACT_VERSION" "$ETL_VERSION"
