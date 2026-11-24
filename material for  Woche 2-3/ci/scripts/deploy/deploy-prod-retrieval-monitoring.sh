#!/usr/bin/env bash
# #671 — Deploy only the four prod retrieval-health alarm actions.
#
# This is deliberately separate from the ordinary promotion path: a
# chatbot-only/config-only promotion does not deploy the ETL stack that owns
# these alarms. The script derives every image/slot context from the live
# active+previous manifests, proves the synthesized ETL template differs from
# the deployed template only in RetrievalHealthAlarms.*.AlarmActions, deploys
# that one stack, and verifies selectors remained byte-identical.
#
# Usage: deploy-prod-retrieval-monitoring.sh prod
set -euo pipefail

fail() {
  echo "prod-retrieval-monitoring-deploy: $*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
ENV="${1:-}"
[[ "$ENV" == prod ]] || fail "expected the literal environment argument 'prod'"

# The gate is a zero-AWS no-op unless config.yaml explicitly requests actions.
"${SCRIPT_DIR}/../validate/assert-prod-retrieval-monitoring-ready.sh" \
  prod "${REPO_ROOT}/deployments/prod/config.yaml" require-enabled

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
[[ -n "${GITLAB_OIDC_TOKEN:-}" ]] || fail "CI OIDC is required; workstation deployment is not supported"
qa_retrieval_assume_oidc \
  "$RETRIEVAL_PROMOTION_ROLE_ARN" prod-retrieval-monitoring-deploy

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

ACTIVE_BEFORE="${WORKDIR}/active-before.json"
PREVIOUS_BEFORE="${WORKDIR}/previous-before.json"
printf '%s\n' "$(qa_retrieval_required_ssm "$RETRIEVAL_ACTIVE_SELECTOR")" \
  >"$ACTIVE_BEFORE"
printf '%s\n' "$(qa_retrieval_required_ssm "$RETRIEVAL_PREVIOUS_SELECTOR")" \
  >"$PREVIOUS_BEFORE"
qa_retrieval_validate_manifest "$ACTIVE_BEFORE" >/dev/null
qa_retrieval_validate_manifest "$PREVIOUS_BEFORE" >/dev/null

BLUE_KB_ID="$(qa_retrieval_required_ssm "${RETRIEVAL_BASE_PATH}/slots/blue/knowledge-base-id")"
GREEN_KB_ID="$(qa_retrieval_required_ssm "${RETRIEVAL_BASE_PATH}/slots/green/knowledge-base-id")"
ACTIVE_KB_ID="$(jq -er .knowledge_base_id "$ACTIVE_BEFORE")"
PREVIOUS_KB_ID="$(jq -er .knowledge_base_id "$PREVIOUS_BEFORE")"

jq -n --arg active "$ACTIVE_KB_ID" --arg blue "$BLUE_KB_ID" \
  --arg green "$GREEN_KB_ID" \
  '{activeKbId:$active, blueKbId:$blue, greenKbId:$green}' \
  >"${WORKDIR}/resolve-slots-input.json"
SLOTS_JSON="$(node "${SCRIPT_DIR}/../lib/node/retrieval-orchestration.mjs" \
  resolve-slots "${WORKDIR}/resolve-slots-input.json")" || fail \
  "active manifest does not select a provisioned prod slot"
ACTIVE_SLOT="$(jq -er .activeSlot <<<"$SLOTS_JSON")"
INACTIVE_SLOT="$(jq -er .inactiveSlot <<<"$SLOTS_JSON")"

case "$INACTIVE_SLOT" in
  blue) [[ "$PREVIOUS_KB_ID" == "$BLUE_KB_ID" ]] || fail \
      "previous manifest does not select the inactive blue slot" ;;
  green) [[ "$PREVIOUS_KB_ID" == "$GREEN_KB_ID" ]] || fail \
      "previous manifest does not select the inactive green slot" ;;
  *) fail "unexpected inactive slot: ${INACTIVE_SLOT}" ;;
esac

