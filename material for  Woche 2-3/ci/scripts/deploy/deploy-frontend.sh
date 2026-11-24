#!/usr/bin/env bash
set -euo pipefail

# #648 — Build + deploy Angular frontend to per-env S3 + CloudFront.
#
# Replaces the CDK-side @cdklabs/deploy-time-build NodejsBuild for dev/qa/preprod.
# One build path, visible in the GitLab job UI, no CFN asset-packaging games.
#
# Contract
# --------
# Args:
#   $1  env: dev | qa | preprod
#
# Env (required, exits non-zero if unset):
#   GITLAB_OIDC_TOKEN, CI_JOB_ID   — from GitLab id_tokens
#   ROLE_ARN                       — ki-lab-digibro-<env>-frontend-deploy
#   AWS_DEFAULT_REGION
#
# Reads (no mutation):
#   cloudformation describe-stacks --stack-name renate-chatbot-<env>
#     → Frontend* outputs (bucket, distribution id, url)
#     → Auth*     outputs (user pool + client id)
#   deployments/<env>/config.yaml
#     → anonymousAccess, intern (booleans → NG_APP_ANONYMOUS_ACCESS/NG_APP_INTERN)
#
# Effects (idempotent, bounded to root of the env's assets bucket):
#   npm run build:<env>                                     (angular.json config)
#   cp -r src/maintenance-page/. → _maintenance/
#   aws s3 sync   dist/… s3://<bucket>/  --delete           (bucket root)
#   aws cloudfront create-invalidation --paths "/*"         (no --wait, matches NodejsBuild)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/log.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/log.sh"
# shellcheck source=../lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

GET_STACK_OUTPUTS="${SCRIPT_DIR}/../util/get-stack-outputs.sh"

ENV_ARG="${1:-}"
[[ -n "$ENV_ARG" ]] || { echo "usage: deploy-frontend.sh <env>" >&2; exit 1; }

# Supported envs — dev/qa/preprod/prod. demo out of scope (see #648).
case "$ENV_ARG" in
  dev|qa|preprod|prod) ;;
  *) echo "deploy-frontend: unsupported env '$ENV_ARG' (allowed: dev qa preprod prod)" >&2; exit 1 ;;
esac

: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${ROLE_ARN:?ROLE_ARN is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"

STACK="renate-chatbot-${ENV_ARG}"

# npm build script per env — mirrors AngularFrontend.resolveBuildScript
# (cdk/lib/constructs/frontend.ts) so the artifact is bit-for-bit equivalent
# input-wise. preprod shares the production Angular config.
case "$ENV_ARG" in
  dev)     BUILD_SCRIPT="build:dev" ;;
  qa)      BUILD_SCRIPT="build:qa"  ;;
  preprod) BUILD_SCRIPT="build:prod" ;;
  prod)    BUILD_SCRIPT="build:prod" ;;
esac

FRONTEND_DIR="${FRONTEND_DIR:-drv-frontend}"
DIST_DIR="${FRONTEND_DIR}/dist/ng-digibro-frontend/browser"
MAINT_SRC="${FRONTEND_DIR}/src/maintenance-page"
CONFIG_YAML="deployments/${ENV_ARG}/config.yaml"

# --- OIDC assume-role ---------------------------------------------------------
assume_deploy_role "$ROLE_ARN"

# --- Stack outputs ------------------------------------------------------------
log_section "Reading stack outputs"
log_kv "Stack:" "$STACK"

OUTPUTS_JSON="$(mktemp)"
trap 'rm -f "$OUTPUTS_JSON"' EXIT
bash "$GET_STACK_OUTPUTS" "$STACK" "$OUTPUTS_JSON"

# CDK CfnOutput logical IDs carry an 8-hex suffix (e.g.
# FrontendCloudFrontDistributionIdC60423D7). Match by prefix.
extract_output() {
  local prefix="$1"
  jq -r --arg stack "$STACK" --arg p "$prefix" \
    '.[$stack] | to_entries | .[] | select(.key | startswith($p)) | .value' \
    "$OUTPUTS_JSON" | head -n1
}

