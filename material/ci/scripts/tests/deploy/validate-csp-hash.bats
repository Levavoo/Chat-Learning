#!/usr/bin/env bats
# Tests for validate-csp-hash.sh (new semantics after #682):
# Validates no inline <script> in index.html, no sha256- hash in frontend.ts,
# and that the Matomo domain is present in script-src.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/validate-csp-hash.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/drv-frontend/src"
  mkdir -p "$TEST_DIR/cdk/lib/constructs"

  # Default: valid state (no script, no hash, domain present)
  cat >"$TEST_DIR/drv-frontend/src/index.html" <<'EOF'
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <title>DRV RentenChatBot</title>
  </head>
  <body>
    <drv-root></drv-root>
  </body>
</html>
EOF

  cat >"$TEST_DIR/cdk/lib/constructs/frontend.ts" <<'EOF'
const cspValue = [
  "default-src 'self'",
  "script-src 'self' https://www.deutsche-rentenversicherung.de",
  "connect-src 'self' https://www.deutsche-rentenversicherung.de",
].join('; ');
EOF
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Pass cases ────────────────────────────────────────────────────────────────

@test "[validate-csp-hash] no inline script + no hash + domain present → pass" {
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ CSP validation passed"* ]]
}

@test "[validate-csp-hash] works with the real project files" {
  run bash "$SCRIPT" "."
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ CSP validation passed"* ]]
}

# ── Fail cases ────────────────────────────────────────────────────────────────

@test "[validate-csp-hash] inline <script> in index.html → fail" {
  cat >"$TEST_DIR/drv-frontend/src/index.html" <<'EOF'
<!doctype html>
<html>
  <head>
    <script>var _paq = [];</script>
  </head>
  <body><drv-root></drv-root></body>
</html>
EOF
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"inline <script>"* ]]
}

@test "[validate-csp-hash] sha256- hash present in frontend.ts → fail" {
  cat >"$TEST_DIR/cdk/lib/constructs/frontend.ts" <<'EOF'
const matomoScriptHash = 'sha256-eceBA++fFG1v+N1lKG22hjT2UUkQ0gD6TUwTXN6nUtg=';
const cspValue = [
  "script-src 'self' 'sha256-eceBA++fFG1v+N1lKG22hjT2UUkQ0gD6TUwTXN6nUtg=' https://www.deutsche-rentenversicherung.de",
].join('; ');
EOF
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"sha256-"* ]]
}

@test "[validate-csp-hash] index.html not found → fail" {
  rm "$TEST_DIR/drv-frontend/src/index.html"
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not found"* ]]
}

@test "[validate-csp-hash] frontend.ts not found → fail" {
  rm "$TEST_DIR/cdk/lib/constructs/frontend.ts"
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not found"* ]]
}

@test "[validate-csp-hash] Matomo domain missing from frontend.ts → fail" {
  cat >"$TEST_DIR/cdk/lib/constructs/frontend.ts" <<'EOF'
const cspValue = [
  "script-src 'self'",
].join('; ');
EOF
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"deutsche-rentenversicherung.de"* ]]
}

@test "[validate-csp-hash] Matomo domain in connect-src but not script-src → fail" {
  cat >"$TEST_DIR/cdk/lib/constructs/frontend.ts" <<'EOF'
const cspValue = [
  "script-src 'self'",
  "connect-src 'self' https://www.deutsche-rentenversicherung.de",
].join('; ');
EOF
  run bash "$SCRIPT" "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == *"script-src does not contain"* ]]
}