ACTIVE_ETL_DIGEST="$(jq -er .etl_image_digest "$ACTIVE_BEFORE")"
PREVIOUS_ETL_DIGEST="$(jq -er .etl_image_digest "$PREVIOUS_BEFORE")"
[[ "$ACTIVE_ETL_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
  "active manifest has no immutable ETL digest"
[[ "$PREVIOUS_ETL_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
  "previous manifest has no immutable ETL digest"

if [[ "$ACTIVE_SLOT" == blue ]]; then
  BLUE_ETL_DIGEST="$ACTIVE_ETL_DIGEST"
  GREEN_ETL_DIGEST="$PREVIOUS_ETL_DIGEST"
else
  BLUE_ETL_DIGEST="$PREVIOUS_ETL_DIGEST"
  GREEN_ETL_DIGEST="$ACTIVE_ETL_DIGEST"
fi

# The ordinary promotion deploys the transform Lambda with the incoming/active
# ETL digest. Refuse to use selector state as a context if live code disagrees.
TRANSFORM_LAMBDA_ARN="$(qa_retrieval_required_ssm "/prod/renate/transform-lambda-arn")"
LIVE_TRANSFORM_URI="$(aws lambda get-function --function-name "$TRANSFORM_LAMBDA_ARN" \
  --query Code.ResolvedImageUri --output text)"
[[ "$LIVE_TRANSFORM_URI" == *@"$ACTIVE_ETL_DIGEST" ]] || fail \
  "live transform image does not match the active manifest ETL digest"

CURRENT_RAW="${WORKDIR}/current-raw.json"
CURRENT_TEMPLATE="${WORKDIR}/current-template.json"
DESIRED_TEMPLATE="${WORKDIR}/desired-template.json"
CURRENT_NORMALIZED="${WORKDIR}/current-normalized.json"
DESIRED_NORMALIZED="${WORKDIR}/desired-normalized.json"

fetch_deployed_template() {
  local output="$1"
  aws cloudformation get-template --stack-name "$RETRIEVAL_ETL_STACK" \
    --template-stage Original --query TemplateBody --output json \
    >"$CURRENT_RAW"
  jq 'if type == "string" then fromjson else . end' "$CURRENT_RAW" >"$output"
  jq -e '.Resources | type == "object"' "$output" >/dev/null || fail \
    "CloudFormation returned an invalid deployed template"
}

normalize_non_retrieval_actions() {
  jq -S '
    .Resources |= with_entries(
      if (.key | startswith("RetrievalHealthAlarms")) then
        .value.Properties |= del(.AlarmActions)
      else .
      end
    )
  ' "$1" >"$2"
}

fetch_deployed_template "$CURRENT_TEMPLATE"
(
  cd "$REPO_ROOT/cdk"
  npx cdk synth "$RETRIEVAL_ETL_STACK" --exclusively --json \
    --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
    --context env=prod \
    --context "etlImageTag=${ACTIVE_ETL_DIGEST}" \
    --context "retrievalCandidateSlot=${ACTIVE_SLOT}" \
    --context "blueEtlImageTag=${BLUE_ETL_DIGEST}" \
    --context "greenEtlImageTag=${GREEN_ETL_DIGEST}" \
    >"$DESIRED_TEMPLATE"
)
jq -e '.Resources | type == "object"' "$DESIRED_TEMPLATE" >/dev/null || fail \
  "CDK returned an invalid desired template"

jq -e '
  [.Resources | to_entries[] |
    select(.key | startswith("RetrievalHealthAlarms")) |
    select(.value.Type == "AWS::CloudWatch::Alarm")] as $alarms |
  ($alarms | length) == 4 and
  all($alarms[]; (.value.Properties.AlarmActions | type == "array" and length == 1))
' "$DESIRED_TEMPLATE" >/dev/null || fail \
  "desired template does not wire exactly four retrieval-health alarms to one action"

normalize_non_retrieval_actions "$CURRENT_TEMPLATE" "$CURRENT_NORMALIZED"
normalize_non_retrieval_actions "$DESIRED_TEMPLATE" "$DESIRED_NORMALIZED"
if ! cmp -s "$CURRENT_NORMALIZED" "$DESIRED_NORMALIZED"; then
  diff -u "$CURRENT_NORMALIZED" "$DESIRED_NORMALIZED" >&2 || true
  fail "ETL template contains changes outside retrieval-health AlarmActions"
fi

echo "prod-retrieval-monitoring-deploy: template allow-list passed; deploying only retrieval-health AlarmActions."
(
  cd "$REPO_ROOT/cdk"
  npx cdk deploy "$RETRIEVAL_ETL_STACK" \
    --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
    --context env=prod \
    --context "etlImageTag=${ACTIVE_ETL_DIGEST}" \
    --context "retrievalCandidateSlot=${ACTIVE_SLOT}" \
    --context "blueEtlImageTag=${BLUE_ETL_DIGEST}" \
    --context "greenEtlImageTag=${GREEN_ETL_DIGEST}" \
    --require-approval never
)

DEPLOYED_AFTER="${WORKDIR}/deployed-after.json"
fetch_deployed_template "$DEPLOYED_AFTER"
jq -S . "$DESIRED_TEMPLATE" >"${WORKDIR}/desired-sorted.json"
jq -S . "$DEPLOYED_AFTER" >"${WORKDIR}/deployed-after-sorted.json"
cmp -s "${WORKDIR}/desired-sorted.json" "${WORKDIR}/deployed-after-sorted.json" || fail \
  "deployed template does not match the reviewed desired template"

ACTIVE_AFTER="${WORKDIR}/active-after.json"
PREVIOUS_AFTER="${WORKDIR}/previous-after.json"
printf '%s\n' "$(qa_retrieval_required_ssm "$RETRIEVAL_ACTIVE_SELECTOR")" \
  >"$ACTIVE_AFTER"
printf '%s\n' "$(qa_retrieval_required_ssm "$RETRIEVAL_PREVIOUS_SELECTOR")" \
  >"$PREVIOUS_AFTER"
cmp -s "$ACTIVE_BEFORE" "$ACTIVE_AFTER" || fail "active selector changed"
cmp -s "$PREVIOUS_BEFORE" "$PREVIOUS_AFTER" || fail "previous selector changed"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

jq -n \
  --arg recorded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg active_release "$(jq -er .release_id "$ACTIVE_BEFORE")" \
  --arg previous_release "$(jq -er .release_id "$PREVIOUS_BEFORE")" \
  --arg active_slot "$ACTIVE_SLOT" \
  --arg inactive_slot "$INACTIVE_SLOT" \
  --arg active_etl_digest "$ACTIVE_ETL_DIGEST" \
  --arg previous_etl_digest "$PREVIOUS_ETL_DIGEST" \
  --arg desired_template_sha256 "$(hash_file "$DESIRED_TEMPLATE")" \
  '{
    schema_version: 1,
    recorded_at: $recorded_at,
    stack: "renate-etl-kb-prod",
    change_allowlist: "RetrievalHealthAlarms.*.AlarmActions only",
    active_release: $active_release,
    previous_release: $previous_release,
    active_slot: $active_slot,
    inactive_slot: $inactive_slot,
    active_etl_digest: $active_etl_digest,
    previous_etl_digest: $previous_etl_digest,
    desired_template_sha256: $desired_template_sha256,
    selectors_unchanged: true
  }' >prod-retrieval-monitoring-activation-evidence.json

echo "prod-retrieval-monitoring-deploy: alarm actions enabled; deployed template verified; selectors unchanged."
