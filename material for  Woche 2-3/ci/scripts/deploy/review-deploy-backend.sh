#!/usr/bin/env bash
set -euo pipefail

# TKT-REV-04b — Deploy a branch review backend: idempotent Lambda + HTTP API GW.
#
# Clones the dev Lambda's VPC config (Bedrock KB is only reachable via VPC
# endpoints) and its environment variables, injects REVIEW_ID / REVIEW_DEPLOY_SHA,
# and fronts the function with an HTTP API (explicit integration, payload format
# 1.0 for APIGatewayRestResolver compatibility). Re-runs on the same branch
# update the function in place (no duplicates). Resources are tagged on both the
# create and update paths.
#
# Idempotency contract:
#   - lambda get-function    → 404 = create-function, 200 = update-function-code
#   - apigatewayv2 get-apis  → empty = create-api,     present = reuse ApiId
#
# Writes review.env (dotenv) consumed by the GitLab environment URL and by the
# frontend deploy job (TKT-REV-04c).

# Required environment variables (provided by CI job or caller)
: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"
: "${CI_COMMIT_SHORT_SHA:?CI_COMMIT_SHORT_SHA is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${ROLE_ARN:?ROLE_ARN is required}"
: "${ECR_REGISTRY:?ECR_REGISTRY is required}"
: "${ECR_REPO:?ECR_REPO is required}"
: "${DEV_FUNCTION_NAME:?DEV_FUNCTION_NAME is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"
# RFC-0034: the review SPA is served from the dedicated review CloudFront
# distribution now, not the shared CDK one. Its domain is the only valid
# origin for the review API GW CORS AllowOrigins. Project-level CI variable.
: "${REVIEW_CF_DOMAIN:?REVIEW_CF_DOMAIN is required}"

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/../lib/log.sh"
# shellcheck source=lib/review-names.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/../lib/review-names.sh"

IMAGE_TAG="review-${CI_COMMIT_REF_SLUG}-${CI_COMMIT_SHORT_SHA}"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"

# Resource tags applied on every create AND update (update-function-code /
# update-function-configuration do NOT touch tags — see RFC-02 § 5).
TAGS="Environment=review,Branch=${CI_COMMIT_REF_SLUG},Commit=${CI_COMMIT_SHORT_SHA}"

echo "Review function:  ${FUNC}"
echo "Review API name:  ${API_NAME}"
echo "Image URI:        ${IMAGE_URI}"

# --- Tooling ------------------------------------------------------------------
# jq is available in node-aws:0.6.0+. Dev env values contain commas/"=" (URLs,
# ARNs) so the CLI shorthand is unsafe for --environment — use JSON via jq.

# --- OIDC: assume role --------------------------------------------------------
echo "Assuming role: ${ROLE_ARN}"
# Capture stdout only — let AWS CLI errors flow to the job log unmodified.
# (Mixing stderr into STS_OUTPUT could be mis-parsed as credentials.)
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

# Account ID for resource ARNs (source-arn below rejects a "*" account).
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
[[ -n "${ACCOUNT_ID}" && "${ACCOUNT_ID}" != "None" ]] \
  || { echo "Could not resolve AWS account ID"; exit 1; }

# --- Read dev Lambda configuration to clone -----------------------------------
echo "Reading config from dev function: ${DEV_FUNCTION_NAME}"
DEV_CONFIG=$(aws lambda get-function-configuration \
  --function-name "${DEV_FUNCTION_NAME}" \
  --output json)

EXEC_ROLE=$(printf '%s' "${DEV_CONFIG}" | jq -r '.Role')
SUBNETS=$(printf '%s' "${DEV_CONFIG}" \
  | jq -r '.VpcConfig.SubnetIds | join(",")')
SECURITY_GROUPS=$(printf '%s' "${DEV_CONFIG}" \
  | jq -r '.VpcConfig.SecurityGroupIds | join(",")')
