#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/build/etl-changed.sh
# Dual fingerprint gate (#626): ETL_IMAGE_CHANGED / ETL_STACK_CHANGED, each
# compared independently against a composite JSON value
# ({"image":"<sha>","stack":"<sha>"}) stored in the single existing
# /dev/renate/etl-code-fingerprint parameter (#626 Decision D1 = Option B).
# Hash match per signal -> that signal unchanged; hash differs / missing /
# unparseable -> that signal changed (fail-open, independently per signal).
# Regression guard: an in-place edit of an EXISTING file (same file set) must
# change the relevant fingerprint -- guards against a paths-only hash regression.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/build/etl-changed.sh"

_write_release_files() {
  local backend_version="$1"
  local dependency_version="${2:-1.0.0}"

  printf '%s\n' \
    '[project]' \
    'name = "digibro-backend"' \
    "version = \"${backend_version}\"" \
    "dependencies = [\"example-dependency==${dependency_version}\"]" \
    >"$TEST_DIR/backend/pyproject.toml"

  printf '%s\n' \
    'version = 1' \
    '' \
    '[[package]]' \
    'name = "example-dependency"' \
    "version = \"${dependency_version}\"" \
    '' \
    '[[package]]' \
    'name = "digibro-backend"' \
    "version = \"${backend_version}\"" \
    'source = { editable = "backend" }' \
    'dependencies = [' \
    '    { name = "example-dependency" },' \
    ']' \
    >"$TEST_DIR/uv.lock"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  mkdir -p "$TEST_DIR/backend/src/etl"
  mkdir -p "$TEST_DIR/backend/src/bm25_shared"
  mkdir -p "$TEST_DIR/cdk/lib/constructs/knowledge-base"
  mkdir -p "$TEST_DIR/cdk/lib/custom-resources/source-reprocess"
  mkdir -p "$TEST_DIR/cdk/lib/config/kb"

  echo "def handler(): pass" >"$TEST_DIR/backend/src/etl/transform.py"
  echo "TOKENIZER = 1" >"$TEST_DIR/backend/src/bm25_shared/tokenizer.py"
  echo "export const x = 1;" >"$TEST_DIR/cdk/lib/etl-kb-stack.ts"
  echo "export const y = 1;" >"$TEST_DIR/cdk/lib/constructs/knowledge-base/transform-pipeline.ts"
  echo '{"name":"cdk"}' >"$TEST_DIR/cdk/package.json"
  echo "[project]" >"$TEST_DIR/pyproject.toml"
  _write_release_files "1.101.1"

  export PATH="$TEST_DIR/bin:$PATH"
  export AWS_DEFAULT_REGION="eu-central-1"
  export AWS_ACCESS_KEY_ID="FAKEID"
  export AWS_SECRET_ACCESS_KEY="FAKESECRET"
  export AWS_SESSION_TOKEN="FAKETOKEN"

  cd "$TEST_DIR" || exit
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Compute the same fingerprints the script would compute (used to seed a stub).
_current_image_fingerprint() {
  bash "$SCRIPT" 2>/dev/null | grep '^ETL_IMAGE_FINGERPRINT=' | cut -d= -f2
}

_current_stack_fingerprint() {
  bash "$SCRIPT" 2>/dev/null | grep '^ETL_STACK_FINGERPRINT=' | cut -d= -f2
}

# aws stub. $1 = stored parameter value returned by ssm get-parameter.
# "MISSING" simulates ParameterNotFound / no output. Pass a raw string (e.g.
# a legacy bare sha) to test fail-open on unparseable JSON, or a JSON string
# (e.g. from _composite_json) to test the composite-value path.
#
# The stored value is written to a fixture file rather than interpolated
# directly into the heredoc below — a composite JSON value contains literal
# double-quotes, which would otherwise prematurely close the heredoc's own
# quoted strings and corrupt the generated stub script.
_aws_stub() {
  local stored="${1:-}"
  if [ "$stored" = "MISSING" ]; then
    rm -f "$TEST_DIR/stored_value"
  else
    printf '%s' "$stored" >"$TEST_DIR/stored_value"
  fi
  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"
if [[ "\$CMD" == *"get-parameter"* ]]; then
  cat "$TEST_DIR/stored_value" 2>/dev/null || exit 1
  exit 0
fi
exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

_composite_json() {
  jq -n --arg image "$1" --arg stack "$2" '{image: $image, stack: $stack}'
}

# ---------------------------------------------------------------------------

@test "[etl-changed] missing stored fingerprint -> fail-open, both signals changed" {
  _aws_stub "MISSING"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
  [[ "$output" == *"ETL_IMAGE_FINGERPRINT="* ]]
  [[ "$output" == *"ETL_STACK_FINGERPRINT="* ]]
}

@test "[etl-changed] empty stored fingerprint -> both signals changed" {
  _aws_stub ""
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
}

@test "[etl-changed] legacy bare-sha stored value (pre-#626 format) -> fail-open, both signals changed" {
  # Simulates the value shape written before #626 shipped (a plain sha256,
  # not JSON). jq -e on it must yield empty, not a hard failure.
  _aws_stub "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcd"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
}

@test "[etl-changed] unparseable/corrupt JSON stored value -> fail-open, both signals changed" {
  _aws_stub '{"image": "abc", "stack": '
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
}

@test "[etl-changed] matching composite fingerprint -> both signals unchanged" {
  _aws_stub "MISSING"
  IMAGE_FP=$(_current_image_fingerprint)
  STACK_FP=$(_current_stack_fingerprint)
  [ -n "$IMAGE_FP" ]
  [ -n "$STACK_FP" ]

  _aws_stub "$(_composite_json "$IMAGE_FP" "$STACK_FP")"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=false"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=false"* ]]
}

