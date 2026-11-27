#!/usr/bin/env bash
# Validates that the frontend has no inline scripts and that the CDK CSP
# config correctly allows the external Matomo domain without a sha256 hash.
#
# Replaces the old hash-comparison logic: Matomo is now loaded dynamically
# via MatomoService (no inline script) so no CSP hash is needed or wanted.
#
# Checks:
#   1. index.html contains NO <script> tag (regression guard)
#   2. frontend.ts script-src contains NO sha256- hash
#   3. frontend.ts script-src contains https://www.deutsche-rentenversicherung.de
set -euo pipefail

REPO_ROOT="${1:-.}"
INDEX_HTML="${REPO_ROOT}/drv-frontend/src/index.html"
FRONTEND_TS="${REPO_ROOT}/cdk/lib/constructs/frontend.ts"

PASS=0

# --- 1. index.html must not contain any <script> tag ---
if [[ ! -f "$INDEX_HTML" ]]; then
  echo "❌ ERROR: $INDEX_HTML not found" >&2
  exit 1
fi

if grep -q '<script' "$INDEX_HTML"; then
  echo "❌ index.html contains an inline <script> tag — this should not exist." >&2
  echo "   Matomo is loaded dynamically via MatomoService. Remove any inline scripts." >&2
  PASS=1
else
  echo "✅ index.html contains no inline <script> tag"
fi

# --- 2. frontend.ts script-src must NOT contain a sha256- hash ---
if [[ ! -f "$FRONTEND_TS" ]]; then
  echo "❌ ERROR: $FRONTEND_TS not found" >&2
  exit 1
fi

if grep -q "sha256-" "$FRONTEND_TS"; then
  echo "❌ frontend.ts contains a sha256- hash in script-src — not needed without inline scripts." >&2
  echo "   Remove the matomoScriptHash variable from cdk/lib/constructs/frontend.ts." >&2
  PASS=1
else
  echo "✅ frontend.ts script-src contains no sha256- hash"
fi

# --- 3. frontend.ts script-src must contain the Matomo domain ---
# Extract the line containing the script-src CSP directive (not comments).
SCRIPT_SRC_LINE=$(grep "script-src" "$FRONTEND_TS" | grep -v "^[[:space:]]*//" | head -1)
if [[ -z "$SCRIPT_SRC_LINE" ]]; then
  echo "❌ frontend.ts does not contain a script-src directive" >&2
  PASS=1
elif ! grep -q "https://www.deutsche-rentenversicherung.de" <<<"$SCRIPT_SRC_LINE"; then
  echo "❌ frontend.ts script-src does not contain https://www.deutsche-rentenversicherung.de" >&2
  echo "   Required for dynamically loaded matomo.js." >&2
  PASS=1
else
  echo "✅ frontend.ts script-src contains https://www.deutsche-rentenversicherung.de"
fi

# --- Result ---
if [[ "$PASS" -ne 0 ]]; then
  exit 1
fi

echo "✅ CSP validation passed"
exit 0
