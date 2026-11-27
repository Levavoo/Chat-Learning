#!/usr/bin/env bats
# TKT-RO-03: capture is incident-recovery tooling. The suite exercises its
# fail-closed argument and immutable-copy boundaries without live AWS access.
# shellcheck disable=SC2016,SC2314

bats_require_minimum_version 1.5.0

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/capture-blue-baseline.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  FUNCTIONS="$TEST_DIR/functions.sh"
  TEST_SCRIPT="$TEST_DIR/capture-blue-baseline.sh"
  sed 's/\r$//' "$SCRIPT" >"$TEST_SCRIPT"
}

teardown() { rm -rf "$TEST_DIR"; }

extract() {
  awk -v fn="$1" '
    $0 ~ "^" fn "\\(\\) \\{" { capture=1 }
    capture && seen && $0 ~ "^[[:alnum:]_]+\\(\\) \\{" { exit }
    capture { print; seen=1 }
  ' "$TEST_SCRIPT"
}

@test "[capture-blue-baseline] rejects an unknown environment before AWS" {
  run bash "$TEST_SCRIPT" --env bogus
  [ "$status" -eq 2 ]
  [[ "$output" == *"--env must be qa or preprod"* ]]
}

@test "[capture-blue-baseline] resolves moved node helpers under lib/node" {
  grep -Fq 'lib/node/retrieval-release.mjs' "$SCRIPT"
  grep -Fq 'lib/node/retrieval-environment.mjs' "$SCRIPT"
  grep -Fq 'lib/node/release-retention.mjs' "$SCRIPT"
}

@test "[capture-blue-baseline] write-once upload verifies existing bytes and skips put" {
  {
    extract sha256_base64
    printf '\n'
    extract put_write_once
  } >"$FUNCTIONS"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${AWS_CALLS:?}"
case "$*" in
  *'--query ChecksumSHA256'*) openssl dgst -sha256 -binary "$TEST_FILE" | openssl base64 -A ;;
  *'put-object'*) echo 'unexpected upload' >&2; exit 1 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  printf 'immutable payload' >"$TEST_DIR/payload"
  export AWS_CALLS="$TEST_DIR/aws-calls" TEST_FILE="$TEST_DIR/payload" EXECUTE=true
  run bash -c 'source "$1"; put_write_once bucket key "$2"' _ "$FUNCTIONS" "$TEST_DIR/payload"
  [ "$status" -eq 0 ]
  run ! grep -q 'put-object' "$TEST_DIR/aws-calls"
}

@test "[capture-blue-baseline] cleanup keeps disabled mappings closed after dirty copy" {
  grep -Fq '[ "$RAW_COPY_STARTED" = true ] && [ "$COPY_EVENT_QUEUES_CLEAN" != true ]' "$SCRIPT"
  grep -Fq 'Purge/drain the listed queues before re-enabling' "$SCRIPT"
  grep -Fq 'restore_pipeline' "$SCRIPT"
}