@test "[etl-changed] stack-only change: image signal unchanged, stack signal changed" {
  # Reproduces the MR !898 / Pipeline #3093 scenario: only a CDK construct
  # file changes -- the image fingerprint must NOT flip.
  _aws_stub "MISSING"
  IMAGE_FP=$(_current_image_fingerprint)
  STACK_FP=$(_current_stack_fingerprint)

  _aws_stub "$(_composite_json "$IMAGE_FP" "$STACK_FP")"
  echo "export const y = 2;" >"$TEST_DIR/cdk/lib/constructs/knowledge-base/transform-pipeline.ts"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=false"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
}

@test "[etl-changed] image-only change: stack signal unchanged, image signal changed" {
  _aws_stub "MISSING"
  IMAGE_FP=$(_current_image_fingerprint)
  STACK_FP=$(_current_stack_fingerprint)

  _aws_stub "$(_composite_json "$IMAGE_FP" "$STACK_FP")"
  echo "def handler(): return 1" >"$TEST_DIR/backend/src/etl/transform.py"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=false"* ]]
}

@test "[etl-changed] combined change: both signals changed" {
  _aws_stub "MISSING"
  IMAGE_FP=$(_current_image_fingerprint)
  STACK_FP=$(_current_stack_fingerprint)

  _aws_stub "$(_composite_json "$IMAGE_FP" "$STACK_FP")"
  echo "def handler(): return 1" >"$TEST_DIR/backend/src/etl/transform.py"
  echo "export const y = 2;" >"$TEST_DIR/cdk/lib/constructs/knowledge-base/transform-pipeline.ts"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=true"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=true"* ]]
}

@test "[etl-changed] unrelated file (outside ETL path lists) does not change either signal" {
  _aws_stub "MISSING"
  IMAGE_FP=$(_current_image_fingerprint)
  STACK_FP=$(_current_stack_fingerprint)

  _aws_stub "$(_composite_json "$IMAGE_FP" "$STACK_FP")"
  mkdir -p "$TEST_DIR/drv-frontend/src"
  echo "console.log('hi')" >"$TEST_DIR/drv-frontend/src/app.ts"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL_IMAGE_CHANGED=false"* ]]
  [[ "$output" == *"ETL_STACK_CHANGED=false"* ]]
}