TIMEOUT=$(printf '%s' "${DEV_CONFIG}" | jq -r '.Timeout')
MEMORY_SIZE=$(printf '%s' "${DEV_CONFIG}" | jq -r '.MemorySize')

[[ -n "${EXEC_ROLE}" && "${EXEC_ROLE}" != "null" ]] \
  || { echo "Could not read exec role from ${DEV_FUNCTION_NAME}"; exit 1; }
[[ -n "${SUBNETS}" ]] \
  || { echo "Dev function has no VPC subnets — cannot clone"; exit 1; }
[[ -n "${SECURITY_GROUPS}" ]] \
  || { echo "Dev function has no security groups — cannot clone"; exit 1; }

echo "Exec role:        ${EXEC_ROLE}"
echo "VPC subnets:      ${SUBNETS}"
echo "Security groups:  ${SECURITY_GROUPS}"

VPC_CONFIG="SubnetIds=${SUBNETS},SecurityGroupIds=${SECURITY_GROUPS}"

# --- Consent log group (DSFA audit trail, mirrors CDK's /renate/<env>/consent-log) ---
CONSENT_LOG_GROUP="/renate/review-${SLUG}/consent-log"
aws logs create-log-group \
  --log-group-name "${CONSENT_LOG_GROUP}" \
  --tags "Environment=review,Branch=${CI_COMMIT_REF_SLUG}" 2>/dev/null || true
# Set retention to 90 days (matches CDK THREE_MONTHS)
aws logs put-retention-policy \
  --log-group-name "${CONSENT_LOG_GROUP}" \
  --retention-in-days 90 2>/dev/null || true
echo "Consent log group: ${CONSENT_LOG_GROUP}"

# Merge dev env vars + review-specific overrides into a Lambda --environment JSON.
# Missing Environment.Variables on dev → start from an empty object.

# --- Parse search_mode from the review trigger YAML (default: rag) ----------
TRIGGER_FILE="deployments/review/${CI_COMMIT_REF_SLUG}.yml"
SEARCH_MODE="rag"
if [ -f "${TRIGGER_FILE}" ]; then
  _parsed=$(grep -E '^\s*search_mode\s*:' "${TRIGGER_FILE}" \
    | sed 's/^[^:]*:\s*//' | tr -d ' "'"'" | head -1 || true)
  if [ -n "${_parsed}" ]; then
    SEARCH_MODE="${_parsed}"
  fi
fi
echo "Search mode:      ${SEARCH_MODE}"

# --- Agent-mode setup: S3 index upload + IAM policy ---------------------------
AGENT_SEARCH_INDEX_BUCKET=""
if [ "${SEARCH_MODE}" = "agent" ]; then
  # Use the frontend assets bucket — the CI deploy role already has write access.
  # Read its name from the dev CFN stack (same stack read later for Cognito).
  _STACK_JSON=$(aws cloudformation describe-stacks \
    --stack-name renate-chatbot-dev --output json)
  AGENT_SEARCH_INDEX_BUCKET=$(printf '%s' "${_STACK_JSON}" | jq -r \
    '.Stacks[0].Outputs[] | select(.OutputKey | startswith("FrontendFrontendS3BucketName")) | .OutputValue')

  if [ -z "${AGENT_SEARCH_INDEX_BUCKET}" ]; then
    echo "WARNING: Could not read FrontendS3BucketName — agent search index will not be available."
  else
    echo "Agent index bucket: ${AGENT_SEARCH_INDEX_BUCKET}"

    # Upload the agent-search-index from the repo to S3.
    # Use review/ prefix — the CI deploy role only has S3 access to review/*.
    AGENT_SEARCH_INDEX_PREFIX="review/agent-search-index/"
    echo "Uploading agent-search-index to s3://${AGENT_SEARCH_INDEX_BUCKET}/${AGENT_SEARCH_INDEX_PREFIX}..."
    aws s3 sync cdk/seed-data/agent-search-index/ \
      "s3://${AGENT_SEARCH_INDEX_BUCKET}/${AGENT_SEARCH_INDEX_PREFIX}" --quiet

    # NOTE: The Lambda role needs s3:GetObject on review/agent-search-index/*.
    # This is pre-provisioned via the "review-agent-search-index-read" inline
    # policy on the Lambda role (operator-managed — the CI deploy role does not
    # have iam:PutRolePolicy). If missing, agent search will log AccessDenied.
    echo "Agent index uploaded (Lambda IAM: pre-provisioned 'review-agent-search-index-read' policy)"
  fi
