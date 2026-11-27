#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/render-deployment-page.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  OUTPUTS="$TEST_DIR/outputs.json"
  # Pin the volatile header fields so output is deterministic in tests.
  export RENDER_TIMESTAMP="2026-06-23T10:00:00Z"
  export RENDER_VERSION="testver"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Line number (1-based) of the first output line matching a pattern.
_line_of() {
  printf '%s\n' "$output" | grep -n -- "$1" | head -n1 | cut -d: -f1
}

@test "[render-deployment-page] missing env arg → exit 1 with usage" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "[render-deployment-page] happy path → header + sections, exit 0" {
  cat >"$OUTPUTS" <<'EOF'
{
  "renate-chatbot-dev": {
    "ApiChatEndpoint": "https://abc.execute-api.eu-central-1.amazonaws.com/prod/api/chat",
    "AccessLogGroup": "/aws/apigateway/renate-apigateway-dev"
  }
}
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  # Header line carries env + last-updated + version.
  [[ "$output" == *"# Deployment outputs — dev"* ]]
  [[ "$output" == *"Last updated: 2026-06-23T10:00:00Z"* ]]
  # Version is surfaced as its own Quick access line.
  [[ "$output" == *"- Version: testver"* ]]
  # Fixed section order.
  qa="$(_line_of '## Quick access')"
  ke="$(_line_of '## Key endpoints')"
  ids="$(_line_of '## Important IDs')"
  all="$(_line_of '## All outputs')"
  [ "$qa" -lt "$ke" ]
  [ "$ke" -lt "$ids" ]
  [ "$ids" -lt "$all" ]
  # All outputs lists each entry in a table row.
  [[ "$output" == *"| renate-chatbot-dev | AccessLogGroup | /aws/apigateway/renate-apigateway-dev |"* ]]
}

@test "[render-deployment-page] URL values render as Markdown links" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[https://x.example.com/prod/](https://x.example.com/prod/)"* ]]
  # Quick-access API base resolves from the exact ApiUrl key.
  [[ "$output" == *"- API base: [https://x.example.com/prod/](https://x.example.com/prod/)"* ]]
}

@test "[render-deployment-page] missing slots render as n/a" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-dev": { "SomeUnrelatedKey": "value" } }
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Frontend (CloudFront): n/a"* ]]
  [[ "$output" == *"- Guardrails: ID=n/a · Version=n/a"* ]]
  [[ "$output" == *"- API base: n/a"* ]]
  [[ "$output" == *"| CloudFront URL | n/a |"* ]]
  [[ "$output" == *"| API Gateway ID | n/a |"* ]]
}

@test "[render-deployment-page] guardrail id and version resolve into Quick access" {
  # CDK appends a hash suffix to logical ids, so the fuzzy guardrail+id /
  # guardrail+version candidates must resolve these prefixed keys.
  cat >"$OUTPUTS" <<'EOF'
{
  "renate-chatbot-dev": {
    "GuardrailGuardrailArnEB581131": "arn:aws:bedrock:eu-central-1:831926590742:guardrail/66ls9ief56x8",
    "GuardrailGuardrailId494F4212": "66ls9ief56x8",
    "GuardrailGuardrailVersionOutputF2C265AE": "DRAFT"
  }
}
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Guardrails: ID=66ls9ief56x8 · Version=DRAFT"* ]]
}