@test "[etl-changed] in-place edit of an EXISTING image-set file changes the image fingerprint only" {
  # Regression guard: hashing only the sorted path LIST (not contents) would
  # keep the fingerprint stable across an in-place edit -- this must not happen.
  _aws_stub "MISSING"
  IMAGE_FP_BEFORE=$(_current_image_fingerprint)
  STACK_FP_BEFORE=$(_current_stack_fingerprint)

  echo "def handler(): return 42" >"$TEST_DIR/backend/src/etl/transform.py"

  _aws_stub "MISSING"
  IMAGE_FP_AFTER=$(_current_image_fingerprint)
  STACK_FP_AFTER=$(_current_stack_fingerprint)

  [ "$IMAGE_FP_BEFORE" != "$IMAGE_FP_AFTER" ]
  [ "$STACK_FP_BEFORE" = "$STACK_FP_AFTER" ]
}

@test "[etl-changed] in-place edit of an EXISTING stack-set file changes the stack fingerprint only" {
  _aws_stub "MISSING"
  IMAGE_FP_BEFORE=$(_current_image_fingerprint)
  STACK_FP_BEFORE=$(_current_stack_fingerprint)

  echo "export const x = 2;" >"$TEST_DIR/cdk/lib/etl-kb-stack.ts"

  _aws_stub "MISSING"
  IMAGE_FP_AFTER=$(_current_image_fingerprint)
  STACK_FP_AFTER=$(_current_stack_fingerprint)

  [ "$IMAGE_FP_BEFORE" = "$IMAGE_FP_AFTER" ]
  [ "$STACK_FP_BEFORE" != "$STACK_FP_AFTER" ]
}

@test "[etl-changed] release-only backend version bump does not change the image fingerprint" {
  _aws_stub "MISSING"
  IMAGE_FP_BEFORE=$(_current_image_fingerprint)

  _write_release_files "1.101.2"

  _aws_stub "MISSING"
  IMAGE_FP_AFTER=$(_current_image_fingerprint)

  [ "$IMAGE_FP_BEFORE" = "$IMAGE_FP_AFTER" ]
}

@test "[etl-changed] resolved dependency version change is covered by the image fingerprint" {
  _aws_stub "MISSING"
  IMAGE_FP_BEFORE=$(_current_image_fingerprint)

  _write_release_files "1.101.1" "2.0.0"

  _aws_stub "MISSING"
  IMAGE_FP_AFTER=$(_current_image_fingerprint)

  [ "$IMAGE_FP_BEFORE" != "$IMAGE_FP_AFTER" ]
}

@test "[etl-changed] backend dependency declaration change is covered by the image fingerprint" {
  _aws_stub "MISSING"
  IMAGE_FP_BEFORE=$(_current_image_fingerprint)

  printf '%s\n' 'requires-python = ">=3.14"' >>"$TEST_DIR/backend/pyproject.toml"

  _aws_stub "MISSING"
  IMAGE_FP_AFTER=$(_current_image_fingerprint)

  [ "$IMAGE_FP_BEFORE" != "$IMAGE_FP_AFTER" ]
}

@test "[etl-changed] dotenv shape: exactly the four expected keys on stdout" {
  _aws_stub "MISSING"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Diagnostics go to stderr; bats merges stderr into $output by default, so
  # assert the dotenv keys are present rather than asserting exact line count.
  [[ "$output" == *"ETL_IMAGE_CHANGED="* ]]
  [[ "$output" == *"ETL_STACK_CHANGED="* ]]
  [[ "$output" == *"ETL_IMAGE_FINGERPRINT="* ]]
  [[ "$output" == *"ETL_STACK_FINGERPRINT="* ]]
}
