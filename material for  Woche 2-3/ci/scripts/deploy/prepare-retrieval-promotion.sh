#!/usr/bin/env bash
# Validate the exact #490 pin for <env> and emit deterministic promotion
# coordinates. Environment-parameterized (#643): the same code serves qa and
# preprod; the pin path and dotenv basename come from the environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: prepare-retrieval-promotion.sh <qa|preprod|prod> [pin_file] [output_file]}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"
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

PIN_FILE="${2:-${REPO_ROOT}/deployments/${ENV}/version.yaml}"
OUTPUT_FILE="${3:-${REPO_ROOT}/${RETRIEVAL_ARTIFACT_PREFIX}.env}"

validate_promotion_pin "$PIN_FILE"

# #643 — the pin must still equal QA's current triple, re-checked HERE rather
# than only at MR time. check-promotion-source.sh runs on the promotion MR, but
# QA can be re-promoted between that merge and this transaction; this script runs
# both in the zero-write parent preflight (before approval) and again in the
# child under resource_group: deploy-preprod (before any mutation), so a triple
# that drifted during the human approval wait is caught. Downstream only: for QA
# itself the comparison is against its own pin and always trivially true.
if [[ "$RETRIEVAL_RAW_SOURCE_MODE" != origin ]]; then
  assert_pin_on_qa "$PIN_FILE" "${REPO_ROOT}/deployments/qa/version.yaml"
fi

CHATBOT_VERSION=$(promotion_pin_value "$PIN_FILE" version)
DATA_ARTIFACT_VERSION=$(promotion_pin_value "$PIN_FILE" data_artifact_version)
ETL_VERSION=$(promotion_pin_value "$PIN_FILE" etl_version)
RELEASE_ID=$(node "${SCRIPT_DIR}/../lib/node/retrieval-release.mjs" derive-release \
  "$CHATBOT_VERSION" "$DATA_ARTIFACT_VERSION" "$ETL_VERSION")

# #643 D3 / #660 — deployment-implementation attestation.
#
# The triple above proves the release INPUTS. It cannot prove which deployment
# implementation validated them: a retrieval CDK or CI-script change merged after
# the QA transaction — including a #626 stack-only change that moves no
# coordinate — must not ride an unrelated QA attestation into preprod.
#
# #643 closed that gap by fingerprinting master HEAD and requiring a matching
# qa-attested-impl-<fp> tag. But HEAD drifts with every unrelated master commit,
# so that comparison forced a freeze window on every promotion (see #660). #660
# replaced the comparison by RUNNING the exact implementation QA attested:
# resolve-attested-implementation.sh overlays it in each mutating job. Here we
# resolve and record the very same commit, so the zero-write preflight fails
# closed BEFORE approval when a triple was never attested, and the transaction's
# audit evidence can name the implementation it ran.
#
# Only downstream (non-origin) environments attest: QA IS the attester, so
# requiring its own tag before it has run would be circular. ATTESTATION_MODE=skip
# is the explicit, logged break-glass for a reviewed recovery; it never silently
# defaults on. resolve_pin_attested_commit fails closed (set -e) on an unattested
# triple or an unreachable origin.
ATTESTED_COMMIT=""
if [[ "$RETRIEVAL_RAW_SOURCE_MODE" == downstream ]]; then
  if [[ "${ATTESTATION_MODE:-}" == skip ]]; then
    echo "WARNING: ATTESTATION_MODE=skip — implementation attestation bypassed for ${ENV}; the transaction will run whatever is on current master (reviewed break-glass)." >&2
  else
    ATTESTED_COMMIT="$(resolve_pin_attested_commit "$PIN_FILE")"
    printf 'Implementation attestation: %s -> %s (qa-attested; overlaid before every mutation)\n' \
      "$(promotion_pin_attestation_tag "$PIN_FILE")" "$ATTESTED_COMMIT"
  fi
fi

cat >"$OUTPUT_FILE" <<EOF
CHATBOT_VERSION=${CHATBOT_VERSION}
DATA_ARTIFACT_VERSION=${DATA_ARTIFACT_VERSION}
ETL_VERSION=${ETL_VERSION}
RELEASE_ID=${RELEASE_ID}
ATTESTED_COMMIT=${ATTESTED_COMMIT}
EOF

printf 'Validated %s retrieval promotion %s + %s + %s\n' \
  "$ENV" "$CHATBOT_VERSION" "$DATA_ARTIFACT_VERSION" "$ETL_VERSION"
printf 'Derived release ID: %s\n' "$RELEASE_ID"
if [[ -n "$ATTESTED_COMMIT" ]]; then
  printf 'Attested implementation commit: %s\n' "$ATTESTED_COMMIT"
fi
