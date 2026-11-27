#!/usr/bin/env bash
set -euo pipefail

# #650 — Post-cdk-deploy API Gateway stage redeploy.
#
# Why
# ---
# CDK's RestApi creates ONE AWS::ApiGateway::Deployment. Adding or removing
# Methods bumps the Deployment's logical id (verified — CDK does hash the
# method set). But CloudFormation applies the events in an order that breaks
# route removal: it creates the new Deployment and flips the Stage BEFORE it
# deletes the removed Methods. Since Deployment is an immutable snapshot at
# creation time, the new snapshot still contains the routes that CFN is
# about to delete → the stage keeps serving them.
#
# Observed 2026-07-27 during history endpoint removal (#481 / !966):
# job 16658 CFN events showed Deployment CREATE_COMPLETE at 08:31:35,
# Stage UPDATE_COMPLETE at 08:31:37, /history Method DELETE_COMPLETE at
# 08:31:47 — 10 seconds too late. Endpoint kept returning 401 UnauthorizedException.
#
# Fix
# ---
# After cdk-deploy settles, force a fresh Deployment via the AWS CLI. API
# Gateway re-snapshots the current RestApi state (removals now applied) and
# the stage points at the new deployment. Idempotent — a no-diff run just
# creates a redundant deployment which is harmless.
#
# Contract
# --------
# Args:
#   $1  env: dev | qa | preprod | prod
#
# Env (required):
#   GITLAB_OIDC_TOKEN, CI_JOB_ID   — from GitLab id_tokens
#   ROLE_ARN                       — CDK_DEPLOY_ROLE_ARN_<ENV> from caller
#   AWS_DEFAULT_REGION
#
# Reads:
#   cloudformation describe-stacks --stack-name renate-chatbot-<env>
#     → ApiGatewayId output (from api-gateway.ts CfnOutput at line 277)
#
# Effect:
#   aws apigateway create-deployment --rest-api-id <id> --stage-name prod

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/log.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/log.sh"
# shellcheck source=../lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

GET_STACK_OUTPUTS="${SCRIPT_DIR}/../util/get-stack-outputs.sh"

ENV_ARG="${1:-}"
[[ -n "$ENV_ARG" ]] || { echo "usage: apigateway-redeploy.sh <env>" >&2; exit 1; }
_deploy_validate_env "$ENV_ARG" || exit 1

: "${ROLE_ARN:?ROLE_ARN is required (set CDK_DEPLOY_ROLE_ARN_<ENV> in caller)}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"

STACK="renate-chatbot-${ENV_ARG}"

# --- OIDC assume-role ---------------------------------------------------------
assume_deploy_role "$ROLE_ARN"

# --- Read API Gateway ID + stage from stack outputs ---------------------------
log_section "Reading API Gateway ID"
log_kv "Stack:" "$STACK"

OUTPUTS_JSON="$(mktemp)"
trap 'rm -f "$OUTPUTS_JSON"' EXIT
bash "$GET_STACK_OUTPUTS" "$STACK" "$OUTPUTS_JSON"

# CDK CfnOutput logical IDs carry an 8-hex suffix. Match by prefix.
API_ID="$(jq -r --arg stack "$STACK" \
  '.[$stack] | to_entries | .[] | select(.key | startswith("ApiGatewayApiGatewayId")) | .value' \
  "$OUTPUTS_JSON" | head -n1)"

[[ -n "$API_ID" ]] || { echo "Missing ApiGatewayId in $STACK outputs" >&2; exit 1; }

STAGE_NAME="$(jq -r --arg stack "$STACK" \
  '.[$stack] | to_entries | .[] | select(.key | startswith("ApiGatewayApiStageName")) | .value' \
  "$OUTPUTS_JSON" | head -n1)"

[[ -n "$STAGE_NAME" ]] || { echo "Missing ApiStageName in $STACK outputs" >&2; exit 1; }

log_kv "API ID:" "$API_ID"
log_kv "Stage:"  "$STAGE_NAME"

# --- Force fresh stage deployment ---------------------------------------------
section_start "create_deployment" "aws apigateway create-deployment"
aws apigateway create-deployment \
  --rest-api-id "$API_ID" \
  --stage-name "$STAGE_NAME" \
  --description "post-cdk redeploy ${CI_COMMIT_SHORT_SHA:-manual}" \
  --output text --query 'id' >/dev/null
section_end "create_deployment"

log_section "API GATEWAY REDEPLOYED"
log_kv "Env:"    "$ENV_ARG"
log_kv "API:"    "$API_ID"
log_kv "Stage:"  "$STAGE_NAME"
log_done
