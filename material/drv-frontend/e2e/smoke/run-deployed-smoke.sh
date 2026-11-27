#!/usr/bin/env bash
set -euo pipefail

: "${FRONTEND_BASE_URL:?FRONTEND_BASE_URL is required; no fallback URL is allowed}"
: "${ENV_LABEL:?ENV_LABEL is required}"
: "${FRONTEND_ENTRYPOINT_PATH:?FRONTEND_ENTRYPOINT_PATH is required}"
: "${FRONTEND_ENTRYPOINT_SHA256:?FRONTEND_ENTRYPOINT_SHA256 is required}"
: "${FRONTEND_ANONYMOUS_ACCESS:?FRONTEND_ANONYMOUS_ACCESS is required}"

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
  echo 'deployed frontend smoke: no executable Chromium found; set CHROME_BIN to the existing browser binary' >&2
  exit 1
fi

printf 'Deployed frontend smoke [%s]: %s/ (anonymousAccess=%s)\n' \
  "$ENV_LABEL" "${FRONTEND_BASE_URL%/}" "$FRONTEND_ANONYMOUS_ACCESS"
printf 'Using existing Chromium: %s\n' "$CHROME_BIN"
printf 'No frontend build, local server, browser download, AWS lookup, or login will run.\n'

node e2e/smoke/wait-for-deployed-entrypoint.mjs
npm run test:smoke:deployed:browser