@test "[render-deployment-page] exact key wins over fuzzy match for a slot" {
  # Both an exact ApiUrl and a fuzzy 'api'+'url' key exist; exact must win.
  cat >"$OUTPUTS" <<'EOF'
{
  "renate-chatbot-dev": {
    "ApiUrl": "https://exact.example.com/prod/",
    "ApiGatewayApiGatewayUrl4372BE92": "https://fuzzy.example.com/prod/"
  }
}
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- API base: [https://exact.example.com/prod/](https://exact.example.com/prod/)"* ]]
}

@test "[render-deployment-page] fuzzy slots resolve from prefixed/suffixed keys" {
  cat >"$OUTPUTS" <<'EOF'
{
  "renate-chatbot-dev": {
    "FrontendCloudFrontDistributionUrl650AAAFD": "https://d11u.cloudfront.net",
    "FrontendCloudFrontDistributionIdC60423D7": "EVF377ANHHHC9",
    "ApiGatewayApiGatewayId8E95341B": "ime50ezq2b",
    "ApiGatewayApiGatewayRootResourceIdB8FB7888": "mylnnjaur8"
  }
}
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Frontend (CloudFront): [https://d11u.cloudfront.net](https://d11u.cloudfront.net)"* ]]
  [[ "$output" == *"| CloudFront Distribution ID | EVF377ANHHHC9 |"* ]]
  # On a fuzzy tie, lexicographically smallest <stack>.<key> wins:
  # ApiGatewayApiGatewayId... < ApiGatewayApiGatewayRootResourceId...
  [[ "$output" == *"| API Gateway ID | ime50ezq2b |"* ]]
}

@test "[render-deployment-page] multiple stacks → all outputs, globally sorted" {
  cat >"$OUTPUTS" <<'EOF'
{
  "renate-chatbot-qa": { "Beta": "qb" },
  "renate-chatbot-dev": { "Alpha": "da" }
}
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"| renate-chatbot-dev | Alpha | da |"* ]]
  [[ "$output" == *"| renate-chatbot-qa | Beta | qb |"* ]]
  # dev stack sorts before qa stack regardless of JSON order.
  dev="$(_line_of '| renate-chatbot-dev | Alpha |')"
  qa="$(_line_of '| renate-chatbot-qa | Beta |')"
  [ "$dev" -lt "$qa" ]
}

@test "[render-deployment-page] output is byte-identical across runs and sorted" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-dev": { "Zebra": "z", "Alpha": "a", "Mango": "m" } }
EOF
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  first="$output"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [ "$output" = "$first" ]
  a="$(_line_of '| renate-chatbot-dev | Alpha |')"
  m="$(_line_of '| renate-chatbot-dev | Mango |')"
  z="$(_line_of '| renate-chatbot-dev | Zebra |')"
  [ "$a" -lt "$m" ]
  [ "$m" -lt "$z" ]
}

@test "[render-deployment-page] values are published raw (never masked)" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-qa": { "AccountId": "571600837515", "ApiUrl": "https://x.example.com/prod/" } }
EOF
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"| renate-chatbot-qa | AccountId | 571600837515 |"* ]]
  [[ "$output" == *"| renate-chatbot-qa | ApiUrl | [https://x.example.com/prod/](https://x.example.com/prod/) |"* ]]
}

@test "[render-deployment-page] missing outputs file → exit 1 with clear error" {
  run bash "$SCRIPT" dev "$TEST_DIR/does-not-exist.json"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not found"* ]]
}

@test "[render-deployment-page] empty outputs file → exit 1 with clear error" {
  : >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 1 ]
  [[ "$output" == *"empty"* ]]
}

@test "[render-deployment-page] empty JSON object → exit 1 (no outputs)" {
  echo '{}' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 1 ]
  [[ "$output" == *"no outputs"* ]]
}

@test "[render-deployment-page] stack with no outputs is tolerated → exit 1 (no outputs)" {
  echo '{ "renate-chatbot-dev": {} }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 1 ]
  [[ "$output" == *"no outputs"* ]]
}

@test "[render-deployment-page] invalid JSON → exit 1 with clear error" {
  printf 'not json {{{\n' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a valid JSON object"* ]]
}

# ── Maintenance marker (TKT-MM-03) ────────────────────────────────────────────
# The flag comes from deployments/<env>/version.yaml; tests point
# RENDER_VERSION_FILE at a fixture file so they never depend on repo state.

@test "[render-deployment-page] maintenance: true → -maintenance suffix + banner" {
  printf 'version: 9.9.9\nmaintenance: true\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver-maintenance"* ]]
  [[ "$output" == *"> ⚠️ **MAINTENANCE MODE ACTIVE**"* ]]
  # Banner sits under the page header, above Quick access.
  banner="$(_line_of 'MAINTENANCE MODE ACTIVE')"
  quick="$(_line_of '## Quick access')"
  [ "$banner" -lt "$quick" ]
}

@test "[render-deployment-page] maintenance: false → normal render" {
  printf 'version: 9.9.9\nmaintenance: false\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver"* ]]
  [[ "$output" != *"-maintenance"* ]]
  [[ "$output" != *"MAINTENANCE MODE ACTIVE"* ]]
}

@test "[render-deployment-page] maintenance key absent → normal render" {
  printf 'version: 9.9.9\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver"* ]]
  [[ "$output" != *"-maintenance"* ]]
  [[ "$output" != *"MAINTENANCE MODE ACTIVE"* ]]
}