fi

ENV_JSON=$(printf '%s' "${DEV_CONFIG}" | jq \
  --arg review_id "${CI_COMMIT_REF_SLUG}" \
  --arg deploy_sha "${CI_COMMIT_SHORT_SHA}" \
  --arg langfuse_review_tag "${REVIEW_LANGFUSE_TAG}" \
  --arg consent_log_group "${CONSENT_LOG_GROUP}" \
  --arg search_mode "${SEARCH_MODE}" \
  --arg agent_bucket "${AGENT_SEARCH_INDEX_BUCKET}" \
  --arg agent_prefix "${AGENT_SEARCH_INDEX_PREFIX:-agent-search-index/}" \
  '{Variables: ((.Environment.Variables // {})
      + {REVIEW_ID: $review_id, REVIEW_DEPLOY_SHA: $deploy_sha, LANGFUSE_REVIEW_TAG: $langfuse_review_tag, CONSENT_LOG_GROUP: $consent_log_group, SEARCH_MODE: $search_mode}
      + (if $agent_bucket != "" then {AGENT_SEARCH_INDEX_BUCKET: $agent_bucket, AGENT_SEARCH_INDEX_PREFIX: $agent_prefix} else {} end))}')

# --- Idempotent Lambda create / update ----------------------------------------
if aws lambda get-function --function-name "${FUNC}" >/dev/null 2>&1; then
  echo "Function ${FUNC} exists — updating code."
  aws lambda update-function-code \
    --function-name "${FUNC}" \
    --image-uri "${IMAGE_URI}" >/dev/null
  aws lambda wait function-updated-v2 --function-name "${FUNC}"

  echo "Syncing configuration (VPC + env vars)."
  aws lambda update-function-configuration \
    --function-name "${FUNC}" \
    --role "${EXEC_ROLE}" \
    --vpc-config "${VPC_CONFIG}" \
    --environment "${ENV_JSON}" \
    --timeout "${TIMEOUT}" \
    --memory-size "${MEMORY_SIZE}" >/dev/null
  aws lambda wait function-updated-v2 --function-name "${FUNC}"
else
  echo "Function ${FUNC} not found — creating."
  aws lambda create-function \
    --function-name "${FUNC}" \
    --package-type Image \
    --code "ImageUri=${IMAGE_URI}" \
    --role "${EXEC_ROLE}" \
    --vpc-config "${VPC_CONFIG}" \
    --environment "${ENV_JSON}" \
    --timeout "${TIMEOUT}" \
    --memory-size "${MEMORY_SIZE}" >/dev/null
  aws lambda wait function-active-v2 --function-name "${FUNC}"
fi

# --- Tag the Lambda (create AND update paths) ---------------------------------
LAMBDA_ARN=$(aws lambda get-function \
  --function-name "${FUNC}" \
  --query 'Configuration.FunctionArn' \
  --output text)
aws lambda tag-resource --resource "${LAMBDA_ARN}" --tags "${TAGS}"
echo "Tagged Lambda ${LAMBDA_ARN}"

# --- Idempotent HTTP API Gateway ----------------------------------------------
API_ID=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='${API_NAME}'].ApiId | [0]" \
  --output text)

