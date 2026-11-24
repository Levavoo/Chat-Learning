#!/usr/bin/env bash
set -euo pipefail

# TKT-REV-05 — Idempotent cleanup for a branch review environment.
#
# Deletes (in order): API Gateway → Lambda → S3 prefix → ECR image → DynamoDB items.
# Verifies each resource is gone after deletion.
# Idempotency: 404/NotFound on any resource is treated as success.
#
# Used by two CI jobs:
#   review:teardown     — manual Stop button (GIT_STRATEGY: none)
#   review:auto-cleanup — auto-triggered on trigger-file deletion

# --- Required environment variables ------------------------------------------
: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"
: "${CI_COMMIT_SHORT_SHA:?CI_COMMIT_SHORT_SHA is required}"
: "${REVIEW_ASSETS_BUCKET:?REVIEW_ASSETS_BUCKET is required}"
: "${REVIEW_CF_DISTRIBUTION_ID:?REVIEW_CF_DISTRIBUTION_ID is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${ROLE_ARN:?ROLE_ARN is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"

# --- Derived names (must match review-deploy-backend.sh exactly) -------------
# shellcheck disable=SC1091
source "$(dirname "$0")/../lib/review-names.sh"
# shellcheck disable=SC1091
source "$(dirname "$0")/../lib/log.sh"
# Conversation table: resolved from the review Lambda's env below. CDK names it
# "<prefix>-conversations-<env>" (cdk/lib/constructs/dynamodb.ts); the review
# Lambda clones the dev function's DYNAMODB_TABLE_NAME. Fallback matches dev.

echo "Review function:  ${FUNC}"
echo "Review API name:  ${API_NAME}"
echo "DynamoDB prefix:  ${DDB_PREFIX}"

# --- OIDC: assume role --------------------------------------------------------
echo "Assuming role: ${ROLE_ARN}"
STS_OUTPUT=$(aws sts assume-role-with-web-identity \
  --role-arn "${ROLE_ARN}" \
  --role-session-name "gitlab-ci-${CI_JOB_ID}" \
  --web-identity-token "${GITLAB_OIDC_TOKEN}" \
  --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
  --output text) || { echo "STS assume-role failed (see error above)"; exit 1; }

read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  <<< "${STS_OUTPUT}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

[[ -n "${AWS_ACCESS_KEY_ID}" && -n "${AWS_SECRET_ACCESS_KEY}" \
  && -n "${AWS_SESSION_TOKEN}" ]] \
  || { echo "STS assume-role failed: empty credentials"; exit 1; }

aws sts get-caller-identity

# --- Read Lambda env (SHA + table name) before deleting the function ---------
# Both are read from the deployed review Lambda's environment. The table name
# is cloned from the dev function by review-deploy-backend.sh, so it reflects
# the real conversation table rather than the conversation.py fallback default.
REVIEW_DEPLOY_SHA=""
if aws lambda get-function-configuration --function-name "${FUNC}" \
     --query 'Environment.Variables.REVIEW_DEPLOY_SHA' --output text \
     > /tmp/review_sha_out 2>/dev/null; then
  REVIEW_DEPLOY_SHA=$(cat /tmp/review_sha_out)
fi
[ "${REVIEW_DEPLOY_SHA}" = "None" ] && REVIEW_DEPLOY_SHA=""
echo "REVIEW_DEPLOY_SHA: ${REVIEW_DEPLOY_SHA:-<not found>}"

DDB_TABLE="${DDB_TABLE_DEFAULT}"
if aws lambda get-function-configuration --function-name "${FUNC}" \
     --query 'Environment.Variables.DYNAMODB_TABLE_NAME' --output text \
     > /tmp/review_ddb_out 2>/dev/null; then
  _ddb=$(cat /tmp/review_ddb_out)
  [ -n "${_ddb}" ] && [ "${_ddb}" != "None" ] && DDB_TABLE="${_ddb}"
fi
echo "DynamoDB table:   ${DDB_TABLE}"

