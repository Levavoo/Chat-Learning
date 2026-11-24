#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
EVIDENCE_DIR="${FOUNDATION_OUTPUT_DIR:-${REPO_ROOT}/preprod-foundation-evidence}"
CONTEXT_FILE="${EVIDENCE_DIR}/preprod-foundation-context.env"
STATE_FILE="${EVIDENCE_DIR}/preprod-foundation-state.json"
RESOURCES_BEFORE="${EVIDENCE_DIR}/preprod-etl-stack-resources.json"
ASSEMBLY_DIR="${EVIDENCE_DIR}/cdk.out"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "preprod-foundation-deploy: $*" >&2
  exit 1
}

stable_lambda_config_sha() {
  local config="$1" normalized="${TMP_DIR}/lambda-config-$RANDOM.json"
  jq -S '
    del(
      .State,
      .StateReason,
      .StateReasonCode,
      .LastUpdateStatus,
      .LastUpdateStatusReason,
      .LastUpdateStatusReasonCode
    )
  ' "$config" >"$normalized"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$normalized" | cut -d' ' -f1
  else
    shasum -a 256 "$normalized" | cut -d' ' -f1
  fi
}

: "${ISSUE_641_EVIDENCE_URL:?Attach the preflight evidence to #641 and provide ISSUE_641_EVIDENCE_URL}"
[[ "$ISSUE_641_EVIDENCE_URL" =~ /-/work_items/641#note_ ]] ||
[[ "$ISSUE_641_EVIDENCE_URL" =~ /-/issues/641#note_ ]] ||
  fail "ISSUE_641_EVIDENCE_URL must point to a note on issue #641"

[[ -f "$CONTEXT_FILE" && -f "$STATE_FILE" && -f "$RESOURCES_BEFORE" &&
  -f "${ASSEMBLY_DIR}/manifest.json" ]] \
  || fail "required preflight artifacts are missing"
# shellcheck disable=SC1090
source "$CONTEXT_FILE"
: "${LEGACY_ETL_DIGEST:?LEGACY_ETL_DIGEST missing from preflight}"
: "${LEGACY_ETL_REPOSITORY:?LEGACY_ETL_REPOSITORY missing from preflight}"
: "${LEGACY_ETL_IMAGE_COORDINATE:?LEGACY_ETL_IMAGE_COORDINATE missing from preflight}"
: "${TRANSFORM_IMAGE_URI_BEFORE:?TRANSFORM_IMAGE_URI_BEFORE missing from preflight}"
: "${BLUE_BM25_IMAGE_URI_BEFORE:?BLUE_BM25_IMAGE_URI_BEFORE missing from preflight}"
: "${CHATBOT_IMAGE_URI_BEFORE:?CHATBOT_IMAGE_URI_BEFORE missing from preflight}"
: "${CHATBOT_DIGEST_BEFORE:?CHATBOT_DIGEST_BEFORE missing from preflight}"
: "${CHAT_CONFIG_SHA_BEFORE:?CHAT_CONFIG_SHA_BEFORE missing from preflight}"
: "${ETL_STACK:?ETL_STACK missing from preflight}"
: "${CHATBOT_STACK:?CHATBOT_STACK missing from preflight}"

RECHECK_DIR="${TMP_DIR}/recheck"
FOUNDATION_OUTPUT_DIR="$RECHECK_DIR" \
  "${SCRIPT_DIR}/preflight-preprod-retrieval-foundation.sh"
cmp -s "$STATE_FILE" "${RECHECK_DIR}/preprod-foundation-state.json" \
  || fail "live state drifted after review; run a new preflight and attach new evidence"

CONFIG="$(node "${SCRIPT_DIR}/../lib/node/retrieval-environment.mjs" json preprod)"
PREPROD_ROLE="$(jq -r .promotionRoleArn <<<"$CONFIG")"
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
qa_retrieval_assume_oidc "$PREPROD_ROLE" preprod-foundation-deploy
[[ "$(aws sts get-caller-identity --query Account --output text)" == "271033482134" ]] \
  || fail "deployment credentials are not in the preprod account"

(
  cd "${REPO_ROOT}/cdk"
  npx cdk deploy --app "$ASSEMBLY_DIR" "$ETL_STACK" \
    --exclusively \
    --require-approval never \
    --outputs-file "${EVIDENCE_DIR}/preprod-foundation-outputs.json"
)

RESOURCES_AFTER="${EVIDENCE_DIR}/preprod-etl-stack-resources-after.json"
CFN_DEPLOY_ROLE="arn:aws:iam::271033482134:role/cdk-hnb659fds-deploy-role-271033482134-eu-central-1"
read -r CFN_ACCESS_KEY_ID CFN_SECRET_ACCESS_KEY CFN_SESSION_TOKEN < <(
  aws sts assume-role --role-arn "$CFN_DEPLOY_ROLE" \
    --role-session-name "gitlab-${CI_JOB_ID}-foundation-resource-verify" \
    --duration-seconds 900 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text
)
[[ -n "$CFN_ACCESS_KEY_ID" && -n "$CFN_SECRET_ACCESS_KEY" &&
  -n "$CFN_SESSION_TOKEN" ]] \
  || fail "CDK deploy role returned incomplete credentials for resource verification"
AWS_ACCESS_KEY_ID="$CFN_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$CFN_SECRET_ACCESS_KEY" \
AWS_SESSION_TOKEN="$CFN_SESSION_TOKEN" \
  aws cloudformation list-stack-resources --stack-name "$ETL_STACK" |
  jq '{
    StackResources: [
      .StackResourceSummaries[] | {
        LogicalResourceId,
        PhysicalResourceId,
        ResourceType,
        Timestamp: .LastUpdatedTimestamp,
        ResourceStatus,
        DriftInformation
      }
    ]
  }' >"$RESOURCES_AFTER"
node - "$RESOURCES_BEFORE" "$RESOURCES_AFTER" <<'NODE'
const fs = require('node:fs');
const [beforeFile, afterFile] = process.argv.slice(2);
const resources = (file) =>
  new Map(
    JSON.parse(fs.readFileSync(file, 'utf8')).StackResources.map((resource) => [
      resource.LogicalResourceId,
      resource,
    ]),
  );
const before = resources(beforeFile);
const after = resources(afterFile);
for (const [logicalId, prior] of before) {
  const current = after.get(logicalId);
  if (!current) throw new Error(`existing resource deleted: ${logicalId}`);
  if (
    current.ResourceType !== prior.ResourceType ||
    current.PhysicalResourceId !== prior.PhysicalResourceId
  ) {
    throw new Error(`existing resource identity changed: ${logicalId}`);
  }
}
NODE

capture_selector() {
  local name="$1" output="$2" value error_file="${TMP_DIR}/selector-error"
  if value="$(aws ssm get-parameter --name "$name" \
      --query Parameter.Value --output text 2>"$error_file")"; then
    sha="$(printf '%s' "$value" | {
      if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
    } | cut -d' ' -f1)"
    jq -n --arg name "$name" --arg sha "$sha" \
      '{name:$name,present:true,sha256:$sha}' >"$output"
  elif grep -q ParameterNotFound "$error_file"; then
    jq -n --arg name "$name" '{name:$name,present:false,sha256:null}' >"$output"
  else
    cat "$error_file" >&2
    fail "could not inspect selector ${name}"
  fi
}

ACTIVE_SELECTOR="$(jq -r .activeSelector <<<"$CONFIG")"
PREVIOUS_SELECTOR="$(jq -r .previousSelector <<<"$CONFIG")"
capture_selector "$ACTIVE_SELECTOR" "${TMP_DIR}/active-after.json"
capture_selector "$PREVIOUS_SELECTOR" "${TMP_DIR}/previous-after.json"
cmp -s "${EVIDENCE_DIR}/active-selector-before.json" "${TMP_DIR}/active-after.json" \
  || fail "active selector changed"
cmp -s "${EVIDENCE_DIR}/previous-selector-before.json" "${TMP_DIR}/previous-after.json" \
  || fail "previous selector changed"

lambda_image_uri() {
  aws lambda get-function --function-name "$1" --query Code.ImageUri --output text |
    tr -d '\r\n'
}
[[ "$(lambda_image_uri "$TRANSFORM_FUNCTION_BEFORE")" == "$TRANSFORM_IMAGE_URI_BEFORE" ]] \
  || fail "transform image URI changed"
[[ "$(lambda_image_uri "$BLUE_BM25_FUNCTION_BEFORE")" == "$BLUE_BM25_IMAGE_URI_BEFORE" ]] \
  || fail "blue BM25 image URI changed"
[[ "$(lambda_image_uri "$CHAT_FUNCTION_BEFORE")" == "$CHATBOT_IMAGE_URI_BEFORE" ]] \
  || fail "chatbot image URI changed"
aws lambda get-function-configuration --function-name "$CHAT_FUNCTION_BEFORE" \
  >"${TMP_DIR}/chatbot-config-after.json"
CHAT_CONFIG_SHA_AFTER="$(
  stable_lambda_config_sha "${TMP_DIR}/chatbot-config-after.json"
)"
[[ "$CHAT_CONFIG_SHA_AFTER" == "$CHAT_CONFIG_SHA_BEFORE" ]] \
  || fail "chatbot runtime configuration changed"

