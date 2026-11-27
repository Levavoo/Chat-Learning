#!/usr/bin/env bash
set -euo pipefail
# check-maintenance-rehearsal.sh <env>
# MR-time guard (TKT-MM-04): when an MR sets `maintenance: true` for <env>,
# fails unless the version being promoted has at least 2
# `maintenance-rehearsed-qa-<version>-*` tags on origin — each pushed by
# push-maintenance-rehearsed-tag.sh after a completed maintenance-switch:qa
# enable→disable cycle. A no-op (exit 0) when maintenance is not being
# enabled, so ordinary promotion MRs are unaffected.
# Pure git check (no AWS), suitable for a validate job on merge_request_event.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

ENV="${1:?Usage: check-maintenance-rehearsal.sh <env>}"
case "$ENV" in
  preprod) ;;
  *)
    echo "check-maintenance-rehearsal: unsupported env '${ENV}' (only preprod is gated today)" >&2
    exit 1
    ;;
esac

PIN="${REPO_ROOT}/deployments/${ENV}/version.yaml"
[[ -f "$PIN" ]] || { echo "Pin file not found: $PIN" >&2; exit 1; }

# Same extraction idiom as maintenance-switch.sh: first `maintenance:` line,
# trailing comment and whitespace stripped.
FLAG="$(sed -n 's/^maintenance:[[:space:]]*//p' "$PIN" \
  | head -n1 | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"

if [[ "$FLAG" != "true" ]]; then
  echo "maintenance: not set to true for ${ENV} — skipping rehearsal check"
  exit 0
fi

VERSION=$(read_pin_version "$PIN")
[[ -n "$VERSION" ]] || { echo "Could not parse version from $PIN" >&2; exit 1; }

echo "Checking ${VERSION} has at least 2 qa maintenance rehearsals before enabling ${ENV} maintenance…"
assert_maintenance_rehearsed "$VERSION"
echo "OK: ${VERSION} has enough qa rehearsals to enable ${ENV} maintenance"