LANGFUSE_HOST=""
if aws lambda get-function-configuration --function-name "${FUNC}" \
     --query 'Environment.Variables.LANGFUSE_HOST' --output text \
     > /tmp/review_lf_host 2>/dev/null; then
  _lf=$(cat /tmp/review_lf_host)
  [ -n "${_lf}" ] && [ "${_lf}" != "None" ] && LANGFUSE_HOST="${_lf}"
fi

LANGFUSE_SECRET_NAME=""
if aws lambda get-function-configuration --function-name "${FUNC}" \
     --query 'Environment.Variables.LANGFUSE_SECRET_NAME' --output text \
     > /tmp/review_lf_secret 2>/dev/null; then
  _lfsecret=$(cat /tmp/review_lf_secret)
  [ -n "${_lfsecret}" ] && [ "${_lfsecret}" != "None" ] && LANGFUSE_SECRET_NAME="${_lfsecret}"
fi

LANGFUSE_REVIEW_TAG=""
if aws lambda get-function-configuration --function-name "${FUNC}" \
     --query 'Environment.Variables.LANGFUSE_REVIEW_TAG' --output text \
     > /tmp/review_lf_tag 2>/dev/null; then
  _lftag=$(cat /tmp/review_lf_tag)
  [ -n "${_lftag}" ] && [ "${_lftag}" != "None" ] && LANGFUSE_REVIEW_TAG="${_lftag}"
fi

# --- Delete API Gateway -------------------------------------------------------
API_ID=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)
if [ -n "${API_ID}" ] && [ "${API_ID}" != "None" ]; then
  echo "Deleting API ${API_ID} (${API_NAME})..."
  aws apigatewayv2 delete-api --api-id "${API_ID}" || true
  # Retry loop for propagation delay (up to 30s)
  for _ in $(seq 1 6); do
    REMAINING=$(aws apigatewayv2 get-apis \
      --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)
    if [ -z "${REMAINING}" ] || [ "${REMAINING}" = "None" ]; then break; fi
    sleep 5
  done
else
  echo "API ${API_NAME} not found — already deleted (idempotent)."
fi

# --- Delete Lambda ------------------------------------------------------------
if aws lambda get-function --function-name "${FUNC}" >/dev/null 2>&1; then
  echo "Deleting Lambda ${FUNC}..."
  aws lambda delete-function --function-name "${FUNC}"
else
  echo "Lambda ${FUNC} not found — already deleted (idempotent)."
fi

# --- Delete S3 prefix ---------------------------------------------------------
# RFC-0034 moved review frontend assets off the shared CDK dev bucket to a
# dedicated terraform-managed bucket. Both bucket + distribution come in as
# project-level CI variables (REVIEW_ASSETS_BUCKET, REVIEW_CF_DISTRIBUTION_ID).
BUCKET="${REVIEW_ASSETS_BUCKET}"
echo "Deleting S3 prefix s3://${BUCKET}/${CI_COMMIT_REF_SLUG}/"
aws s3 rm "s3://${BUCKET}/${CI_COMMIT_REF_SLUG}/" --recursive

# --- CloudFront invalidation (fail-soft) --------------------------------------
# Keeps the edge cache from serving a stale index after teardown; a failure
# here must not block the rest of the cleanup, so swallow the exit code.
echo "Invalidating CloudFront /${CI_COMMIT_REF_SLUG}/* on ${REVIEW_CF_DISTRIBUTION_ID}"
aws cloudfront create-invalidation \
  --distribution-id "${REVIEW_CF_DISTRIBUTION_ID}" \
  --paths "/${CI_COMMIT_REF_SLUG}/*" >/dev/null \
  || echo "WARNING: CloudFront invalidation failed — continuing teardown."

# --- Delete ECR images --------------------------------------------------------
# Every push that kept the trigger file built a new review-<slug>-<sha> image,
# so multiple tags accumulate. Delete ALL of them for this branch (the SHA from
# the Lambda env only identifies the last one).
#
# Match EXACTLY review-<slug>-<hexsha>: anchored, with a hex commit SHA and no
# further "-". A naive starts_with('review-<slug>-') prefix would also match a
# sibling branch whose slug extends this one (e.g. <slug>-foo → review-<slug>-foo-<sha>),
# deleting another active review env's image. The anchor prevents that.
ECR_TAGS=$(aws ecr list-images \
  --repository-name renate-chat-lambda \
  --query 'imageIds[].imageTag' --output text 2>/dev/null || true)

