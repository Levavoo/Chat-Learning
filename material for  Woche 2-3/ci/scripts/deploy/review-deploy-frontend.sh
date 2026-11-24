#!/usr/bin/env bash
set -euo pipefail

# TKT-REV-04c — Build + deploy Angular review frontend to S3 + CloudFront.
#
# Contract
# --------
# Inputs (required, exits non-zero if unset):
#   CI_COMMIT_REF_SLUG         — branch slug → $SLUG/ prefix + --base-href
#   REVIEW_API_URL             — from 04b review.env → NG_APP_API_ENDPOINT
#   REVIEW_CF_DISTRIBUTION_ID  — RFC-0034 CloudFront distribution id (project var)
#   REVIEW_CF_DOMAIN           — RFC-0034 CloudFront *.cloudfront.net domain
#   REVIEW_ASSETS_BUCKET       — RFC-0034 review assets S3 bucket name
#   GITLAB_OIDC_TOKEN, CI_JOB_ID, ROLE_ARN, AWS_DEFAULT_REGION
#
# Reads (no mutation):
#   cloudformation describe-stacks --stack-name renate-chatbot-dev
#   → Auth/Region/CognitoDomain outputs for NG_APP_* build-time vars
#   (Frontend distribution/bucket outputs are no longer read — RFC-0034
#    migrated these to the dedicated review-frontend TF module whose values
#    are injected via the three REVIEW_CF_* / REVIEW_ASSETS_* project vars.)
#
# Effects (idempotent, bounded to $SLUG/ prefix):
#   ng build --configuration review --base-href /$SLUG/
#   s3 sync dist/ng-digibro-frontend/browser/ s3://$BUCKET/$SLUG/ --delete
#   cloudfront create-invalidation --distribution-id $DIST_ID --paths "/$SLUG/*"
#
# Consumes: review.env (04b) via needs:artifacts
# Serialized by: resource_group review-$CI_COMMIT_REF_SLUG
# Produces: review URL https://$REVIEW_CF_DOMAIN/$SLUG/index.html (environment:url in 04c)
# Out of scope: CORS on review HTTP API (tracked in TKT-REV-09 / #458)

# --- Required environment variables ------------------------------------------
: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"
: "${REVIEW_API_URL:?REVIEW_API_URL is required}"
: "${REVIEW_CF_DISTRIBUTION_ID:?REVIEW_CF_DISTRIBUTION_ID is required}"
: "${REVIEW_CF_DOMAIN:?REVIEW_CF_DOMAIN is required}"
: "${REVIEW_ASSETS_BUCKET:?REVIEW_ASSETS_BUCKET is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${ROLE_ARN:?ROLE_ARN is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/../lib/log.sh"

SLUG="${CI_COMMIT_REF_SLUG}"
echo "Review slug: ${SLUG}"

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

# --- Read dev CloudFormation stack outputs ------------------------------------
echo "Reading stack outputs from renate-chatbot-dev"
STACK_JSON=$(aws cloudformation describe-stacks \
  --stack-name renate-chatbot-dev \
  --output json)

extract_output() {
  local key="$1"
  printf '%s' "${STACK_JSON}" \
    | jq -r --arg k "$key" \
        '.Stacks[0].Outputs[] | select(.OutputKey | startswith($k)) | .OutputValue'
}

USER_POOL_ID=$(extract_output "AuthUserPoolId")
USER_POOL_CLIENT_ID=$(extract_output "AuthUserPoolClientId")
REGION=$(extract_output "Region")
REDIRECT_SIGNIN_URL=$(extract_output "RedirectSigninUrl")
REDIRECT_SIGNOUT_URL=$(extract_output "RedirectSignoutUrl")
COGNITO_DOMAIN=$(extract_output "CognitoDomain")