if [ -z "${API_ID}" ] || [ "${API_ID}" = "None" ]; then
  echo "API ${API_NAME} not found — creating."
  # Do NOT use --target (quick-create): it wires payload format 2.0 by default,
  # which is incompatible with APIGatewayRestResolver (expects format 1.0).
  API_ID=$(aws apigatewayv2 create-api \
    --name "${API_NAME}" \
    --protocol-type HTTP \
    --query 'ApiId' \
    --output text)

  INT_ID=$(aws apigatewayv2 create-integration \
    --api-id "${API_ID}" \
    --integration-type AWS_PROXY \
    --integration-uri "${LAMBDA_ARN}" \
    --payload-format-version 1.0 \
    --query 'IntegrationId' \
    --output text)

  # shellcheck disable=SC2016  # $default is a literal APIGW route/stage name
  aws apigatewayv2 create-route \
    --api-id "${API_ID}" \
    --route-key '$default' \
    --target "integrations/${INT_ID}" >/dev/null

  # shellcheck disable=SC2016  # $default is a literal APIGW route/stage name
  aws apigatewayv2 create-stage \
    --api-id "${API_ID}" \
    --stage-name '$default' \
    --auto-deploy >/dev/null
else
  echo "Reusing existing API ${API_NAME} (${API_ID})."
fi

# Allow API Gateway to invoke the Lambda. Idempotent: a fixed statement id means
# re-runs hit ResourceConflictException, which is expected and ignored. Any
# other error (e.g. AccessDenied) must fail the job — a missing resource policy
# makes every API call return 500 (API GW cannot invoke the Lambda).
ADD_PERM_ERR=$(aws lambda add-permission \
  --function-name "${FUNC}" \
  --statement-id "apigw-invoke-${SLUG}" \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
  2>&1 >/dev/null) || true

if [ -n "${ADD_PERM_ERR}" ]; then
  if printf '%s' "${ADD_PERM_ERR}" | grep -q "ResourceConflictException"; then
    echo "add-permission already present (idempotent re-run)."
  else
    echo "add-permission failed: ${ADD_PERM_ERR}"
    exit 1
  fi
fi

# Tag the API (create AND reuse paths — create-api tags are not updated on reuse).
API_ARN="arn:aws:apigateway:${AWS_DEFAULT_REGION}::/apis/${API_ID}"
aws apigatewayv2 tag-resource \
  --resource-arn "${API_ARN}" \
  --tags "${TAGS}"
echo "Tagged API ${API_ID}"

# --- Cognito JWT authorizer + CORS + health route + test user (TKT-REV-08 / #455) ---

# Read Cognito pool + client IDs and CloudFront origin from the dev stack.
DEV_STACK_JSON=$(aws cloudformation describe-stacks \
  --stack-name renate-chatbot-dev --output json)

extract_stack_output() {
  local key="$1"
  printf '%s' "${DEV_STACK_JSON}" | jq -r \
    --arg k "$key" \
    '.Stacks[0].Outputs[] | select(.OutputKey | startswith($k)) | .OutputValue'
}

USER_POOL_ID=$(extract_stack_output "AuthUserPoolId")
CLIENT_ID=$(extract_stack_output "AuthUserPoolClientId")

[[ -n "${USER_POOL_ID}" ]] || { echo "Could not read UserPoolId from stack"; exit 1; }
[[ -n "${CLIENT_ID}" ]]    || { echo "Could not read UserPoolClientId from stack"; exit 1; }

# RFC-0034: SPA served from the review CloudFront distribution. CF_ORIGIN was
# previously the CDK dev frontend URL extracted above — that distribution no
# longer hosts the review SPA, so the API GW CORS must trust the review
# distribution instead.
CF_ORIGIN="https://${REVIEW_CF_DOMAIN}"

ISSUER="https://cognito-idp.${AWS_DEFAULT_REGION}.amazonaws.com/${USER_POOL_ID}"

# --- JWT authorizer (idempotent) ---
AUTH_ID=$(aws apigatewayv2 get-authorizers \
  --api-id "${API_ID}" \
  --query "Items[?Name=='cognito-jwt'].AuthorizerId | [0]" \
  --output text)