ECR_DELETE_ARGS=""
for _tag in ${ECR_TAGS}; do
  if printf '%s' "${_tag}" | grep -Eq "^review-${CI_COMMIT_REF_SLUG}-[0-9a-f]+$"; then
    ECR_DELETE_ARGS="${ECR_DELETE_ARGS} imageTag=${_tag}"
  fi
done

if [ -n "${ECR_DELETE_ARGS}" ]; then
  echo "Deleting ECR images:${ECR_DELETE_ARGS}"
  # shellcheck disable=SC2086  # intentional word-splitting: one --image-ids arg per tag
  aws ecr batch-delete-image \
    --repository-name renate-chat-lambda \
    --image-ids ${ECR_DELETE_ARGS} || true
else
  echo "No ECR images for 'review-${CI_COMMIT_REF_SLUG}-<sha>' — already deleted (idempotent)."
fi

# --- Delete DynamoDB items ----------------------------------------------------
echo "Scanning DynamoDB ${DDB_TABLE} for prefix ${DDB_PREFIX}..."
aws dynamodb scan \
  --table-name "${DDB_TABLE}" \
  --filter-expression "begins_with(session_id, :p)" \
  --expression-attribute-values "{\":p\":{\"S\":\"${DDB_PREFIX}\"}}" \
  --projection-expression "session_id,message_id" \
  --output json \
| jq -c '.Items[]' 2>/dev/null | while read -r item; do
    sid=$(printf '%s' "$item" | jq -r '.session_id.S')
    mid=$(printf '%s' "$item" | jq -r '.message_id.S')
    aws dynamodb delete-item \
      --table-name "${DDB_TABLE}" \
      --key "{\"session_id\":{\"S\":\"${sid}\"},\"message_id\":{\"S\":\"${mid}\"}}"
  done
echo "DynamoDB cleanup done."

# --- Delete review test user --------------------------------------------------
REVIEW_TEST_USER="review-$(printf '%s' "${CI_COMMIT_REF_SLUG}" | sha256sum | cut -c1-12)@drv-bund.de"
CLEANUP_STACK_JSON=$(aws cloudformation describe-stacks \
  --stack-name renate-chatbot-dev --output json)
CLEANUP_USER_POOL_ID=$(printf '%s' "${CLEANUP_STACK_JSON}" | jq -r \
  '.Stacks[0].Outputs[] | select(.OutputKey | startswith("AuthUserPoolId")) | .OutputValue')

if [ -n "${CLEANUP_USER_POOL_ID}" ] && [ "${CLEANUP_USER_POOL_ID}" != "null" ]; then
  if aws cognito-idp admin-get-user \
       --user-pool-id "${CLEANUP_USER_POOL_ID}" \
       --username "${REVIEW_TEST_USER}" >/dev/null 2>&1; then
    echo "Deleting test user ${REVIEW_TEST_USER}..."
    aws cognito-idp admin-delete-user \
      --user-pool-id "${CLEANUP_USER_POOL_ID}" \
      --username "${REVIEW_TEST_USER}"
  else
    echo "Test user ${REVIEW_TEST_USER} not found — already deleted (idempotent)."
  fi
else
  echo "Could not read UserPoolId from stack — skipping test user deletion."
fi

