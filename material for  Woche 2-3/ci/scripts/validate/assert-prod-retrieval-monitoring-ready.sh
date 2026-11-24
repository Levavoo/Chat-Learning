#!/usr/bin/env bash
# #671 — Fail closed before prod retrieval alarm actions are wired.
#
# The CheckExecuted alarm treats missing data as breaching and prod's alert
# topic has official mailbox subscribers. A config-only promotion may enable
# those actions only after (a) the first ordinary promotion created a distinct
# previous selector and (b) a recent health run completed every check cleanly.
#
# Usage: assert-prod-retrieval-monitoring-ready.sh prod [config_file] [require-enabled]
set -euo pipefail

fail() {
  echo "prod-retrieval-monitoring-ready: $*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
ENV="${1:-}"
[[ "$ENV" == prod ]] || fail "expected the literal environment argument 'prod'"

CONFIG_FILE="${2:-${REPO_ROOT}/deployments/prod/config.yaml}"
[[ -f "$CONFIG_FILE" ]] || fail "missing config file: ${CONFIG_FILE}"
MODE="${3:-allow-disabled}"
[[ "$MODE" == allow-disabled || "$MODE" == require-enabled ]] || fail \
  "unknown mode: ${MODE}"

mapfile -t configured_values < <(
  awk '
    /^[[:space:]]*retrievalHealthAlarmActionsEnabled[[:space:]]*:/ {
      count++
      line = $0
      sub(/^[^:]*:[[:space:]]*/, "", line)
      sub(/[[:space:]]*#.*$/, "", line)
      sub(/[[:space:]]+$/, "", line)
      print line
    }
  ' "$CONFIG_FILE"
)

if [[ "${#configured_values[@]}" -eq 0 ]]; then
  [[ "$MODE" != require-enabled ]] || fail \
    "retrievalHealthAlarmActionsEnabled must be true for the activation job"
  echo "prod-retrieval-monitoring-ready: alarm actions remain disabled (flag absent)." >&2
  exit 0
fi
[[ "${#configured_values[@]}" -eq 1 ]] || fail \
  "retrievalHealthAlarmActionsEnabled must occur exactly once"

case "${configured_values[0]}" in
  false)
    [[ "$MODE" != require-enabled ]] || fail \
      "retrievalHealthAlarmActionsEnabled must be true for the activation job"
    echo "prod-retrieval-monitoring-ready: alarm actions remain disabled." >&2
    exit 0
    ;;
  true) ;;
  *) fail "retrievalHealthAlarmActionsEnabled must be boolean true or false" ;;
esac

# resolve-attested-implementation.sh overlays the QA-attested cdk/ tree before
# this script runs. Refuse a flag flip when that exact implementation predates
# #671 and would silently ignore the new config key.
grep -q 'retrievalHealthAlarmActionsEnabled' \
  "${REPO_ROOT}/cdk/lib/utils/parameter-models.ts" || fail \
  "the QA-attested CDK implementation does not support the alarm-action flag"
grep -q 'props.retrievalHealthAlarmActionsEnabled' \
  "${REPO_ROOT}/cdk/lib/etl-kb-stack.ts" || fail \
  "the QA-attested ETL stack does not wire the alarm-action flag"

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
qa_retrieval_init_env prod

if [[ -n "${GITLAB_OIDC_TOKEN:-}" ]]; then
  qa_retrieval_assume_oidc \
    "$RETRIEVAL_PROMOTION_ROLE_ARN" prod-retrieval-monitoring-ready
else
  aws sts get-caller-identity --output json >/dev/null 2>&1 || fail \
    "no GITLAB_OIDC_TOKEN and no usable AWS credentials"
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

read_required_parameter() {
  local name="$1" output="$2" error_file="${WORKDIR}/ssm-error"
  if aws ssm get-parameter --name "$name" --query Parameter.Value \
      --output text >"$output" 2>"$error_file"; then
    return 0
  fi
  cat "$error_file" >&2
  fail "required SSM parameter is absent or unreadable: ${name}"
}

ACTIVE_FILE="${WORKDIR}/active.json"
PREVIOUS_FILE="${WORKDIR}/previous.json"
STATE_FILE="${WORKDIR}/health-state.json"
read_required_parameter "$RETRIEVAL_ACTIVE_SELECTOR" "$ACTIVE_FILE"
read_required_parameter "$RETRIEVAL_PREVIOUS_SELECTOR" "$PREVIOUS_FILE"
read_required_parameter "$RETRIEVAL_HEALTH_STATE_PARAMETER" "$STATE_FILE"

qa_retrieval_validate_manifest "$ACTIVE_FILE" >/dev/null
qa_retrieval_validate_manifest "$PREVIOUS_FILE" >/dev/null
active_release="$(jq -er .release_id "$ACTIVE_FILE")"
previous_release="$(jq -er .release_id "$PREVIOUS_FILE")"
[[ "$active_release" != "$previous_release" ]] || fail \
  "active and previous selectors name the same release; first promotion is not proven"

# One scheduled interval plus one interval of tolerance. This proves the health
# runner reached all three checks recently; the GitLab schedule's active state
# is still a human-audited prerequisite in the #671 runbook.
MAX_AGE_SECONDS=1800
if ! jq -e --argjson max_age "$MAX_AGE_SECONDS" '
    . as $state |
    now as $now |
    ["IngestionFailure", "CoherenceFailure", "RetentionPinMissing"] as $checks |
    all($checks[];
      . as $check |
      ($state[$check] | type) == "object" and
      $state[$check].last_failed == false and
      (($state[$check].last_checked_at | fromdateiso8601) >= ($now - $max_age)) and
      (($state[$check].last_checked_at | fromdateiso8601) <= ($now + 300))
    )
  ' "$STATE_FILE" >/dev/null; then
  jq . "$STATE_FILE" >&2 2>/dev/null || true
  fail "health state is incomplete, stale, failed, or malformed; run the prod health check successfully before enabling alarm actions"
fi

oldest_check="$(jq -r '
  [.IngestionFailure.last_checked_at,
   .CoherenceFailure.last_checked_at,
   .RetentionPinMissing.last_checked_at] | min
' "$STATE_FILE")"
echo "prod-retrieval-monitoring-ready: first promotion and fresh clean health state verified (oldest check ${oldest_check}; active ${active_release}; previous ${previous_release})." >&2