@test "[render-deployment-page] version file missing (dev case) → normal render" {
  export RENDER_VERSION_FILE="$TEST_DIR/does-not-exist.yaml"
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver"* ]]
  [[ "$output" != *"MAINTENANCE MODE ACTIVE"* ]]
}

@test "[render-deployment-page] maintenance value tolerates extra whitespace" {
  printf 'version: 9.9.9\nmaintenance:    true   \n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver-maintenance"* ]]
}

@test "[render-deployment-page] maintenance true with inline comment still enables marker" {
  printf 'version: 9.9.9\nmaintenance: true # scheduled window\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Version: testver-maintenance"* ]]
  [[ "$output" == *"MAINTENANCE MODE ACTIVE"* ]]
}

@test "[render-deployment-page] maintenance page is byte-identical across runs" {
  printf 'version: 9.9.9\nmaintenance: true\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  echo '{ "renate-chatbot-qa": { "Zebra": "z", "Alpha": "a" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  first="$output"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [ "$output" = "$first" ]
}

# ── Degraded-rollback marker banner (#628) ────────────────────────────────────
# RENDER_ROLLBACK_DEGRADED is caller-supplied; the renderer stays AWS-free and
# never requires the value to parse (presence wins per the spec's fail-safe
# constraint) so a real marker can never silently fail to render.

@test "[render-deployment-page] non-empty degraded marker (JSON) renders an enriched banner" {
  export RENDER_ROLLBACK_DEGRADED='{"schema_version":1,"release_id":"sha256-abc123","candidate_slot":"green","opened_at":"2026-07-22T08:00:00Z"}'
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"🔴 **RETRIEVAL ROLLBACK DEGRADED**"* ]]
  [[ "$output" == *"release sha256-abc123"* ]]
  [[ "$output" == *"since 2026-07-22T08:00:00Z"* ]]
  # Banner sits under the page header, above Quick access.
  banner="$(_line_of 'RETRIEVAL ROLLBACK DEGRADED')"
  quick="$(_line_of '## Quick access')"
  [ "$banner" -lt "$quick" ]
}

@test "[render-deployment-page] non-empty degraded marker (unparseable string) still renders a banner" {
  export RENDER_ROLLBACK_DEGRADED='not-json-but-still-present'
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"🔴 **RETRIEVAL ROLLBACK DEGRADED**"* ]]
  [[ "$output" != *"release"* ]]
}

@test "[render-deployment-page] empty degraded marker renders no banner" {
  export RENDER_ROLLBACK_DEGRADED=''
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"RETRIEVAL ROLLBACK DEGRADED"* ]]
}

@test "[render-deployment-page] degraded marker unset renders no banner" {
  unset RENDER_ROLLBACK_DEGRADED
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"RETRIEVAL ROLLBACK DEGRADED"* ]]
}

@test "[render-deployment-page] degraded marker literal 'false' renders no banner" {
  export RENDER_ROLLBACK_DEGRADED='false'
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"RETRIEVAL ROLLBACK DEGRADED"* ]]
}

@test "[render-deployment-page] degraded banner and maintenance banner can coexist, both above Quick access" {
  printf 'version: 9.9.9\nmaintenance: true\n' >"$TEST_DIR/version.yaml"
  export RENDER_VERSION_FILE="$TEST_DIR/version.yaml"
  export RENDER_ROLLBACK_DEGRADED='{"schema_version":1,"release_id":"sha256-abc123"}'
  echo '{ "renate-chatbot-qa": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"MAINTENANCE MODE ACTIVE"* ]]
  [[ "$output" == *"RETRIEVAL ROLLBACK DEGRADED"* ]]
  maint="$(_line_of 'MAINTENANCE MODE ACTIVE')"
  degraded="$(_line_of 'RETRIEVAL ROLLBACK DEGRADED')"
  quick="$(_line_of '## Quick access')"
  [ "$maint" -lt "$quick" ]
  [ "$degraded" -lt "$quick" ]
}

@test "[render-deployment-page] degraded page output is byte-identical across runs" {
  export RENDER_ROLLBACK_DEGRADED='{"schema_version":1,"release_id":"sha256-abc123","opened_at":"2026-07-22T08:00:00Z"}'
  echo '{ "renate-chatbot-qa": { "Zebra": "z", "Alpha": "a" } }' >"$OUTPUTS"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  first="$output"
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [ "$output" = "$first" ]
}

