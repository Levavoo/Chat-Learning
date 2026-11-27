#!/usr/bin/env bash
set -euo pipefail

# render-deployment-page.sh — TKT-DDP-02
#
# Render a CDK `outputs.json` into the deterministic, scannable Markdown page
# that is published to the GitLab Wiki. See:
#   docs/architecture/rfc/rfc-deployment-dashboard.md
#   docs/tickets/ci_cd/03-deployment-detail-page.md  (TKT-DDP-02)
#
# Input: a CDK `--outputs-file` JSON of the shape
#   { "renate-chatbot-<env>": { "OutputKey": "OutputValue", ... }, ... }
#
# Output (stdout): a Markdown page with a fixed section order, most-important
# info first:
#   1. Quick access      — CloudFront URL, guardrails (id · version), version,
#                          API base, health, chat
#   2. Key endpoints     — the four endpoints as a labelled table
#   3. Important IDs      — CloudFront distribution id, API Gateway id
#   4. All outputs       — every output as a sorted `| stack | key | value |` row
#
# Determinism: stacks sort ASC, keys sort ASC, and the most-important slots are
# resolved by a stable key-matching priority (exact key before fuzzy; on a tie,
# the lexicographically smallest `<stack>.<key>` wins). Identical inputs produce
# byte-identical output so the Wiki gathers no noise revisions. Missing slots
# render as `n/a`; values that look like URLs (http:// or https://) render as
# `[value](value)` Markdown links. All diagnostics go to stderr.
#
# This script writes NOTHING to the repo — the rendered page is consumed by
# TKT-DDP-03. Values are published RAW on purpose (RFC: internal, not secret);
# they are never masked or redacted.
#
# Usage: render-deployment-page.sh <env> [outputs.json]
#   <env>          environment label, e.g. dev or qa (required)
#   [outputs.json] path to the CDK outputs file
#                  (default: <repo-root>/outputs.json, matching deploy-*.sh)
#
# Optional overrides (for reproducible output / testing):
#   RENDER_TIMESTAMP  "last updated" value
#                     (default: $CI_PIPELINE_CREATED_AT, else current UTC time)
#   RENDER_VERSION    version indicator
#                     (default: $CI_COMMIT_TAG, else $CI_COMMIT_SHORT_SHA, else "unknown")
#   RENDER_DATA_VERSION  data artifact version (optional, e.g. DATA_ARTIFACT_VERSION);
#                        when set, rendered as an additional Quick access line.
#   RENDER_ETL_VERSION   ETL image version (optional, e.g. ETL_VERSION);
#                        when set, rendered as an additional Quick access line.
#   RENDER_VERSION_FILE  path to the maintenance.yaml carrying the optional
#                        `maintenance:` flag (TKT-MM-03)
#                        (default: <repo-root>/deployments/<env>/maintenance.yaml)
#   RENDER_ROLLBACK_DEGRADED  degraded-rollback marker value (#628); any
#                             non-empty, non-"false" value renders a banner.
#                             Typically the SSM marker JSON, read by the
#                             caller — this script makes no AWS calls.
#                             (default: empty — no banner)

err() { printf '%s\n' "$*" >&2; }

ENV_LABEL="${1:-}"
[[ -n "$ENV_LABEL" ]] \
  || { err "Usage: render-deployment-page.sh <env> [outputs.json]"; exit 1; }

# Resolve the repo root from this script's own location so the default outputs
# path is deterministic regardless of the caller's CWD (mirrors deploy-*.sh).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
OUTPUTS_FILE="${2:-${REPO_ROOT}/outputs.json}"

[[ -f "$OUTPUTS_FILE" ]] \
  || { err "outputs file not found: $OUTPUTS_FILE"; exit 1; }
[[ -s "$OUTPUTS_FILE" ]] \
  || { err "outputs file is empty: $OUTPUTS_FILE"; exit 1; }
if ! jq -e 'type == "object"' "$OUTPUTS_FILE" >/dev/null 2>&1; then
  err "outputs file is not a valid JSON object: $OUTPUTS_FILE"
  err "File content (first 500 bytes):"
  head -c 500 "$OUTPUTS_FILE" | sed 's/^/  /' >&2
  exit 1
fi

# Bail before rendering if there is nothing to show (empty object, or every
# stack has a null/empty output map). `.value // {}` tolerates a null stack.
COUNT="$(jq '[ to_entries[] | (.value // {}) | to_entries[] ] | length' "$OUTPUTS_FILE")"
[[ "$COUNT" -gt 0 ]] || { err "no outputs found in $OUTPUTS_FILE"; exit 1; }

TIMESTAMP="${RENDER_TIMESTAMP:-${CI_PIPELINE_CREATED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}}"
VERSION="${RENDER_VERSION:-${CI_COMMIT_TAG:-${CI_COMMIT_SHORT_SHA:-unknown}}}"

# Maintenance flag (TKT-MM-03): read the optional `maintenance:` key from this
# environment's maintenance file. A missing file, a missing key, or any value
# other than the literal `true` means normal operation.
# Override for tests: RENDER_VERSION_FILE points at an alternate maintenance.yaml.
# TODO (Iteration 2): parse the structured maintenance block
# (enabled/reason/owner/expected_off) here and pass the extra fields to jq.
VERSION_FILE="${RENDER_VERSION_FILE:-${REPO_ROOT}/deployments/${ENV_LABEL}/maintenance.yaml}"
MAINTENANCE="false"
if [[ -f "$VERSION_FILE" ]]; then
  FLAG="$(sed -n 's/^maintenance:[[:space:]]*//p' "$VERSION_FILE" | head -n1 | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"
  if [[ "$FLAG" == "true" ]]; then MAINTENANCE="true"; fi
fi

# All page logic lives in render-deployment-page.jq (next to this script) so
# ordering and slot resolution are done over the parsed JSON (not text-munged),
# keeping output byte-stable across runs. See that file for the slot-resolution
# contract. Resolve it from BASH_SOURCE so the path is independent of the CWD.
JQ_PROGRAM="$(dirname "${BASH_SOURCE[0]}")/render-deployment-page.jq"
[[ -f "$JQ_PROGRAM" ]] \
  || { err "jq program not found: $JQ_PROGRAM"; exit 1; }

jq -r \
  --arg env "$ENV_LABEL" \
  --arg ts "$TIMESTAMP" \
  --arg ver "$VERSION" \
  --arg maint "$MAINTENANCE" \
  --arg degraded "${RENDER_ROLLBACK_DEGRADED:-}" \
  --arg data_ver "${RENDER_DATA_VERSION:-}" \
  --arg etl_ver "${RENDER_ETL_VERSION:-}" \
  --arg evidence "${RENDER_EVIDENCE:-}" \
  -f "$JQ_PROGRAM" \
  "$OUTPUTS_FILE"
