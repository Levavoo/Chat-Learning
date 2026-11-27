#!/usr/bin/env bash
set -euo pipefail
# check-promotion-source.sh <env>
# MR-time guard: verifies the application+data+ETL triple pinned for <env>
# matches qa's current pin or a QA-tested rollback triple.
# Pure file check (no AWS), suitable for a validate job on merge_request_event
# so a bad promotion MR fails before merge.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

ENV="${1:?Usage: check-promotion-source.sh <env>}"
_deploy_validate_env "$ENV" || exit 1

PIN="${REPO_ROOT}/deployments/${ENV}.yaml"
case "$ENV" in
  qa | preprod | prod) PIN="${REPO_ROOT}/deployments/${ENV}/version.yaml" ;;
esac
[[ -f "$PIN" ]] || { echo "Pin file not found: $PIN" >&2; exit 1; }

VERSION=$(grep '^version:' "$PIN" | sed 's/version: //' | tr -d '[:space:]')
[[ -n "$VERSION" ]] || { echo "Could not parse version from $PIN" >&2; exit 1; }

DATA_ARTIFACT_VERSION=$(promotion_pin_value "$PIN" data_artifact_version)
ETL_VERSION=$(promotion_pin_value "$PIN" etl_version)

# #642 controlled legacy-baseline migration: preprod's one-time blue baseline is
# captured live (scripts/capture-blue-baseline.sh), not promoted through qa, so
# it is exempt from the qa-promotion attestation. Narrow by construction — only
# preprod's synthetic v<version>-preprod-blue-baseline coordinate, used
# identically for data and ETL — so it can never authorize an ordinary promotion
# (those carry distinct, real data/ETL coordinates).
BASELINE_COORDINATE="v${VERSION}-preprod-blue-baseline"
if [[ "$ENV" == "preprod" && "$DATA_ARTIFACT_VERSION" == "$BASELINE_COORDINATE" && "$ETL_VERSION" == "$BASELINE_COORDINATE" ]]; then
  echo "OK: ${VERSION} + ${DATA_ARTIFACT_VERSION} + ${ETL_VERSION} is the #642 controlled preprod blue baseline (exempt from qa-promotion attestation)"
  exit 0
fi

echo "Checking ${ENV} versions ${VERSION} + ${DATA_ARTIFACT_VERSION} + ${ETL_VERSION} were promoted through qa…"
assert_pin_on_qa "$PIN" "${REPO_ROOT}/deployments/qa/version.yaml"
echo "OK: ${VERSION} + ${DATA_ARTIFACT_VERSION} + ${ETL_VERSION} is a qa-promoted triple"