# --- Verify all resources are gone --------------------------------------------
verify_cleanup() {
  local failed=0

  # Lambda: must be 404
  if aws lambda get-function --function-name "${FUNC}" >/dev/null 2>&1; then
    echo "VERIFY FAIL: Lambda ${FUNC} still exists"
    failed=1
  fi

  # APIGW: must be absent by name
  REMAINING_API=$(aws apigatewayv2 get-apis \
    --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)
  if [ -n "${REMAINING_API}" ] && [ "${REMAINING_API}" != "None" ]; then
    echo "VERIFY FAIL: API ${API_NAME} still exists (${REMAINING_API})"
    failed=1
  fi

  # S3: KeyCount must be 0
  KEY_COUNT=$(aws s3api list-objects-v2 \
    --bucket "${BUCKET}" \
    --prefix "${CI_COMMIT_REF_SLUG}/" \
    --query 'KeyCount' --output text)
  if [ "${KEY_COUNT}" != "0" ] && [ "${KEY_COUNT}" != "None" ] && [ -n "${KEY_COUNT}" ]; then
    echo "VERIFY FAIL: S3 prefix still has ${KEY_COUNT} objects"
    failed=1
  fi

  # ECR: image tag must be absent
  if [ -n "${REVIEW_DEPLOY_SHA}" ]; then
    ECR_FOUND=$(aws ecr describe-images \
      --repository-name renate-chat-lambda \
      --image-ids "imageTag=review-${CI_COMMIT_REF_SLUG}-${REVIEW_DEPLOY_SHA}" \
      --query 'imageDetails[0].imageDigest' --output text 2>/dev/null || true)
    if [ -n "${ECR_FOUND}" ] && [ "${ECR_FOUND}" != "None" ]; then
      echo "VERIFY FAIL: ECR image still exists"
      failed=1
    fi
  fi

  # DynamoDB: Count must be 0. The scan paginates over the whole table (the
  # filter is applied per page), so --query 'Count' emits one count per page —
  # sum them into a single total.
  DDB_COUNT=$(aws dynamodb scan \
    --table-name "${DDB_TABLE}" \
    --filter-expression "begins_with(session_id, :p)" \
    --expression-attribute-values "{\":p\":{\"S\":\"${DDB_PREFIX}\"}}" \
    --select COUNT \
    --query 'Count' --output text | awk '{s += $1} END {print s + 0}')
  if [ "${DDB_COUNT}" != "0" ]; then
    echo "VERIFY FAIL: DynamoDB still has ${DDB_COUNT} items with prefix"
    failed=1
  fi

  [ "$failed" -eq 0 ] || { echo "Cleanup verification failed — see above"; exit 1; }
  echo "All resources verified deleted."

  # Cognito test user: must be absent
  if [ -n "${CLEANUP_USER_POOL_ID}" ]; then
    if aws cognito-idp admin-get-user \
         --user-pool-id "${CLEANUP_USER_POOL_ID}" \
         --username "${REVIEW_TEST_USER}" >/dev/null 2>&1; then
      echo "VERIFY FAIL: Cognito test user ${REVIEW_TEST_USER} still exists"
      failed=1
    fi
  fi

  [ "$failed" -eq 0 ] || { echo "Cleanup verification failed — see above"; exit 1; }
  echo "All resources verified deleted."
}

