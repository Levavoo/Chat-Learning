#!/usr/bin/env bats
# TKT-RO-03: preflight must prove account/identity and policy boundaries while
# remaining read-only. These helper-level tests mock AWS at the command edge.
# shellcheck disable=SC2030,SC2031,SC2314

bats_require_minimum_version 1.5.0

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/.gitlab/ci/scripts/deploy/preflight-preprod-retrieval-foundation.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  TEST_SCRIPT="$TEST_DIR/preflight-preprod-retrieval-foundation.sh"
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

append_function() {
  extract "$1"
  printf '\n'
}

@test "[preflight-foundation] local identity selects the configured profile" {
  append_function fail >"$TEST_DIR/functions.sh"
  append_function record >>"$TEST_DIR/functions.sh"
  append_function select_identity >>"$TEST_DIR/functions.sh"
  export LOCAL_MODE=true PREPROD_PROFILE=mock-preprod EVIDENCE="$TEST_DIR/evidence"
  : >"$EVIDENCE"
  run bash -c 'source "$1"; select_identity role suffix mock-preprod; printf "%s" "$AWS_PROFILE"' _ "$TEST_DIR/functions.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"mock-preprod"* ]]
}

@test "[preflight-foundation] OIDC credentials are exported from mocked STS output" {
  append_function fail >"$TEST_DIR/functions.sh"
  append_function assume_oidc >>"$TEST_DIR/functions.sh"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf 'AKIA-MOCK SECRET-MOCK TOKEN-MOCK\n'
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export GITLAB_OIDC_TOKEN=oidc JOB_ID=123
  run bash -c 'source "$1"; assume_oidc arn:role test; printf "%s|%s|%s" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$AWS_SESSION_TOKEN"' _ "$TEST_DIR/functions.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"AKIA-MOCK|SECRET-MOCK|TOKEN-MOCK"* ]]
}

@test "[preflight-foundation] promotion AWS uses the preprod profile in local mode" {
  append_function promotion_aws >"$TEST_DIR/functions.sh"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s|%s\n' "${AWS_PROFILE:-unset}" "$*"
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export LOCAL_MODE=true PREPROD_PROFILE=mock-preprod
  run bash -c 'source "$1"; promotion_aws ssm get-parameter --name x' _ "$TEST_DIR/functions.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == "mock-preprod|ssm get-parameter --name x"* ]]
}

@test "[preflight-foundation] source is read-only at the script boundary" {
  run ! grep -Eq '^[[:space:]]*aws (ssm put-parameter|cloudformation create-change-set|bedrock-agent start-ingestion-job)' "$SCRIPT"
  grep -Fq 'FOUNDATION_LOCAL_MODE' "$SCRIPT"
}