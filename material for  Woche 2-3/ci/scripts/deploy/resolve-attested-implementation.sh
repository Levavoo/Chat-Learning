#!/usr/bin/env bash
# #660 — Overlay the QA-attested deployment implementation for a downstream
# (preprod/prod) retrieval promotion.
#
# WHY. A promotion is DEFINED by the pin on current master (the triple being
# promoted), but the code that ENACTS it must be the code qa validated. The
# original D3 gate instead fingerprinted master HEAD and required a matching
# qa-attested-impl-<fp> tag; because master keeps moving, any unrelated commit
# touching an attested file between the qa transaction and the preprod merge
# flipped that fingerprint and falsely refused the promotion — a 30–60 min freeze
# window on every promotion (the 2026-07-28 API-Gateway fix to chatbot-stack.ts
# is the worked example). This script removes the window by construction: it
# discovers the exact commit qa attested and replaces the executing
# implementation on disk with that commit's, so drift is impossible. The pin
# stays current — it is the promotion definition. See #660 and
# docs/architecture/runbooks/643-preprod-retrieval-promotion.md.
#
# DISCOVERY. pin -> qa-deployed-<triple> tag -> the exact qa commit. That tag and
# qa-attested-impl-<fp> are pushed together at the same qa HEAD by
# push-qa-deployed-tag.sh, so the resolved commit IS an attested implementation.
#
# OVERLAY SCOPE = the code that EXECUTES during a promotion: the whole cdk/ app
# (so `cdk synth --exclusively` resolves every import to attested code — the
# retrieval stacks pull in many constructs OUTSIDE the fingerprint set, so a
# file-level overlay would synth a Frankenstein tree) plus the retrieval deploy
# scripts and node modules. The ETL IMAGE inputs in the fingerprint
# (backend/src/etl, bm25_shared, dep manifests) are deliberately NOT overlaid:
# the promotion references the prebuilt ETL image by immutable digest, so those
# are already pinned. The bootstrap that runs this discovery/overlay
# (prepare-retrieval-promotion.sh, this script, lib/deploy.sh) stays on current
# master — it must, to be able to apply the overlay at all.
#
# SAFE TO RUN IN EVERY MUTATING JOB. Deterministic: the same pin resolves to the
# same commit and the same overlay, so the preflight and each child job converge
# on identical code. Fail-closed: an unresolved tag, an unreachable origin, or a
# declared-but-missing attested path aborts before any mutation.
# ATTESTATION_MODE=skip is the explicit, logged break-glass (identical contract
# to the old gate): it runs whatever is on current master.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: resolve-attested-implementation.sh <preprod|prod> [pin_file]}"

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
ATTESTED_ENV="${ATTESTED_ENV:-${REPO_ROOT}/${RETRIEVAL_ARTIFACT_PREFIX}-attested.env}"

# The executing-implementation set (see header). Directories and files both work
# with `git checkout <commit> -- <path>` and `git ls-tree`.
ATTESTED_PATHS=(
  # whole cdk app: synth coherence for the two --exclusively stacks
  "cdk"
  # retrieval deploy implementation (the scripts that mutate the environment)
  ".gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
  ".gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
  ".gitlab/ci/scripts/deploy/activate-retrieval.sh"
  ".gitlab/ci/scripts/verify/etl-readiness-check.sh"
  # shared library + typed decision modules the deploy scripts call
  ".gitlab/ci/scripts/lib/qa-retrieval.sh"
  ".gitlab/ci/scripts/lib/node/retrieval-orchestration.mjs"
  ".gitlab/ci/scripts/lib/node/retrieval-release.mjs"
  ".gitlab/ci/scripts/lib/node/retrieval-environment.mjs"
  ".gitlab/ci/scripts/lib/node/release-retention.mjs"
)

# qa IS the attester and runs its own current implementation; overlaying would be
# circular. Only downstream (non-origin) environments run attested code.
if [[ "$RETRIEVAL_RAW_SOURCE_MODE" != downstream ]]; then
  echo "resolve-attested-implementation: ${ENV} is not downstream (rawSourceMode=${RETRIEVAL_RAW_SOURCE_MODE}); no overlay." >&2
  exit 0
fi

if [[ "${ATTESTATION_MODE:-}" == skip ]]; then
  echo "WARNING: ATTESTATION_MODE=skip — ${ENV} will run the CURRENT-master implementation, NOT the qa-attested one (reviewed break-glass)." >&2
  exit 0
fi

cd "$REPO_ROOT"

TRIPLE_TAG="$(promotion_pin_attestation_tag "$PIN_FILE")"
ATTESTED_COMMIT="$(resolve_pin_attested_commit "$PIN_FILE")"   # fail-closed inside
echo "Attested implementation: ${TRIPLE_TAG} -> ${ATTESTED_COMMIT}" >&2

# Bring the attested commit into the (shallow, --depth 20) CI clone. Fetch the
# tag at depth 1 rather than the bare sha: fetching a tag ref is portable, and
# depth 1 pulls exactly that commit's tree+blobs without deepening history.
git fetch --depth=1 origin "refs/tags/${TRIPLE_TAG}" >/dev/null 2>&1 || {
  echo "resolve-attested-implementation: could not fetch ${TRIPLE_TAG} from origin." >&2
  exit 1
}
# Guard against the tag moving between the ls-remote resolve and this fetch.
fetched="$(git rev-parse "FETCH_HEAD^{commit}" 2>/dev/null || true)"
[[ "$fetched" == "$ATTESTED_COMMIT" ]] || {
  echo "resolve-attested-implementation: ${TRIPLE_TAG} changed under us (${ATTESTED_COMMIT} != ${fetched})." >&2
  exit 1
}

# Fail closed on any declared attested path absent at the attested commit — a
# renamed or removed input must break the transaction, not silently narrow the
# executed surface (the same fail-closed stance as the fingerprint's
# assert_declared_inputs_present).
missing=0
for p in "${ATTESTED_PATHS[@]}"; do
  if [[ -z "$(git ls-tree "$ATTESTED_COMMIT" -- "$p")" ]]; then
    echo "resolve-attested-implementation: declared attested path missing at ${ATTESTED_COMMIT}: ${p}" >&2
    missing=1
  fi
done
[[ "$missing" -eq 0 ]] || exit 1

git checkout "$ATTESTED_COMMIT" -- "${ATTESTED_PATHS[@]}"
echo "Overlaid the qa-attested implementation from ${ATTESTED_COMMIT} (${#ATTESTED_PATHS[@]} paths)." >&2

# Record the resolved identity for the transaction's audit evidence (D11) and for
# any later human forensics. Written, not exported: CI job steps run in one shell,
# but downstream jobs pick this up as an artifact.
cat >"$ATTESTED_ENV" <<EOF
ATTESTED_COMMIT=${ATTESTED_COMMIT}
ATTESTED_TRIPLE_TAG=${TRIPLE_TAG}
EOF