# --- Delete Langfuse traces for this branch (fail-soft) ----------------------
#
# As of the v4 `events_only` cutover (#901, 2026-10-20), Langfuse OSS no longer
# exposes GET /api/public/traces or DELETE /api/public/traces. Detection path
# below surfaces this via a loud GitLab error banner so broken teardowns do
# not pass as silent successes — see #948 for the replacement implementation
# (ClickHouse-direct deletion or Langfuse Enterprise retention).
delete_review_langfuse_traces() {
  if [ -z "${LANGFUSE_HOST}" ] || [ -z "${LANGFUSE_SECRET_NAME}" ] || [ -z "${LANGFUSE_REVIEW_TAG}" ]; then
    echo "Langfuse tracing disabled or vars absent — skipping trace deletion."
    return 0
  fi
  # Strip any trailing slash to avoid "//api/public/..." in request URLs.
  LANGFUSE_HOST="${LANGFUSE_HOST%/}"

  # Response-body sink shared across every curl; cleaned up on every return.
  local body_file
  body_file=$(mktemp)
  trap 'rm -f "${body_file}"; unset auth' RETURN

  # Fetch public+secret keys; never print values
  local secret_str
  secret_str=$(aws secretsmanager get-secret-value \
    --secret-id "${LANGFUSE_SECRET_NAME}" \
    --query SecretString --output text 2>/dev/null) || {
    echo "WARNING: Could not fetch Langfuse secret — skipping trace deletion."
    return 0
  }
  local pub_key secret_key auth
  pub_key=$(printf '%s' "${secret_str}" | jq -r '.publicKey')
  secret_key=$(printf '%s' "${secret_str}" | jq -r '.secretKey')
  auth=$(printf '%s:%s' "${pub_key}" "${secret_key}" | base64 -w0)
  unset secret_str pub_key secret_key

  # Paginate GET /api/public/traces?tags=<tag>
  local page=1
  local -a trace_ids=()
  while true; do
    local http_status
    : > "${body_file}"
    http_status=$(curl -s -o "${body_file}" -w '%{http_code}' --max-time 30 \
      -H "Authorization: Basic ${auth}" \
      "${LANGFUSE_HOST}/api/public/traces?tags=${LANGFUSE_REVIEW_TAG}&limit=100&page=${page}" 2>/dev/null) \
      || http_status="000"

    case "${http_status}" in
      2??)
        ;;
      404)
        if grep -qiE 'events[_-]only' "${body_file}" 2>/dev/null; then
          # Langfuse OSS v4 events_only mode: list-by-tag and bulk-delete are
          # architecturally gone. Make this loud so teardowns stop looking
          # successful just because the GET returned 404.
          log_error_banner "langfuse-cleanup-events-only" \
            "ERROR: Langfuse cleanup unsupported under events_only — branch=${CI_COMMIT_REF_SLUG} tag=${LANGFUSE_REVIEW_TAG} — see #948"
          # Print the marker response once so a future Langfuse rename of
          # 'events_only' is visible in CI output instead of silently
          # dropping into the generic WARNING branch.
          echo "Langfuse response (first 500 chars):"
          head -c 500 "${body_file}" || true
          echo
          return 0
        fi
        echo "WARNING: Langfuse GET traces page ${page} returned 404 — stopping pagination."
        break
        ;;
      000)
        echo "WARNING: Langfuse GET traces page ${page} connect failure — stopping pagination."
        break
        ;;
      *)
        echo "WARNING: Langfuse GET traces page ${page} failed (HTTP ${http_status}) — stopping pagination."
        break
        ;;
    esac

    local ids
    ids=$(jq -r '.data[].id // empty' "${body_file}" 2>/dev/null) || break
    [ -z "${ids}" ] && break
    while IFS= read -r id; do
      trace_ids+=("${id}")
    done <<< "${ids}"
    local total_pages
    total_pages=$(jq -r '.meta.totalPages // 1' "${body_file}" 2>/dev/null || echo 1)
    [ "${page}" -ge "${total_pages}" ] && break
    page=$((page + 1))
  done

  if [ "${#trace_ids[@]}" -eq 0 ]; then
    echo "No Langfuse traces found for tag ${LANGFUSE_REVIEW_TAG}."
    return 0
  fi
  echo "Deleting ${#trace_ids[@]} Langfuse traces tagged ${LANGFUSE_REVIEW_TAG}..."

  # Batch DELETE in groups of 100. Under events_only this path is unreachable
  # (trace_ids stays empty); the existing fail-soft WARNING is preserved for
  # any future Langfuse mode that re-enables the endpoint.
  local i=0
  while [ "${i}" -lt "${#trace_ids[@]}" ]; do
    local batch=("${trace_ids[@]:${i}:100}")
    local body
    body=$(printf '%s\n' "${batch[@]}" | jq -Rs '[split("\n")[] | select(. != "")]')
    body="{\"traceIds\":${body}}"
    curl -sf --max-time 30 \
      -X DELETE \
      -H "Authorization: Basic ${auth}" \
      -H "Content-Type: application/json" \
      -d "${body}" \
      "${LANGFUSE_HOST}/api/public/traces" >/dev/null 2>&1 || \
      echo "WARNING: Langfuse DELETE batch failed — continuing."
    i=$((i + 100))
  done
  echo "Langfuse trace deletion complete for tag ${LANGFUSE_REVIEW_TAG}."
}

delete_review_langfuse_traces || echo "WARNING: Langfuse cleanup failed — continuing teardown."

# Verify AWS resources last: trace deletion above runs first so a hard verify
# failure (exit 1) cannot leave this branch's traces orphaned in Langfuse.
verify_cleanup
