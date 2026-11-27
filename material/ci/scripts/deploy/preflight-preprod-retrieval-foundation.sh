#!/usr/bin/env bash
set -euo pipefail

# Run all non-OIDC checks locally with:
# FOUNDATION_LOCAL_MODE=true \
#   FOUNDATION_OUTPUT_DIR=/private/tmp/641-local-evidence \
#   .gitlab/ci/scripts/preflight-preprod-retrieval-foundation.sh
# Live authorization-denial requests remain exclusive to the protected GitLab
# job. Read-only IAM policy simulations also run in local diagnostic mode.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
OUTPUT_DIR="${FOUNDATION_OUTPUT_DIR:-${REPO_ROOT}/preprod-foundation-evidence}"
EVIDENCE="${OUTPUT_DIR}/preprod-foundation-evidence.md"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$OUTPUT_DIR"
: >"$EVIDENCE"

LOCAL_MODE="${FOUNDATION_LOCAL_MODE:-false}"
QA_PROFILE="${FOUNDATION_QA_PROFILE:-digibro-eu-qa}"
PREPROD_PROFILE="${FOUNDATION_PREPROD_PROFILE:-digibro-eu-pp}"
DEV_PROFILE="${FOUNDATION_DEV_PROFILE:-digibro-eu-dev}"
JOB_ID="${CI_JOB_ID:-local}"

fail() {
  echo "preprod-foundation-preflight: $*" >&2
  exit 1
}

record() {
  printf -- '- %s\n' "$*" >>"$EVIDENCE"
  echo "preprod-foundation-preflight: $*"
}

sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

sha_json() {
  local normalized="${TMP_DIR}/normalized-$RANDOM.json"
  jq -S . "$1" >"$normalized"
  sha_file "$normalized"
}

stable_lambda_config_sha() {
  local config="$1" normalized="${TMP_DIR}/lambda-config-$RANDOM.json"
  # These fields describe Lambda's transient lifecycle state, not its deployed
  # configuration. A normal cold start can change Idle/Inactive to Active
  # without any infrastructure drift.
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
  sha_file "$normalized"
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool is missing: $1"
}

expect_denied() {
  local label="$1"
  shift
  local error_file="${TMP_DIR}/denied-$RANDOM.log"
  if "$@" >"$error_file" 2>&1; then
    fail "${label}: operation was unexpectedly authorized"
  fi
  if ! grep -Eqi 'AccessDenied|UnauthorizedOperation|not authorized' "$error_file"; then
    sed -E 's/(ASIA|AKIA)[A-Z0-9]+/[REDACTED]/g' "$error_file" >&2
    fail "${label}: failed for a reason other than an authorization denial"
  fi
  record "${label}: denied as required"
}

verify_denied() {
  local label="$1"
  shift
  if [[ "$LOCAL_MODE" == true ]]; then
    record "${label}: CI-only OIDC authorization check skipped in local diagnostic mode"
    return
  fi
  expect_denied "$label" "$@"
}

assert_simulated_denied() {
  local label="$1" action="$2" resource="$3" result_file decision
  result_file="${TMP_DIR}/policy-simulation-$RANDOM.json"
  promotion_aws iam simulate-principal-policy \
    --policy-source-arn "$PREPROD_ROLE" \
    --action-names "$action" \
    --resource-arns "$resource" \
    --output json >"$result_file"
  [[ "$(jq '.EvaluationResults | length' "$result_file")" == 1 ]] \
    || fail "${label}: IAM policy simulation returned an unexpected result count"
  [[ "$(jq -r '.EvaluationResults[0].EvalActionName' "$result_file")" == "$action" ]] \
    || fail "${label}: IAM policy simulation returned the wrong action"
  [[ "$(jq -r '.EvaluationResults[0].EvalResourceName' "$result_file")" == "$resource" ]] \
    || fail "${label}: IAM policy simulation returned the wrong resource"
  decision="$(jq -r '.EvaluationResults[0].EvalDecision' "$result_file")"
  case "$decision" in
    explicitDeny | implicitDeny)
      record "${label}: ${decision} as required by effective role-policy simulation"
      ;;
    allowed)
      fail "${label}: maintenance action was unexpectedly authorized"
      ;;
    *)
      fail "${label}: IAM policy simulation returned unexpected decision ${decision}"
      ;;
  esac
}