DIST_ID="$(extract_output "FrontendCloudFrontDistributionId")"
BUCKET="$(extract_output "FrontendFrontendS3BucketName")"
CF_URL="$(extract_output "FrontendCloudFrontDistributionUrl")"
USER_POOL_ID="$(extract_output "AuthUserPoolId")"
USER_POOL_CLIENT_ID="$(extract_output "AuthUserPoolClientId")"

[[ -n "$DIST_ID" ]] || { echo "Missing FrontendCloudFrontDistributionId in $STACK outputs" >&2; exit 1; }
[[ -n "$BUCKET"  ]] || { echo "Missing FrontendS3BucketName in $STACK outputs" >&2; exit 1; }
[[ -n "$CF_URL" && "$CF_URL" != "null" ]] || { echo "Missing FrontendCloudFrontDistributionUrl in $STACK outputs" >&2; exit 1; }
[[ -n "$USER_POOL_ID" ]] || { echo "Missing AuthUserPoolId in $STACK outputs" >&2; exit 1; }
[[ -n "$USER_POOL_CLIENT_ID" ]] || { echo "Missing AuthUserPoolClientId in $STACK outputs" >&2; exit 1; }

log_kv "Bucket:"   "$BUCKET"
log_kv "Dist ID:"  "$DIST_ID"
log_kv "URL:"      "$CF_URL"

# --- Per-env feature flags from deployments/<env>/config.yaml -----------------
# awk is portable across the node-aws image; yq is not installed there.
# Missing key defaults to the CDK schema default (false for both).
read_yaml_bool() {
  local key="$1" file="$2"
  awk -v key="$key" '
    $0 ~ "^"key":" {
      sub(/[[:space:]]*#.*/, "")
      v = $2
      gsub(/[[:space:]]/, "", v)
      if (v == "true" || v == "false") { print v; exit }
    }
  ' "$file"
}

ANONYMOUS_ACCESS="false"
INTERN="false"
if [[ -f "$CONFIG_YAML" ]]; then
  v="$(read_yaml_bool anonymousAccess "$CONFIG_YAML")" && [[ -n "$v" ]] && ANONYMOUS_ACCESS="$v"
  v="$(read_yaml_bool intern          "$CONFIG_YAML")" && [[ -n "$v" ]] && INTERN="$v"
fi
log_kv "anonymousAccess:" "$ANONYMOUS_ACCESS"
log_kv "intern:"          "$INTERN"

# --- Angular build ------------------------------------------------------------
# NG_APP_API_ENDPOINT is intentionally empty — the frontend calls /api/* via
# CloudFront, not a direct API Gateway URL. Matches chatbot-stack.ts:285.
# IdP-conditional vars (NG_APP_REDIRECT_SIGNIN_URL, NG_APP_COGNITO_DOMAIN…) are
# omitted: dev/qa/preprod use identityProvider([]) so isExist() is false today.
section_start "ng_build" "Angular build — ${BUILD_SCRIPT} (env: ${ENV_ARG})"
(
  cd "$FRONTEND_DIR"
  export PATH="${PWD}/node_modules/.bin:${PATH}"
  NG_APP_API_ENDPOINT="" \
  NG_APP_USER_POOL_ID="$USER_POOL_ID" \
  NG_APP_USER_POOL_CLIENT_ID="$USER_POOL_CLIENT_ID" \
  NG_APP_REGION="$AWS_DEFAULT_REGION" \
  NG_APP_ANONYMOUS_ACCESS="$ANONYMOUS_ACCESS" \
  NG_APP_INTERN="$INTERN" \
    npm run "$BUILD_SCRIPT"
)
section_end "ng_build"

# --- EntryPoint fingerprint ---------------------------------------------------
# Resolve and hash the local bundle before any S3 mutation. A filename alone is
# insufficient for dev because main.js can remain stable across builds.
INDEX_FILE="${DIST_DIR}/index.html"
[[ -f "$INDEX_FILE" ]] || {
  echo "Frontend build output is missing $INDEX_FILE" >&2
  exit 1
}

FRONTEND_ENTRYPOINT_PATH="$(
  while IFS= read -r src_attribute; do
    asset="${src_attribute#src=\"}"
    asset="${asset%\"}"
    asset="${asset%%\?*}"
    asset="${asset#./}"
    asset="${asset#/}"
    case "${asset##*/}" in
      main.js|main-*.js|main.*.js)
        printf '%s\n' "$asset"
        break
        ;;
    esac
  done < <(grep -oE 'src="[^"]+\.js([?#][^"]*)?"' "$INDEX_FILE" || true)
)"

