#!/usr/bin/env bash
set -euo pipefail

readonly DIST_INDEX="dist/ng-digibro-frontend/browser/index.html"
readonly OPTIONAL_IDP_VARIABLES=(
  NG_APP_REDIRECT_SIGNIN_URL
  NG_APP_REDIRECT_SIGNOUT_URL
  NG_APP_COGNITO_DOMAIN
)

unset "${OPTIONAL_IDP_VARIABLES[@]}"
for variable in "${OPTIONAL_IDP_VARIABLES[@]}"; do
  if [[ -v "$variable" ]]; then
    echo "frontend browser smoke: $variable must be unset" >&2
    exit 1
  fi
done
printf 'Optional IdP variables are unset: %s\n' "${OPTIONAL_IDP_VARIABLES[*]}"

export NG_APP_API_ENDPOINT=""
export NG_APP_USER_POOL_ID="eu-central-1_smoketest"
export NG_APP_USER_POOL_CLIENT_ID="1234567890abcdefghijklmnop"
export NG_APP_REGION="eu-central-1"
export NG_APP_ANONYMOUS_ACCESS="false"
export NG_APP_INTERN="false"
export FRONTEND_ANONYMOUS_ACCESS="$NG_APP_ANONYMOUS_ACCESS"
printf 'Required frontend variables are set: %s\n' \
  'NG_APP_API_ENDPOINT NG_APP_USER_POOL_ID NG_APP_USER_POOL_CLIENT_ID NG_APP_REGION NG_APP_ANONYMOUS_ACCESS NG_APP_INTERN'

if [[ -z "${CHROME_BIN:-}" ]]; then
  for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME_BIN="$(command -v "$candidate")"
      export CHROME_BIN
      break
    fi
  done
fi

if [[ -z "${CHROME_BIN:-}" || ! -x "$CHROME_BIN" ]]; then
  echo 'frontend browser smoke: no executable Chromium found; set CHROME_BIN to the existing browser binary' >&2
  exit 1
fi
printf 'Using existing Chromium: %s\n' "$CHROME_BIN"

npm run build:prod

if [[ ! -f "$DIST_INDEX" ]]; then
  echo "frontend browser smoke: production artifact missing at $DIST_INDEX" >&2
  exit 1
fi

npm run test:smoke:browser