# --- Per-MR SPA mode toggles -------------------------------------------------
# Overridable from the review trigger file
# (deployments/review/${CI_COMMIT_REF_SLUG}.yml):
#
#   intern: true|false            # NG_APP_INTERN, default true
#   anonymous_access: true|false  # NG_APP_ANONYMOUS_ACCESS, default false
#
# The dev CDK stack does not export Intern/AnonymousAccess outputs, so these
# values are per-MR config, not stack passthroughs. Same tiny YAML parse shape
# as search_mode in review-deploy-backend.sh.
parse_trigger_bool() {
  local key="$1" default="$2" trigger_file val
  trigger_file="deployments/review/${CI_COMMIT_REF_SLUG}.yml"
  if [ ! -f "${trigger_file}" ]; then
    printf '%s' "${default}"
    return
  fi
  val=$(grep -E "^\s*${key}\s*:" "${trigger_file}" \
    | sed 's/^[^:]*:\s*//' | tr -d ' "'\''' | head -1 | tr '[:upper:]' '[:lower:]')
  case "${val}" in
    true|false) printf '%s' "${val}" ;;
    *)          printf '%s' "${default}" ;;
  esac
}

INTERN=$(parse_trigger_bool "intern" "true")
ANONYMOUS_ACCESS=$(parse_trigger_bool "anonymous_access" "false")
echo "SPA mode:        intern=${INTERN} anonymous_access=${ANONYMOUS_ACCESS}"

# Review frontend infra (RFC-0034): dedicated CloudFront + bucket owned by
# terraform/live/dev, exposed to CI as project-level variables.
DIST_ID="${REVIEW_CF_DISTRIBUTION_ID}"
BUCKET="${REVIEW_ASSETS_BUCKET}"
CF_URL="https://${REVIEW_CF_DOMAIN}"

echo "Distribution ID: ${DIST_ID}"
echo "Assets bucket:   ${BUCKET}"

# --- Angular build ------------------------------------------------------------
# Build runs inside the frontend dir (where angular.json + node_modules live).
# FRONTEND_DIR is overridable for tests; node_modules/.bin is prepended to PATH
# so the locally installed Angular CLI (npm ci) is used — there is no global ng.
FRONTEND_DIR="${FRONTEND_DIR:-drv-frontend}"
DIST_DIR="${FRONTEND_DIR}/dist/ng-digibro-frontend/browser"

section_start "ng_build" "Angular build — review config (slug: ${SLUG})"
(
  cd "${FRONTEND_DIR}"
  export PATH="${PWD}/node_modules/.bin:${PATH}"
  NG_APP_API_ENDPOINT="${REVIEW_API_URL}" \
  NG_APP_USER_POOL_ID="${USER_POOL_ID}" \
  NG_APP_USER_POOL_CLIENT_ID="${USER_POOL_CLIENT_ID}" \
  NG_APP_REGION="${REGION}" \
  NG_APP_INTERN="${INTERN}" \
  NG_APP_ANONYMOUS_ACCESS="${ANONYMOUS_ACCESS}" \
  NG_APP_REDIRECT_SIGNIN_URL="${REDIRECT_SIGNIN_URL}" \
  NG_APP_REDIRECT_SIGNOUT_URL="${REDIRECT_SIGNOUT_URL}" \
  NG_APP_COGNITO_DOMAIN="${COGNITO_DOMAIN}" \
  NG_APP_SHOW_REVIEW_TAG="true" \
    ng build \
      --configuration review \
      --base-href "/${SLUG}/"
)
section_end "ng_build"

# --- S3 sync ------------------------------------------------------------------
section_start "s3_sync" "S3 sync → s3://${BUCKET}/${SLUG}/"
aws s3 sync "${DIST_DIR}/" \
  "s3://${BUCKET}/${SLUG}/" \
  --delete
section_end "s3_sync"

# --- CloudFront invalidation --------------------------------------------------
section_start "cf_invalidation" "CloudFront invalidation for /${SLUG}/*"
aws cloudfront create-invalidation \
  --distribution-id "${DIST_ID}" \
  --paths "/${SLUG}/*"
section_end "cf_invalidation"

# --- Review URL — printed last, flush-left for clean copy-paste ---------------
log_section "REVIEW FRONTEND READY"
log_kv "Branch:" "${SLUG}"
log_url "${CF_URL}/${SLUG}/index.html"
log_done