if [ -z "${AUTH_ID}" ] || [ "${AUTH_ID}" = "None" ]; then
  echo "Creating Cognito JWT authorizer for API ${API_ID}."
  # shellcheck disable=SC2016  # $request.header.Authorization is a literal APIGW expression, not a shell var
  AUTH_ID=$(aws apigatewayv2 create-authorizer \
    --api-id "${API_ID}" \
    --name "cognito-jwt" \
    --authorizer-type JWT \
    --identity-source '$request.header.Authorization' \
    --jwt-configuration "Audience=${CLIENT_ID},Issuer=${ISSUER}" \
    --query 'AuthorizerId' \
    --output text)
else
  echo "Reusing existing JWT authorizer ${AUTH_ID}."
fi

# --- Attach JWT authorizer to the $default route ---
# shellcheck disable=SC2016
DEFAULT_ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "${API_ID}" \
  --query "Items[?RouteKey=='\$default'].RouteId | [0]" \
  --output text)

# shellcheck disable=SC2016
aws apigatewayv2 update-route \
  --api-id "${API_ID}" \
  --route-id "${DEFAULT_ROUTE_ID}" \
  --authorization-type JWT \
  --authorizer-id "${AUTH_ID}" >/dev/null
echo "JWT authorizer attached to \$default route."

# --- Unauthenticated GET /health route (idempotent) ---
HEALTH_ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "${API_ID}" \
  --query "Items[?RouteKey=='GET /health'].RouteId | [0]" \
  --output text)

INT_ID=$(aws apigatewayv2 get-integrations \
  --api-id "${API_ID}" \
  --query "Items[0].IntegrationId" \
  --output text)

if [ -z "${HEALTH_ROUTE_ID}" ] || [ "${HEALTH_ROUTE_ID}" = "None" ]; then
  echo "Creating unauthenticated GET /health route."
  aws apigatewayv2 create-route \
    --api-id "${API_ID}" \
    --route-key "GET /health" \
    --authorization-type NONE \
    --target "integrations/${INT_ID}" >/dev/null
else
  echo "Reusing existing GET /health route."
fi

# --- Unauthenticated POST /api/consent route (DSFA consent logging, #543) -----
# Production CDK configures this route with AuthorizationType.NONE. Mirror that
# in the review env so the frontend dev can test without a token.
CONSENT_ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "${API_ID}" \
  --query "Items[?RouteKey=='POST /api/consent'].RouteId | [0]" \
  --output text)

if [ -z "${CONSENT_ROUTE_ID}" ] || [ "${CONSENT_ROUTE_ID}" = "None" ]; then
  echo "Creating unauthenticated POST /api/consent route."
  aws apigatewayv2 create-route \
    --api-id "${API_ID}" \
    --route-key "POST /api/consent" \
    --authorization-type NONE \
    --target "integrations/${INT_ID}" >/dev/null
else
  echo "Reusing existing POST /api/consent route."
fi

# --- Unauthenticated DELETE /api/session/{conversationId} route (Widerruf, #545) ---
# Production CDK configures this route with AuthorizationType.NONE (capability-based
# security via UUID possession). Mirror that in the review env.
SESSION_ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "${API_ID}" \
  --query "Items[?RouteKey=='DELETE /api/session/{conversationId}'].RouteId | [0]" \
  --output text)

if [ -z "${SESSION_ROUTE_ID}" ] || [ "${SESSION_ROUTE_ID}" = "None" ]; then
  echo "Creating unauthenticated DELETE /api/session/{conversationId} route."
  aws apigatewayv2 create-route \
    --api-id "${API_ID}" \
    --route-key "DELETE /api/session/{conversationId}" \
    --authorization-type NONE \
    --target "integrations/${INT_ID}" >/dev/null
else
  echo "Reusing existing DELETE /api/session/{conversationId} route."
fi

# --- Unauthenticated OPTIONS /{proxy+} route (CORS preflight) -----------------
# The JWT authorizer on $default rejects OPTIONS before reaching Lambda.
# An explicit OPTIONS route with NONE auth bypasses the authorizer so Lambda
# can respond with its own CORS headers (204).
OPTIONS_ROUTE_ID=$(aws apigatewayv2 get-routes \
  --api-id "${API_ID}" \
  --query "Items[?RouteKey=='OPTIONS /{proxy+}'].RouteId | [0]" \
  --output text)