GREEN_BUCKET="$(jq -r '
  [.StackResources[] | select(
    .ResourceType == "AWS::S3::Bucket" and
    (.LogicalResourceId | test("GreenProcessedBucket"))
  )][0].PhysicalResourceId // empty
' "$RESOURCES_AFTER")"
[[ -n "$GREEN_BUCKET" ]] || fail "green processed bucket was not created"
[[ "$(aws s3api get-bucket-versioning --bucket "$GREEN_BUCKET" \
  --query Status --output text)" == "Enabled" ]] \
  || fail "green processed bucket is not versioned"
GREEN_OBJECT_COUNT="$(
  aws s3api list-objects-v2 --bucket "$GREEN_BUCKET" --output json |
    jq '(.Contents // []) | length'
)"
[[ "$GREEN_OBJECT_COUNT" == "0" ]] \
  || fail "green processed bucket is not empty"

while IFS= read -r queue_url; do
  [[ -n "$queue_url" ]] || continue
  depth="$(aws sqs get-queue-attributes --queue-url "$queue_url" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
      ApproximateNumberOfMessagesDelayed \
    --query 'Attributes' --output json |
    jq '[.[] | tonumber] | add // 0')"
  [[ "$depth" == "0" ]] || fail "green queue is not empty: ${queue_url}"
