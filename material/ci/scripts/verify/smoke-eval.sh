#!/usr/bin/env bash
set -euo pipefail

ROLE_ARN="$1"
STACK_NAME="$2"
ENV_LABEL="$3"

echo "Assuming role: $ROLE_ARN"
STS_OUTPUT=$(aws sts assume-role-with-web-identity \
  --role-arn "$ROLE_ARN" \
  --role-session-name "gitlab-ci-${CI_JOB_ID}" \
  --web-identity-token "$GITLAB_OIDC_TOKEN" \
  --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
  --output text) || STS_OUTPUT=""

read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  <<< "$STS_OUTPUT"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

[[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" \
  && -n "$AWS_SESSION_TOKEN" ]] \
  || { echo "STS assume-role failed: empty credentials"; exit 1; }

API_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text)

[[ -n "$API_URL" && "$API_URL" != "None" ]] \
  || { echo "CloudFormation output ApiUrl not found in stack $STACK_NAME"; exit 1; }

echo "Smoke eval [$ENV_LABEL]: GET ${API_URL}health"
curl -sf --max-time 30 "${API_URL}health"

# Frontend: verify the CloudFront distribution serves the app shell (HTTP 2xx).
# The output key is prefixed with the 'Frontend' construct id in the CFN stack.
CF_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendCloudFrontDistributionUrl')].OutputValue | [0]" \
  --output text)

[[ -n "$CF_URL" && "$CF_URL" != "None" ]] \
  || { echo "CloudFormation output FrontendCloudFrontDistributionUrl not found in stack $STACK_NAME"; exit 1; }

echo "Smoke eval [$ENV_LABEL]: GET ${CF_URL}/ (frontend)"
curl -sf -o /dev/null --max-time 30 "${CF_URL}/"
echo "Smoke eval [$ENV_LABEL]: OK"