if [ -z "${OPTIONS_ROUTE_ID}" ] || [ "${OPTIONS_ROUTE_ID}" = "None" ]; then
  echo "Creating unauthenticated OPTIONS /{proxy+} route for CORS preflight."
  aws apigatewayv2 create-route \
    --api-id "${API_ID}" \
    --route-key "OPTIONS /{proxy+}" \
    --authorization-type NONE \
    --target "integrations/${INT_ID}" >/dev/null
else
  echo "Reusing existing OPTIONS /{proxy+} route."
fi

# --- CORS (required for browser SPA cross-origin requests with Authorization header) ---
CF_ORIGIN="${CF_ORIGIN%/}"
CORS_JSON=$(printf '{"AllowOrigins":["%s"],"AllowMethods":["GET","POST","PUT","DELETE","OPTIONS"],"AllowHeaders":["Authorization","Content-Type"],"MaxAge":300}' "${CF_ORIGIN}")
aws apigatewayv2 update-api \
  --api-id "${API_ID}" \
  --cors-configuration "${CORS_JSON}" >/dev/null
echo "CORS configured for origin: ${CF_ORIGIN}"

# --- Idempotent test user (check-or-create, password log-only) ---
REVIEW_TEST_USER="review-$(printf '%s' "${CI_COMMIT_REF_SLUG}" | sha256sum | cut -c1-12)@drv-bund.de"

# Print the review-stage banner just before the test-user credentials.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANNER_FILE="${SCRIPT_DIR}/../banner/review.txt"
[ -f "${BANNER_FILE}" ] && cat "${BANNER_FILE}"

if aws cognito-idp admin-get-user \
     --user-pool-id "${USER_POOL_ID}" \
     --username "${REVIEW_TEST_USER}" >/dev/null 2>&1; then
  log_section "REVIEW TEST USER   (visible only in the CI log)"
  log_kv "User:"     "${REVIEW_TEST_USER}"
  log_kv "Password:" "(shown only in the deploy log that created it)"
  log_done
  echo "  Test user already exists — skipping creation (credentials unchanged)."
else
  echo "  Creating review test user..."
  # 16-char password: 12 random hex + 4 fixed chars satisfying pool policy (upper, digit, symbol).
  REVIEW_TEST_PASSWORD="$(openssl rand -hex 6)Aa1!"
  aws cognito-idp admin-create-user \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${REVIEW_TEST_USER}" \
    --user-attributes Name=email,Value="${REVIEW_TEST_USER}" Name=email_verified,Value=true \
    --message-action SUPPRESS >/dev/null
  aws cognito-idp admin-set-user-password \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${REVIEW_TEST_USER}" \
    --password "${REVIEW_TEST_PASSWORD}" \
    --permanent >/dev/null
  # Printed to CI log only — NOT written to review.env artifact.
  log_section "REVIEW TEST USER   (visible only in this CI log)"
  log_kv "User:"     "${REVIEW_TEST_USER}"
  log_kv "Password:" "${REVIEW_TEST_PASSWORD}"
  log_done
  echo "  Deleted automatically when the review env is cleaned up."
fi

# --- Resolve endpoint + write dotenv artifact ---------------------------------
REVIEW_URL=$(aws apigatewayv2 get-api \
  --api-id "${API_ID}" \
  --query 'ApiEndpoint' \
  --output text)

echo "Review API endpoint: ${REVIEW_URL}"

# Consumed by the job's environment:url and by the frontend deploy job (04c).
cat > review.env <<EOF
REVIEW_URL=${REVIEW_URL}
REVIEW_API_URL=${REVIEW_URL}
REVIEW_FUNCTION_NAME=${FUNC}
EOF

echo "Wrote review.env"