assume_oidc() {
  local role_arn="$1" suffix="$2" credentials
  credentials="$(aws sts assume-role-with-web-identity \
    --role-arn "$role_arn" \
    --role-session-name "gitlab-${JOB_ID}-${suffix}" \
    --web-identity-token "$GITLAB_OIDC_TOKEN" \
    --duration-seconds 7200 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text)"
  read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN <<<"$credentials"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  [[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" && -n "$AWS_SESSION_TOKEN" ]] \
    || fail "could not assume ${role_arn}"
}

select_identity() {
  local role_arn="$1" suffix="$2" profile="$3"
  if [[ "$LOCAL_MODE" == true ]]; then
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    export AWS_PROFILE="$profile"
    record "Local diagnostic identity selected through AWS profile ${profile}"
  else
    unset AWS_PROFILE
    assume_oidc "$role_arn" "$suffix"
  fi
}

promotion_aws() {
  if [[ "$LOCAL_MODE" == true ]]; then
    AWS_PROFILE="$PREPROD_PROFILE" aws "$@"
  else
    AWS_ACCESS_KEY_ID="$PROMOTION_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$PROMOTION_SECRET_ACCESS_KEY" \
    AWS_SESSION_TOKEN="$PROMOTION_SESSION_TOKEN" \
      aws "$@"
  fi
}

assert_account() {
  local expected="$1" actual
  actual="$(aws sts get-caller-identity --query Account --output text)"
  [[ "$actual" == "$expected" ]] \
    || fail "caller account ${actual} does not match expected ${expected}"
  if [[ "$LOCAL_MODE" == true ]]; then
    record "Local profile caller account verified: ${expected}"
  else
    record "OIDC caller account verified: ${expected}"
  fi
}

capture_selector() {
  local name="$1" output="$2" value error_file
  error_file="${TMP_DIR}/selector-error"
  if value="$(aws ssm get-parameter --name "$name" \
      --query Parameter.Value --output text 2>"$error_file")"; then
    jq -n --arg name "$name" --arg sha "$(printf '%s' "$value" | {
      if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
    } | cut -d' ' -f1)" \
      '{name:$name,present:true,sha256:$sha}' >"$output"
  elif grep -q ParameterNotFound "$error_file"; then
    jq -n --arg name "$name" '{name:$name,present:false,sha256:null}' >"$output"
  else
    cat "$error_file" >&2
    fail "could not inspect selector ${name}"
  fi
}

image_digest() {
  local image_uri="$1" registry_id region repository tag digest
  local access_key secret_key session_token
  if [[ "$image_uri" =~ @sha256:([0-9a-f]{64})$ ]]; then
    printf 'sha256:%s\n' "${BASH_REMATCH[1]}"
    return
  fi
  if [[ ! "$image_uri" =~ ^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/(.+):([^/:]+)$ ]]; then
    fail "Lambda image URI is neither digest- nor ECR tag-addressed"
  fi
  registry_id="${BASH_REMATCH[1]}"
  region="${BASH_REMATCH[2]}"
  repository="${BASH_REMATCH[3]}"
  tag="${BASH_REMATCH[4]}"
  if [[ "$registry_id" == "$PREPROD_ACCOUNT" ]]; then
    access_key="$ECR_ACCESS_KEY_ID"
    secret_key="$ECR_SECRET_ACCESS_KEY"
    session_token="$ECR_SESSION_TOKEN"
  elif [[ "$LOCAL_MODE" == true ]]; then
    digest="$(
      AWS_PROFILE="$DEV_PROFILE" aws ecr describe-images \
        --region "$region" \
        --registry-id "$registry_id" \
        --repository-name "$repository" \
        --image-ids "imageTag=${tag}" \
        --query 'imageDetails[0].imageDigest' \
        --output text
    )"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] \
      || fail "could not resolve immutable digest for Lambda ECR image tag"
    printf '%s\n' "$digest"
    return
  else
    access_key="$PROMOTION_ACCESS_KEY_ID"
    secret_key="$PROMOTION_SECRET_ACCESS_KEY"
    session_token="$PROMOTION_SESSION_TOKEN"
  fi
  digest="$(
    AWS_ACCESS_KEY_ID="$access_key" \
    AWS_SECRET_ACCESS_KEY="$secret_key" \
    AWS_SESSION_TOKEN="$session_token" \
      aws ecr describe-images \
        --region "$region" \
        --registry-id "$registry_id" \
        --repository-name "$repository" \
        --image-ids "imageTag=${tag}" \
        --query 'imageDetails[0].imageDigest' \
        --output text
  )"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail "could not resolve immutable digest for Lambda ECR image tag"
  printf '%s\n' "$digest"
}

image_repository() {
  local image_uri="$1"
  [[ "$image_uri" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/(.+)(:([^/:]+)|@sha256:[0-9a-f]{64})$ ]] \
    || fail "Lambda image URI is not a supported ECR coordinate"
  printf '%s\n' "${BASH_REMATCH[1]%:*}"
}

