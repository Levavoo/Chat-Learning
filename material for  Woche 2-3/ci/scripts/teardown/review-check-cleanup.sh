#!/usr/bin/env bash
set -euo pipefail

# TKT-REV-06 — Pre-merge gate: block merge while a review environment is active.
#
# Step 1 (git): fail if any deployments/review/*.yml trigger file is tracked.
# Step 2 (AWS): if ROLE_ARN is set, verify no review resources remain in AWS.

# --- Step 1: trigger-file check -----------------------------------------------
REMAINING=$(git ls-files 'deployments/review/*.yml')
if [ -n "${REMAINING}" ]; then
  echo "Active review environment detected — clean up before merging:"
  echo "  ${REMAINING}"
  echo "Run review:teardown (manual Stop button) or delete the trigger file."
  exit 1
fi
echo "No active review trigger file found — git check passed."

# --- Step 2: AWS leftover-resource check --------------------------------------
# Skipped if ROLE_ARN is not set (e.g. git-only tests).
if [ -z "${ROLE_ARN:-}" ]; then
  echo "ROLE_ARN not set — skipping AWS resource check."
  exit 0
fi

: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"

# shellcheck disable=SC1091
source "$(dirname "$0")/../lib/review-names.sh"

echo "Checking AWS for leftover review resources (slug: ${SLUG})..."

# Assume role via OIDC
STS_OUTPUT=$(aws sts assume-role-with-web-identity \
  --role-arn "${ROLE_ARN}" \
  --role-session-name "gitlab-ci-${CI_JOB_ID}" \
  --web-identity-token "${GITLAB_OIDC_TOKEN}" \
  --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
  --output text) || { echo "STS assume-role failed"; exit 1; }

read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  <<< "${STS_OUTPUT}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

[[ -n "${AWS_ACCESS_KEY_ID}" && -n "${AWS_SECRET_ACCESS_KEY}" \
  && -n "${AWS_SESSION_TOKEN}" ]] \
  || { echo "STS assume-role failed: empty credentials"; exit 1; }

LEFTOVER=0

# Lambda
if aws lambda get-function --function-name "${FUNC}" >/dev/null 2>&1; then
  echo "LEFTOVER: Lambda ${FUNC} still exists — run review:teardown first."
  LEFTOVER=1
fi

# API Gateway
API_ID=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text) \
  || { echo "AWS check failed — could not query API Gateway."; exit 1; }
if [ -n "${API_ID}" ] && [ "${API_ID}" != "None" ]; then
  echo "LEFTOVER: API Gateway '${API_NAME}' (${API_ID}) still exists."
  LEFTOVER=1
fi

# S3 prefix
STACK_JSON=$(aws cloudformation describe-stacks \
  --stack-name renate-chatbot-dev --output json 2>/dev/null || echo '{}')
BUCKET=$(printf '%s' "${STACK_JSON}" | \
  jq -r '.Stacks[0].Outputs[]? | select(.OutputKey | startswith("FrontendFrontendS3BucketName")) | .OutputValue' \
  2>/dev/null || true)
if [ -n "${BUCKET}" ] && [ "${BUCKET}" != "null" ]; then
  # list-objects-v2 paginates; --query 'KeyCount' emits one count per page —
  # sum them (same pagination class as the DynamoDB COUNT scan).
  KEY_COUNT=$(aws s3api list-objects-v2 \
    --bucket "${BUCKET}" \
    --prefix "review/${CI_COMMIT_REF_SLUG}/" \
    --query 'KeyCount' --output text 2>/dev/null \
    | awk '{s += $1} END {print s + 0}')
  if [ -n "${KEY_COUNT}" ] && [ "${KEY_COUNT}" != "0" ]; then
    echo "LEFTOVER: S3 prefix review/${CI_COMMIT_REF_SLUG}/ has ${KEY_COUNT} objects."
    LEFTOVER=1
  fi
fi

# ECR — match EXACTLY review-<slug>-<hexsha> (anchored, hex SHA, no further "-").
# The image tag is built from CI_COMMIT_REF_SLUG (not the truncated SLUG used for
# the Lambda/API names), so match on that. An anchored hex suffix avoids matching
# a sibling branch whose slug extends this one (e.g. <slug>-foo).
ECR_TAGS=$(aws ecr list-images \
  --repository-name renate-chat-lambda \
  --query 'imageIds[].imageTag' --output text 2>/dev/null || true)
for _tag in ${ECR_TAGS}; do
  if printf '%s' "${_tag}" | grep -Eq "^review-${CI_COMMIT_REF_SLUG}-[0-9a-f]+$"; then
    echo "LEFTOVER: ECR image ${_tag} still exists."
    LEFTOVER=1
  fi
done

# Cognito disposable test user (created on deploy, deleted on cleanup).
USER_POOL_ID=$(printf '%s' "${STACK_JSON}" | \
  jq -r '.Stacks[0].Outputs[]? | select(.OutputKey | startswith("AuthUserPoolId")) | .OutputValue' \
  2>/dev/null || true)
if [ -n "${USER_POOL_ID}" ] && [ "${USER_POOL_ID}" != "null" ]; then
  if aws cognito-idp admin-get-user \
       --user-pool-id "${USER_POOL_ID}" \
       --username "${REVIEW_TEST_USER}" >/dev/null 2>&1; then
    echo "LEFTOVER: Cognito test user ${REVIEW_TEST_USER} still exists."
    LEFTOVER=1
  fi
fi

if [ "${LEFTOVER}" -eq 1 ]; then
  echo "AWS check failed — leftover review resources found (see above)."
  exit 1
fi

echo "AWS check passed — no leftover review resources found."