done < <(
  jq -r '
    .StackResources[] |
    select(
      .ResourceType == "AWS::SQS::Queue" and
      (.LogicalResourceId | test("Green"))
    ) |
    .PhysicalResourceId |
    if startswith("https://")
    then .
    else "https://sqs.eu-central-1.amazonaws.com/271033482134/" + .
    end
  ' "$RESOURCES_AFTER"
)

for slot in blue green; do
  base="/preprod/renate/retrieval/slots/${slot}"
  for coordinate in knowledge-base-id data-source-id processed-bucket-name \
    kb-sync-function-name bm25-builder-function-name bm25-rebuild-queue-arn \
    bm25-rebuild-dlq-arn; do
    value="$(aws ssm get-parameter --name "${base}/${coordinate}" \
      --query Parameter.Value --output text)"
    [[ -n "$value" && "$value" != None ]] \
      || fail "slot coordinate is empty: ${base}/${coordinate}"
  done
done

GREEN_KB_ID="$(aws ssm get-parameter \
  --name /preprod/renate/retrieval/slots/green/knowledge-base-id \
  --query Parameter.Value --output text)"
GREEN_DS_ID="$(aws ssm get-parameter \
  --name /preprod/renate/retrieval/slots/green/data-source-id \
  --query Parameter.Value --output text)"
[[ "$(aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id "$GREEN_KB_ID" --data-source-id "$GREEN_DS_ID" \
  --query 'length(ingestionJobSummaries)' --output text)" == "0" ]] \
  || fail "green data source has an unexpected ingestion job"

API_URL="$(aws cloudformation describe-stacks --stack-name "$CHATBOT_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue | [0]" --output text)"
FRONTEND_URL="$(aws cloudformation describe-stacks --stack-name "$CHATBOT_STACK" \
  --query "Stacks[0].Outputs[?contains(OutputKey, 'CloudFrontDistributionUrl')].OutputValue | [0]" \
  --output text)"
curl -fsS --max-time 30 "${API_URL}health" >/dev/null
curl -fsS --max-time 30 "${FRONTEND_URL}/" >/dev/null

cat >"${EVIDENCE_DIR}/preprod-foundation-post-deploy.md" <<EOF
# Preprod retrieval foundation post-deploy verification

- Issue evidence: ${ISSUE_641_EVIDENCE_URL}
- Existing logical and physical resource identities: unchanged
- Active and previous selectors: unchanged
- Transform, blue BM25, and chatbot image digests: unchanged
- Green processed bucket: versioned and empty
- Green queues and DLQ: empty
- Green ingestion jobs: none
- Health and frontend probes: passed
- Required operator follow-up: attach the fixed pre/post authenticated answer
  transcripts and confirm identical cited documents/chunks plus semantic
  equivalence. Byte-identical LLM prose is not required.
EOF

echo "preprod-foundation-deploy: deployment and automated invariants passed"
echo "preprod-foundation-deploy: attach preprod-foundation-post-deploy.md and answer transcripts to #641"