image_coordinate() {
  local image_uri="$1"
  if [[ "$image_uri" =~ @((sha256:)[0-9a-f]{64})$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  elif [[ "$image_uri" =~ :([^/:]+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    fail "Lambda image URI has no immutable deployment coordinate"
  fi
}

exercise_ecr_pull_api() {
  local repository="$1" digest="$2" manifest layer
  local -a ecr_command=(aws)
  if [[ "$LOCAL_MODE" == true ]]; then
    ecr_command=(aws --profile "$DEV_PROFILE")
  fi
  "${ecr_command[@]}" ecr describe-images \
    --registry-id 831926590742 \
    --repository-name "$repository" \
    --image-ids "imageDigest=${digest}" >/dev/null
  manifest="$("${ecr_command[@]}" ecr batch-get-image \
    --registry-id 831926590742 \
    --repository-name "$repository" \
    --image-ids "imageDigest=${digest}" \
    --accepted-media-types application/vnd.docker.distribution.manifest.v2+json \
    --query 'images[0].imageManifest' --output text)"
  layer="$(jq -r '.layers[0].digest // empty' <<<"$manifest")"
  [[ "$layer" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail "could not resolve an ECR layer for ${repository}@${digest}"
  "${ecr_command[@]}" ecr get-download-url-for-layer \
    --registry-id 831926590742 \
    --repository-name "$repository" \
    --layer-digest "$layer" >/dev/null
  record "Dev ECR describe, manifest-read, and layer-URL APIs passed for ${repository}@${digest}"
}

for tool in aws jq node npm npx curl; do
  require_tool "$tool"
done

if [[ "$LOCAL_MODE" != true && "$LOCAL_MODE" != false ]]; then
  fail "FOUNDATION_LOCAL_MODE must be true or false"
fi
if [[ "$LOCAL_MODE" == false ]]; then
  : "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
  : "${CI_JOB_ID:?CI_JOB_ID is required}"
fi
if [[ -n "${CI:-}" ]]; then
  [[ "$LOCAL_MODE" == false ]] || fail "local diagnostic mode is not allowed in CI"
  [[ "${CI_COMMIT_BRANCH:-}" == "${CI_DEFAULT_BRANCH:-main}" ]] || fail "must run from the default branch (${CI_DEFAULT_BRANCH:-main})"
  [[ "${CI_PIPELINE_SOURCE:-}" == "web" ]] || fail "must run from a web pipeline"
  [[ "${PIPELINE_TASK:-}" == "preprod-retrieval-foundation" ]] \
    || fail "PIPELINE_TASK must be preprod-retrieval-foundation"
fi

CONFIG="$(node "${SCRIPT_DIR}/../lib/node/retrieval-environment.mjs" json preprod)"
QA_SOURCE_ROLE="$(jq -r .sourceReaderRoleArn <<<"$CONFIG")"
PREPROD_ROLE="$(jq -r .promotionRoleArn <<<"$CONFIG")"
PREPROD_ACCOUNT="$(jq -r .accountId <<<"$CONFIG")"
QA_ACCOUNT="$(jq -r .sourceAccountId <<<"$CONFIG")"
ETL_STACK="$(jq -r .etlStackName <<<"$CONFIG")"
CHATBOT_STACK="$(jq -r .chatbotStackName <<<"$CONFIG")"
ACTIVE_SELECTOR="$(jq -r .activeSelector <<<"$CONFIG")"
PREVIOUS_SELECTOR="$(jq -r .previousSelector <<<"$CONFIG")"
METRIC_NAMESPACE="$(jq -r .metricNamespace <<<"$CONFIG")"
QA_SOURCE_BUCKET="${QA_RETRIEVAL_SOURCE_BUCKET:-renate-s3-etl-source-dev-ef024612}"
DEV_SOURCE_BUCKET="${DEV_RETRIEVAL_SOURCE_BUCKET:-renate-s3-etl-source-dev-102d01b4}"
DATA_ARTIFACT_VERSION="$(awk '$1 == "data_artifact_version:" {print $2}' \
  "${REPO_ROOT}/deployments/qa/version.yaml")"
[[ -n "$DATA_ARTIFACT_VERSION" ]] || fail "QA data_artifact_version is missing"

{
  printf '# Preprod retrieval foundation preflight\n\n'
  # Backticks are literal Markdown delimiters; the values are separate args.
  # shellcheck disable=SC2016
  printf -- '- Commit: `%s`\n' "${CI_COMMIT_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
  # shellcheck disable=SC2016
  printf -- '- Pipeline: `%s`\n' "${CI_PIPELINE_ID:-local}"
  # shellcheck disable=SC2016
  printf -- '- Job: `%s`\n' "$JOB_ID"
  printf -- '- Mode: %s\n' "$([[ "$LOCAL_MODE" == true ]] && printf local-diagnostic || printf protected-ci)"
} >>"$EVIDENCE"

# QA durable-source boundary.
select_identity "$QA_SOURCE_ROLE" qa-source-reader "$QA_PROFILE"
assert_account "$QA_ACCOUNT"

COMPOSITE_MANIFEST="${TMP_DIR}/qa-composite-manifest.json"
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
if ! qa_retrieval_composite_manifest_complete \
    "$QA_SOURCE_BUCKET" "releases/${DATA_ARTIFACT_VERSION}/" "$COMPOSITE_MANIFEST"; then
  fail "selected QA composite manifest or a declared component object is incomplete"
fi

OBJECT_INVENTORY="${OUTPUT_DIR}/qa-source-object-inventory.jsonl"
: >"$OBJECT_INVENTORY"
for component in brochure faq; do
  COMPONENT_JSON="$(jq -c ".components.${component}" "$COMPOSITE_MANIFEST")"
  COMPONENT_KEY="$(jq -r .manifest_key <<<"$COMPONENT_JSON")"
  COMPONENT_PREFIX="$(jq -r .prefix <<<"$COMPONENT_JSON")"
  COMPONENT_FILE="${TMP_DIR}/${component}-manifest.json"
  aws s3 cp "s3://${QA_SOURCE_BUCKET}/${COMPONENT_KEY}" "$COMPONENT_FILE" \
    --only-show-errors
  EXPECTED_SHA="$(jq -r .manifest_sha256 <<<"$COMPONENT_JSON")"
  [[ "$(sha_file "$COMPONENT_FILE")" == "$EXPECTED_SHA" ]] \
    || fail "${component} manifest hash mismatch"
  while IFS= read -r relative; do
    [[ -n "$relative" ]] || continue
    key="${COMPONENT_PREFIX}${relative}"
    head="$(aws s3api head-object --bucket "$QA_SOURCE_BUCKET" --key "$key")"
    aws s3api get-object --bucket "$QA_SOURCE_BUCKET" --key "$key" \
      --range bytes=0-0 "${TMP_DIR}/probe-byte" >/dev/null
    jq -cn --arg key "$key" \
      --arg etag "$(jq -r .ETag <<<"$head")" \
      --argjson bytes "$(jq -r .ContentLength <<<"$head")" \
      '{key:$key,etag:$etag,bytes:$bytes}' >>"$OBJECT_INVENTORY"
  done < <(
    jq -r '
      if (.files | type) == "object"
      then .files | to_entries[] | .value[]
      else .files[]
      end
    ' "$COMPONENT_FILE"
  )
done
record "QA composite, both component manifests, and $(wc -l <"$OBJECT_INVENTORY" | tr -d ' ') declared objects are readable"

verify_denied "QA source write boundary" \
  aws s3api put-object \
    --bucket "$QA_SOURCE_BUCKET" \
    --key "releases/${DATA_ARTIFACT_VERSION}/manifest.json" \
    --body "$COMPOSITE_MANIFEST" \
    --if-none-match '*'
FIRST_COMPONENT_KEY="$(jq -r '.components.brochure.manifest_key' "$COMPOSITE_MANIFEST")"
verify_denied "Direct dev raw-corpus read boundary" \
  aws s3api get-object \
    --bucket "$DEV_SOURCE_BUCKET" \
    --key "$FIRST_COMPONENT_KEY" \
    --range bytes=0-0 "${TMP_DIR}/dev-probe"

# Preprod deployment/read boundary.
select_identity "$PREPROD_ROLE" preprod-foundation "$PREPROD_PROFILE"
assert_account "$PREPROD_ACCOUNT"
if [[ "$LOCAL_MODE" == false ]]; then
  PROMOTION_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
  PROMOTION_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
  PROMOTION_SESSION_TOKEN="$AWS_SESSION_TOKEN"
fi

for region in eu-central-1 us-east-1; do
  aws ssm get-parameter --region "$region" \
    --name /cdk-bootstrap/hnb659fds/version >/dev/null
  for role_kind in deploy lookup file-publishing image-publishing; do
    role_arn="arn:aws:iam::${PREPROD_ACCOUNT}:role/cdk-hnb659fds-${role_kind}-role-${PREPROD_ACCOUNT}-${region}"
    promotion_aws sts assume-role --role-arn "$role_arn" \
      --role-session-name "gitlab-${JOB_ID}-${role_kind}-${region}" \
      --duration-seconds 900 \
      --query 'Credentials.Expiration' --output text >/dev/null
  done
done
record "Both bootstrap versions and all eight regional bootstrap roles are readable/assumable"

CURRENT_TEMPLATE="${OUTPUT_DIR}/preprod-etl-current-template.json"
ETL_RESOURCES="${OUTPUT_DIR}/preprod-etl-stack-resources.json"
CHATBOT_RESOURCES="${OUTPUT_DIR}/preprod-chatbot-stack-resources.json"
CFN_DEPLOY_ROLE="arn:aws:iam::${PREPROD_ACCOUNT}:role/cdk-hnb659fds-deploy-role-${PREPROD_ACCOUNT}-eu-central-1"
read -r CFN_ACCESS_KEY_ID CFN_SECRET_ACCESS_KEY CFN_SESSION_TOKEN < <(
  promotion_aws sts assume-role --role-arn "$CFN_DEPLOY_ROLE" \
    --role-session-name "gitlab-${JOB_ID}-foundation-template-read" \
    --duration-seconds 900 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text
)
[[ -n "$CFN_ACCESS_KEY_ID" && -n "$CFN_SECRET_ACCESS_KEY" && -n "$CFN_SESSION_TOKEN" ]] \
  || fail "CDK deploy role returned incomplete credentials for template inspection"
ECR_IMAGE_ROLE="arn:aws:iam::${PREPROD_ACCOUNT}:role/cdk-hnb659fds-image-publishing-role-${PREPROD_ACCOUNT}-eu-central-1"
read -r ECR_ACCESS_KEY_ID ECR_SECRET_ACCESS_KEY ECR_SESSION_TOKEN < <(
  promotion_aws sts assume-role --role-arn "$ECR_IMAGE_ROLE" \
    --role-session-name "gitlab-${JOB_ID}-foundation-image-read" \
    --duration-seconds 900 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text
)
[[ -n "$ECR_ACCESS_KEY_ID" && -n "$ECR_SECRET_ACCESS_KEY" && -n "$ECR_SESSION_TOKEN" ]] \
  || fail "CDK image-publishing role returned incomplete credentials for digest resolution"
cloudformation_get_template() {
  local stack_name="$1" output_file="$2"
  AWS_ACCESS_KEY_ID="$CFN_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$CFN_SECRET_ACCESS_KEY" \
  AWS_SESSION_TOKEN="$CFN_SESSION_TOKEN" \
    aws cloudformation get-template --stack-name "$stack_name" >"$output_file"
}
cloudformation_list_stack_resources() {
  local stack_name="$1" output_file="$2"
  AWS_ACCESS_KEY_ID="$CFN_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$CFN_SECRET_ACCESS_KEY" \
  AWS_SESSION_TOKEN="$CFN_SESSION_TOKEN" \
    aws cloudformation list-stack-resources --stack-name "$stack_name" |
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
    }' >"$output_file"
}
cloudformation_get_template "$ETL_STACK" "$CURRENT_TEMPLATE"
cloudformation_list_stack_resources "$ETL_STACK" "$ETL_RESOURCES"
cloudformation_list_stack_resources "$CHATBOT_STACK" "$CHATBOT_RESOURCES"
cloudformation_get_template "$CHATBOT_STACK" \
  "${OUTPUT_DIR}/preprod-chatbot-current-template.json"

TRANSFORM_FUNCTION="$(jq -r '
  [.StackResources[] | select(
    .ResourceType == "AWS::Lambda::Function" and
    (.LogicalResourceId | test("Transform.*Lambda"; "i"))
  )][0].PhysicalResourceId // empty
' "$ETL_RESOURCES")"
BLUE_BM25_FUNCTION="$(jq -r '
  [.StackResources[] | select(
    .ResourceType == "AWS::Lambda::Function" and
    (.LogicalResourceId | test("Bm25IndexBuilder.*BuilderLambda"; "i")) and
    (.LogicalResourceId | test("Green"; "i") | not)
  )][0].PhysicalResourceId // empty
' "$ETL_RESOURCES")"
CHAT_FUNCTION="$(jq -r '
  [.StackResources[] | select(
    .ResourceType == "AWS::Lambda::Function" and
    (.LogicalResourceId | test("ChatHandler"; "i"))
  )][0].PhysicalResourceId // empty
' "$CHATBOT_RESOURCES")"
[[ -n "$TRANSFORM_FUNCTION" && -n "$BLUE_BM25_FUNCTION" && -n "$CHAT_FUNCTION" ]] \
  || fail "could not resolve deployed transform, blue BM25, and chatbot functions"

TRANSFORM_IMAGE="$(aws lambda get-function --function-name "$TRANSFORM_FUNCTION" \
  --query Code.ImageUri --output text)"
BLUE_BM25_IMAGE="$(aws lambda get-function --function-name "$BLUE_BM25_FUNCTION" \
  --query Code.ImageUri --output text)"
CHATBOT_IMAGE="$(aws lambda get-function --function-name "$CHAT_FUNCTION" \
  --query Code.ImageUri --output text)"
CHATBOT_CONFIG="${OUTPUT_DIR}/preprod-chatbot-function-config.json"
aws lambda get-function-configuration --function-name "$CHAT_FUNCTION" \
  >"$CHATBOT_CONFIG"
CHATBOT_CONFIG_SHA="$(stable_lambda_config_sha "$CHATBOT_CONFIG")"
LEGACY_ETL_DIGEST="$(image_digest "$TRANSFORM_IMAGE")"
[[ "$BLUE_BM25_IMAGE" == "$TRANSFORM_IMAGE" ]] \
  || fail "transform and blue BM25 do not use the exact same legacy ETL image"
LEGACY_ETL_REPOSITORY="$(image_repository "$TRANSFORM_IMAGE")"
LEGACY_ETL_IMAGE_COORDINATE="$(image_coordinate "$TRANSFORM_IMAGE")"
EXPECTED_LEGACY_REPOSITORY="cdk-hnb659fds-container-assets-${PREPROD_ACCOUNT}-eu-central-1"
[[ "$LEGACY_ETL_REPOSITORY" == "$EXPECTED_LEGACY_REPOSITORY" ]] \
  || fail "legacy ETL image is not in the expected preprod CDK asset repository"
CHATBOT_DIGEST="$(image_digest "$CHATBOT_IMAGE")"
QA_ETL_IMAGE_TAG="$(awk '$1 == "etl_version:" {print $2}' \
  "${REPO_ROOT}/deployments/qa/version.yaml")"
[[ -n "$QA_ETL_IMAGE_TAG" ]] || fail "QA etl_version is missing"
QA_ETL_DIGEST="$(image_digest \
  "831926590742.dkr.ecr.eu-central-1.amazonaws.com/renate-etl-lambda:${QA_ETL_IMAGE_TAG}")"
exercise_ecr_pull_api renate-etl-lambda "$QA_ETL_DIGEST"
exercise_ecr_pull_api renate-chat-lambda "$CHATBOT_DIGEST"

capture_selector "$ACTIVE_SELECTOR" "${OUTPUT_DIR}/active-selector-before.json"
capture_selector "$PREVIOUS_SELECTOR" "${OUTPUT_DIR}/previous-selector-before.json"

KVS_ARN="$(aws cloudformation describe-stacks --stack-name "$CHATBOT_STACK" \
  --query "Stacks[0].Outputs[?contains(OutputKey, 'MaintenanceModeStoreArn')].OutputValue | [0]" \
  --output text)"
if [[ -z "$KVS_ARN" || "$KVS_ARN" == None ]]; then
  record "Legacy preprod chatbot has no maintenance KVS, as expected for version 1.83.3"
  KVS_ARN="arn:aws:cloudfront::${PREPROD_ACCOUNT}:key-value-store/preprod-foundation-absent-probe"
fi
assert_simulated_denied \
  "Maintenance KVS update boundary" \
  "cloudfront-keyvaluestore:UpdateKeys" \
  "$KVS_ARN"
CHAT_FUNCTION_ARN="arn:aws:lambda:eu-central-1:${PREPROD_ACCOUNT}:function:${CHAT_FUNCTION}"
assert_simulated_denied \
  "Maintenance concurrency enable boundary" \
  "lambda:PutFunctionConcurrency" \
  "$CHAT_FUNCTION_ARN"
assert_simulated_denied \
  "Maintenance concurrency disable boundary" \
  "lambda:DeleteFunctionConcurrency" \
  "$CHAT_FUNCTION_ARN"

while IFS= read -r function_name; do
  [[ -n "$function_name" ]] || continue
  verify_denied "Restricted Lambda invocation boundary (${function_name})" \
    aws lambda invoke --function-name "$function_name" \
      --invocation-type DryRun "${TMP_DIR}/dry-run-response"
done < <(
  jq -r '
    .StackResources[] |
    select(
      .ResourceType == "AWS::Lambda::Function" and
      (.LogicalResourceId | test("SourceReprocess|CleanupFunction"; "i"))
    ) |
    .PhysicalResourceId
  ' "$ETL_RESOURCES"
)

INVENTORY="${OUTPUT_DIR}/preprod-live-inventory.json"
jq -n \
  --slurpfile etl "$ETL_RESOURCES" \
  --slurpfile chatbot "$CHATBOT_RESOURCES" \
  '{etl_stack_resources:$etl[0].StackResources,chatbot_stack_resources:$chatbot[0].StackResources}' \
  >"$INVENTORY"

jq '.queue_attributes=[] | .lambda_configurations=[]' "$INVENTORY" \
  >"${TMP_DIR}/inventory" && mv "${TMP_DIR}/inventory" "$INVENTORY"

while IFS= read -r queue_id; do
  [[ -n "$queue_id" ]] || continue
  if [[ "$queue_id" == https://* ]]; then
    queue_url="$queue_id"
  else
    queue_url="https://sqs.eu-central-1.amazonaws.com/${PREPROD_ACCOUNT}/${queue_id}"
  fi
  attributes="$(aws sqs get-queue-attributes --queue-url "$queue_url" \
    --attribute-names All --output json)"
  jq --arg url "$queue_url" --argjson attributes "$attributes" \
    '.queue_attributes += [{queue_url:$url,attributes:$attributes.Attributes}]' \
    "$INVENTORY" >"${TMP_DIR}/inventory" &&
    mv "${TMP_DIR}/inventory" "$INVENTORY"
done < <(
  jq -r '.StackResources[] | select(.ResourceType=="AWS::SQS::Queue") | .PhysicalResourceId' \
    "$ETL_RESOURCES"
)

while IFS= read -r function_name; do
  [[ -n "$function_name" ]] || continue
  configuration="$(aws lambda get-function-configuration \
    --function-name "$function_name")"
  environment_sha="$(jq -cS '.Environment.Variables // {}' <<<"$configuration" |
    {
      if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
    } | cut -d' ' -f1)"
  summary="$(jq -c \
    --arg environment_sha "$environment_sha" \
    '{
      function_name:.FunctionName,
      package_type:.PackageType,
      code_sha256:.CodeSha256,
      last_modified:.LastModified,
      environment_sha256:$environment_sha
    }' <<<"$configuration")"
  jq --argjson summary "$summary" \
    '.lambda_configurations += [$summary]' "$INVENTORY" \
    >"${TMP_DIR}/inventory" && mv "${TMP_DIR}/inventory" "$INVENTORY"
done < <(
  jq -r '.StackResources[] | select(.ResourceType=="AWS::Lambda::Function") | .PhysicalResourceId' \
    "$ETL_RESOURCES"
)

while IFS= read -r bucket; do
  [[ -n "$bucket" ]] || continue
  if lifecycle="$(aws s3api get-bucket-lifecycle-configuration \
      --bucket "$bucket" 2>"${TMP_DIR}/lifecycle-error")"; then
    jq --arg bucket "$bucket" --argjson lifecycle "$lifecycle" \
      '.s3_lifecycle[$bucket]=$lifecycle' "$INVENTORY" >"${TMP_DIR}/inventory" &&
      mv "${TMP_DIR}/inventory" "$INVENTORY"
  elif grep -q NoSuchLifecycleConfiguration "${TMP_DIR}/lifecycle-error"; then
    jq --arg bucket "$bucket" '.s3_lifecycle[$bucket]={Rules:[]}' \
      "$INVENTORY" >"${TMP_DIR}/inventory" &&
      mv "${TMP_DIR}/inventory" "$INVENTORY"
  else
    cat "${TMP_DIR}/lifecycle-error" >&2
    fail "could not inspect lifecycle for ${bucket}"
  fi
done < <(
  jq -r '.StackResources[] | select(.ResourceType=="AWS::S3::Bucket") | .PhysicalResourceId' \
    "$ETL_RESOURCES"
)

aws bedrock-agent list-knowledge-bases \
  >"${OUTPUT_DIR}/preprod-bedrock-knowledge-bases.json"
jq -n '{knowledge_bases:[]}' >"${OUTPUT_DIR}/preprod-bedrock-data-sources.json"
while IFS= read -r knowledge_base_id; do
  [[ -n "$knowledge_base_id" ]] || continue
  data_sources="$(aws bedrock-agent list-data-sources \
    --knowledge-base-id "$knowledge_base_id")"
  jq --arg id "$knowledge_base_id" --argjson data_sources "$data_sources" \
    '.knowledge_bases += [{knowledge_base_id:$id,data_sources:$data_sources.dataSourceSummaries}]' \
    "${OUTPUT_DIR}/preprod-bedrock-data-sources.json" \
    >"${TMP_DIR}/bedrock-data-sources" &&
    mv "${TMP_DIR}/bedrock-data-sources" \
      "${OUTPUT_DIR}/preprod-bedrock-data-sources.json"
done < <(
  jq -r '.knowledgeBaseSummaries[]?.knowledgeBaseId' \
    "${OUTPUT_DIR}/preprod-bedrock-knowledge-bases.json"
)
aws s3vectors list-vector-buckets \
  >"${OUTPUT_DIR}/preprod-vector-buckets.json"
aws cloudwatch list-metrics --namespace "$METRIC_NAMESPACE" \
  >"${OUTPUT_DIR}/preprod-retrieval-health-metrics.json"
record "Legacy stacks, storage lifecycle, queues/Lambdas, Bedrock/vector resources, selectors, health namespace, and retention boundary inventoried"

CONTEXT_ARGS=(
  --context env=preprod
  --context retrievalCandidateSlot=blue
  --context "etlImageRepository=${LEGACY_ETL_REPOSITORY}"
  --context "etlImageTag=${LEGACY_ETL_IMAGE_COORDINATE}"
  --context "blueEtlImageTag=${LEGACY_ETL_IMAGE_COORDINATE}"
  --context "greenEtlImageTag=${LEGACY_ETL_IMAGE_COORDINATE}"
)
CDK_OUTPUT="${OUTPUT_DIR}/cdk.out"
rm -rf "$CDK_OUTPUT"
(
  cd "${REPO_ROOT}/cdk"
  npx cdk synth "$ETL_STACK" --exclusively \
    --output "$CDK_OUTPUT" "${CONTEXT_ARGS[@]}" >/dev/null
)
SYNTH_TEMPLATE="${CDK_OUTPUT}/${ETL_STACK}.template.json"
RAW_SYNTH_TEMPLATE="${OUTPUT_DIR}/preprod-foundation-raw-synth.template.json"
mv "$SYNTH_TEMPLATE" "$RAW_SYNTH_TEMPLATE"
node "${SCRIPT_DIR}/../lib/node/preprod-foundation-diff.mjs" prepare \
  "$CURRENT_TEMPLATE" "$RAW_SYNTH_TEMPLATE" "$SYNTH_TEMPLATE"
node "${SCRIPT_DIR}/../lib/node/preprod-foundation-diff.mjs" \
  "$CURRENT_TEMPLATE" "$SYNTH_TEMPLATE" \
  >"${OUTPUT_DIR}/preprod-foundation-diff-summary.json"
cp "${OUTPUT_DIR}/preprod-foundation-diff-summary.json" \
  "${OUTPUT_DIR}/preprod-foundation.diff"
record "Additive structural CDK template diff accepted without an AWS change set"

cat >"${OUTPUT_DIR}/preprod-foundation-context.env" <<EOF
LEGACY_ETL_DIGEST=${LEGACY_ETL_DIGEST}
LEGACY_ETL_REPOSITORY=${LEGACY_ETL_REPOSITORY}
LEGACY_ETL_IMAGE_COORDINATE=${LEGACY_ETL_IMAGE_COORDINATE}
TRANSFORM_IMAGE_URI_BEFORE=${TRANSFORM_IMAGE}
BLUE_BM25_IMAGE_URI_BEFORE=${BLUE_BM25_IMAGE}
CHATBOT_IMAGE_URI_BEFORE=${CHATBOT_IMAGE}
CHATBOT_DIGEST_BEFORE=${CHATBOT_DIGEST}
TRANSFORM_FUNCTION_BEFORE=${TRANSFORM_FUNCTION}
BLUE_BM25_FUNCTION_BEFORE=${BLUE_BM25_FUNCTION}
CHAT_FUNCTION_BEFORE=${CHAT_FUNCTION}
CHAT_CONFIG_SHA_BEFORE=${CHATBOT_CONFIG_SHA}
ETL_STACK=${ETL_STACK}
CHATBOT_STACK=${CHATBOT_STACK}
EOF

jq -n \
  --arg commit "${CI_COMMIT_SHA:-$(git -C "$REPO_ROOT" rev-parse HEAD)}" \
  --arg currentTemplateSha "$(sha_json "$CURRENT_TEMPLATE")" \
  --arg reviewedTemplateSha "$(sha_json "$SYNTH_TEMPLATE")" \
  --arg liveInventorySha "$(sha_json "$INVENTORY")" \
  --arg etlDigest "$LEGACY_ETL_DIGEST" \
  --arg chatbotDigest "$CHATBOT_DIGEST" \
  --arg chatbotConfigSha "$CHATBOT_CONFIG_SHA" \
  --slurpfile active "${OUTPUT_DIR}/active-selector-before.json" \
  --slurpfile previous "${OUTPUT_DIR}/previous-selector-before.json" \
  '{
    commit:$commit,
    current_template_sha256:$currentTemplateSha,
    reviewed_template_sha256:$reviewedTemplateSha,
    live_inventory_sha256:$liveInventorySha,
    etl_digest:$etlDigest,
    chatbot_digest:$chatbotDigest,
    chatbot_config_sha256:$chatbotConfigSha,
    active_selector:$active[0],
    previous_selector:$previous[0]
  }' >"${OUTPUT_DIR}/preprod-foundation-state.json"
sha_file "${OUTPUT_DIR}/preprod-foundation-state.json" \
  >"${OUTPUT_DIR}/preprod-foundation-state.sha256"

record "Sanitized state hash: $(cat "${OUTPUT_DIR}/preprod-foundation-state.sha256")"
record "Preflight passed; attach this evidence to issue #641 before deployment"