# ── Data + ETL version lines ──────────────────────────────────────────────────

@test "[render-deployment-page] RENDER_DATA_VERSION set → appears in Quick access" {
  export RENDER_DATA_VERSION="v1.92.0"
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Data version: v1.92.0"* ]]
  # Appears after Version line, before API base.
  ver="$(_line_of '- Version:')"
  data="$(_line_of '- Data version:')"
  api="$(_line_of '- API base:')"
  [ "$ver" -lt "$data" ]
  [ "$data" -lt "$api" ]
}

@test "[render-deployment-page] RENDER_ETL_VERSION set → appears in Quick access" {
  export RENDER_ETL_VERSION="v1.92.0"
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- ETL version: v1.92.0"* ]]
  ver="$(_line_of '- Version:')"
  etl="$(_line_of '- ETL version:')"
  api="$(_line_of '- API base:')"
  [ "$ver" -lt "$etl" ]
  [ "$etl" -lt "$api" ]
}

@test "[render-deployment-page] both data and etl versions set → both appear in order" {
  export RENDER_DATA_VERSION="v1.92.0"
  export RENDER_ETL_VERSION="v1.91.0"
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"- Data version: v1.92.0"* ]]
  [[ "$output" == *"- ETL version: v1.91.0"* ]]
  data="$(_line_of '- Data version:')"
  etl="$(_line_of '- ETL version:')"
  [ "$data" -lt "$etl" ]
}

@test "[render-deployment-page] data and etl versions unset → no extra lines" {
  unset RENDER_DATA_VERSION RENDER_ETL_VERSION
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"Data version"* ]]
  [[ "$output" != *"ETL version"* ]]
}

@test "[render-deployment-page] empty data and etl versions → no extra lines" {
  export RENDER_DATA_VERSION=""
  export RENDER_ETL_VERSION=""
  echo '{ "renate-chatbot-dev": { "ApiUrl": "https://x.example.com/prod/" } }' >"$OUTPUTS"
  run bash "$SCRIPT" dev "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"Data version"* ]]
  [[ "$output" != *"ETL version"* ]]
}

@test "[render-deployment-page] no evidence arg → no evidence section (qa byte-identical)" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-qa": { "ApiUrl": "https://x.example/" } }
EOF
  run bash "$SCRIPT" qa "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"Retrieval promotion evidence"* ]]
}

@test "[render-deployment-page] #643 evidence object → renders identity/digests/slots" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-preprod": { "ApiUrl": "https://x.example/" } }
EOF
  export RENDER_EVIDENCE='{"release_id":"sha256-r","retrieval_artifact_id":"art-9","chatbot_image_digest":"sha256:c0","etl_image_digest":"sha256:e0","active_slot_before":"blue","active_slot_after":"green","implementation_fingerprint":"ff11"}'
  run bash "$SCRIPT" preprod "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"## Retrieval promotion evidence"* ]]
  [[ "$output" == *"| Release ID | sha256-r |"* ]]
  [[ "$output" == *"| Chatbot image digest | sha256:c0 |"* ]]
  [[ "$output" == *"| ETL image digest | sha256:e0 |"* ]]
  [[ "$output" == *"| Active slot before | blue |"* ]]
  [[ "$output" == *"| Active slot after (now live) | green |"* ]]
  [[ "$output" == *"| Implementation fingerprint | ff11 |"* ]]
}

@test "[render-deployment-page] #643 malformed evidence → section omitted, still exit 0" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-preprod": { "ApiUrl": "https://x.example/" } }
EOF
  export RENDER_EVIDENCE='this is not json'
  run bash "$SCRIPT" preprod "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" != *"Retrieval promotion evidence"* ]]
}

@test "[render-deployment-page] #643 partial evidence → present fields shown, missing → n/a" {
  cat >"$OUTPUTS" <<'EOF'
{ "renate-chatbot-preprod": { "ApiUrl": "https://x.example/" } }
EOF
  export RENDER_EVIDENCE='{"release_id":"sha256-r"}'
  run bash "$SCRIPT" preprod "$OUTPUTS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"| Release ID | sha256-r |"* ]]
  [[ "$output" == *"| ETL image digest | n/a |"* ]]
}
