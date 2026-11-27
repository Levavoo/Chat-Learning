#!/usr/bin/env bash
set -euo pipefail
# assert-retrieval-tooling.sh — #629 fail-fast job-start guard for the
# retrieval-promotion child pipeline (.gitlab/ci/deploy/qa/retrieval-promotion.yml).
#
# The #492 rollout's corrective-MR trail included at least one job-image
# regression (!896, missing `jq`) discovered mid-transaction, after real QA
# mutation had already started. Call this as the first line of every job in
# that pipeline so a missing tool fails in seconds with a clear message
# instead of surfacing as a confusing failure deep inside a live promotion.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

MISSING=()
for bin in jq node aws; do
  command -v "$bin" >/dev/null 2>&1 || MISSING+=("$bin")
done

CDK_ENTRY="${REPO_ROOT}/cdk/bin/infrastructure.ts"
[[ -f "$CDK_ENTRY" ]] || MISSING+=("CDK entry point (${CDK_ENTRY})")

if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "assert-retrieval-tooling: missing required tooling before any AWS mutation:" >&2
  printf '  - %s\n' "${MISSING[@]}" >&2
  exit 1
fi

echo "assert-retrieval-tooling: jq, node, aws, and the CDK entry point are all present."
