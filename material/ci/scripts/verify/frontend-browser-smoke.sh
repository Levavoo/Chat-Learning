#!/usr/bin/env bash
set -euo pipefail

: "${ENV_LABEL:?ENV_LABEL is required}"

case "${FRONTEND_DEPLOYED:-}" in
  true) ;;
  '')
    echo 'frontend browser smoke: FRONTEND_DEPLOYED is missing from deploy-frontend.env' >&2
    exit 1
    ;;
  *)
    echo "frontend browser smoke: FRONTEND_DEPLOYED must be true, got '${FRONTEND_DEPLOYED}'" >&2
    exit 1
    ;;
esac

: "${CF_URL:?CF_URL is required when FRONTEND_DEPLOYED=true}"
: "${FRONTEND_ENTRYPOINT_PATH:?FRONTEND_ENTRYPOINT_PATH is required when FRONTEND_DEPLOYED=true}"
: "${FRONTEND_ENTRYPOINT_SHA256:?FRONTEND_ENTRYPOINT_SHA256 is required when FRONTEND_DEPLOYED=true}"

require_boolean() {
  local name="$1"
  local value="${!name-}"

  case "$value" in
    true|false) ;;
    '')
      echo "frontend browser smoke: ${name} is missing from deploy-frontend.env" >&2
      exit 1
      ;;
    *)
      echo "frontend browser smoke: ${name} must be true or false, got '${value}'" >&2
      exit 1
      ;;
  esac
}

require_boolean FRONTEND_ANONYMOUS_ACCESS

export FRONTEND_BASE_URL="$CF_URL"

cd drv-frontend
npm run test:smoke:deployed
