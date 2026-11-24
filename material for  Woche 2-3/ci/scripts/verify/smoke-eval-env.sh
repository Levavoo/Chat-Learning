#!/usr/bin/env bash
set -euo pipefail
# smoke-eval-env.sh <env>
# Generic smoke eval: assumes role, resolves ApiUrl from CloudFormation,
# polls GET /health with exponential backoff + jitter (AWS Well-Architected: REL).
#
# Retry strategy (transient errors only — Lambda cold start, throttle):
#   max attempts: SMOKE_MAX_ATTEMPTS (default 5)
#   base delay:   SMOKE_BASE_DELAY_S (default 4s)
#   max delay:    SMOKE_MAX_DELAY_S  (default 60s)
#   jitter:       ±25% of computed delay
#
# Required: GITLAB_OIDC_TOKEN, CI_JOB_ID, CDK_DEPLOY_ROLE_ARN_<ENV>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

ENV="${1:-}"
_deploy_validate_env "$ENV" || exit 1

ENV_UPPER="${ENV^^}"
ROLE_VAR="CDK_DEPLOY_ROLE_ARN_${ENV_UPPER}"
ROLE_ARN="${!ROLE_VAR:?${ROLE_VAR} is required but not set}"
STACK="renate-chatbot-${ENV}"

SMOKE_MAX_ATTEMPTS="${SMOKE_MAX_ATTEMPTS:-5}"
SMOKE_BASE_DELAY_S="${SMOKE_BASE_DELAY_S:-4}"
SMOKE_MAX_DELAY_S="${SMOKE_MAX_DELAY_S:-60}"

# _smoke_get <label> <url> — GET <url> with exponential backoff + jitter.
# Returns 0 on the first 2xx; 1 once SMOKE_MAX_ATTEMPTS is exhausted.
_smoke_get() {
  local label="$1" url="$2"
  local attempt=1 raw_delay jitter delay

  echo "Smoke eval [${ENV}]: GET ${url} (${label})"

  while [[ $attempt -le $SMOKE_MAX_ATTEMPTS ]]; do
    if curl -sf -o /dev/null --max-time 30 "$url"; then
      return 0
    fi

    if [[ $attempt -lt $SMOKE_MAX_ATTEMPTS ]]; then
      # Exponential backoff: base * 2^(attempt-1), capped, ±25% jitter
      raw_delay=$(( SMOKE_BASE_DELAY_S * (1 << (attempt - 1)) ))
      if [[ $raw_delay -gt $SMOKE_MAX_DELAY_S ]]; then
        raw_delay=$SMOKE_MAX_DELAY_S
      fi
      # Jitter: ±25% — add random 0..50% of base, subtract 25%
      jitter=$(( (RANDOM % (raw_delay / 2 + 1)) - raw_delay / 4 ))
      delay=$(( raw_delay + jitter ))
      [[ $delay -lt 1 ]] && delay=1
      echo "Smoke eval [${ENV}]: ${label} attempt ${attempt}/${SMOKE_MAX_ATTEMPTS} failed — retry in ${delay}s"
      sleep "$delay"
    fi

    attempt=$(( attempt + 1 ))
  done

  echo "Smoke eval [${ENV}]: ${label} FAILED after ${SMOKE_MAX_ATTEMPTS} attempts" >&2
  return 1
}

assume_deploy_role "$ROLE_ARN"

API_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text)

[[ -n "$API_URL" && "$API_URL" != "None" ]] \
  || { echo "CloudFormation output ApiUrl not found in stack $STACK" >&2; exit 1; }

# Frontend: the CloudFront distribution URL. The output key is prefixed with
# the 'Frontend' construct id in the CFN stack.
CF_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendCloudFrontDistributionUrl')].OutputValue | [0]" \
  --output text)

[[ -n "$CF_URL" && "$CF_URL" != "None" ]] \
  || { echo "CloudFormation output FrontendCloudFrontDistributionUrl not found in stack $STACK" >&2; exit 1; }

_smoke_get "health" "${API_URL}health" || exit 1
_smoke_get "frontend" "${CF_URL}/" || exit 1

echo "Smoke eval [${ENV}]: OK"
exit 0