[[ -n "$FRONTEND_ENTRYPOINT_PATH" ]] || {
  echo "Could not find the main JavaScript EntryPoint in $INDEX_FILE" >&2
  exit 1
}
[[ "$FRONTEND_ENTRYPOINT_PATH" != *".."* ]] || {
  echo "Unsafe frontend EntryPoint path: $FRONTEND_ENTRYPOINT_PATH" >&2
  exit 1
}

ENTRYPOINT_FILE="${DIST_DIR}/${FRONTEND_ENTRYPOINT_PATH}"
[[ -f "$ENTRYPOINT_FILE" ]] || {
  echo "Frontend EntryPoint referenced by index.html is missing: $ENTRYPOINT_FILE" >&2
  exit 1
}
FRONTEND_ENTRYPOINT_SHA256="$(sha256sum "$ENTRYPOINT_FILE" | awk '{print $1}')"
[[ "$FRONTEND_ENTRYPOINT_SHA256" =~ ^[a-f0-9]{64}$ ]] || {
  echo "Could not calculate SHA-256 for $ENTRYPOINT_FILE" >&2
  exit 1
}

log_kv "EntryPoint:" "$FRONTEND_ENTRYPOINT_PATH"
log_kv "EntryPoint SHA-256:" "$FRONTEND_ENTRYPOINT_SHA256"

# --- Maintenance mode assets --------------------------------------------------
# NodejsBuild materialised these under _maintenance/ inside the dist tree.
# See cdk/lib/constructs/frontend.ts:454-455.
section_start "maintenance_assets" "Copy maintenance assets into dist/_maintenance/"
mkdir -p "${DIST_DIR}/_maintenance"
cp -r "${MAINT_SRC}/." "${DIST_DIR}/_maintenance/"
section_end "maintenance_assets"

# --- S3 sync ------------------------------------------------------------------
# --delete matches NodejsBuild's full-replacement semantics. Bucket root, not
# a prefix — this bucket only holds frontend assets.
section_start "s3_sync" "S3 sync → s3://${BUCKET}/"
aws s3 sync "${DIST_DIR}/" "s3://${BUCKET}/" --delete
section_end "s3_sync"

# --- CloudFront invalidation --------------------------------------------------
# Async by design — matches NodejsBuild's async invalidation. The downstream
# browser smoke waits with a fixed budget until CloudFront serves the exact
# local EntryPoint content fingerprint emitted below.
section_start "cf_invalidation" "CloudFront invalidation /*"
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/*"
section_end "cf_invalidation"

# --- Deploy evidence ----------------------------------------------------------
# frontend.yml publishes this file as a dotenv report. FRONTEND_DEPLOYED=true
# is written only after build, upload, invalidation, and evidence generation all
# succeeded. Dev deploys unconditionally, so its downstream browser gate always
# receives evidence bound to the deployment from the same pipeline. The
# authentication value is the exact input used for the Angular build, allowing
# the browser smoke to derive the expected landing page without per-env CI logic.
DOTENV_FILE="${DEPLOY_FRONTEND_DOTENV:-deploy-frontend.env}"
{
  echo "FRONTEND_DEPLOYED=true"
  echo "CF_URL=${CF_URL%/}/"
  echo "FRONTEND_ENTRYPOINT_PATH=${FRONTEND_ENTRYPOINT_PATH}"
  echo "FRONTEND_ENTRYPOINT_SHA256=${FRONTEND_ENTRYPOINT_SHA256}"
  echo "FRONTEND_ANONYMOUS_ACCESS=${ANONYMOUS_ACCESS}"
} >"$DOTENV_FILE"

# --- Done ---------------------------------------------------------------------
log_section "FRONTEND DEPLOYED"
log_kv "Env:"    "$ENV_ARG"
log_kv "Bucket:" "$BUCKET"
log_url "${CF_URL}/"
log_done
