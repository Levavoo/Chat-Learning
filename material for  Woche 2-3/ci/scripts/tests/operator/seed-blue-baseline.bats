#!/usr/bin/env bats
# TKT-RO-03: the prod seed is an operator-only mutation path. These tests keep
# its input gate, profile separation, and selector safety testable without AWS.
# shellcheck disable=SC2034,SC2314

bats_require_minimum_version 1.5.0

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/seed-blue-baseline.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  TEST_SCRIPT="$TEST_DIR/seed-blue-baseline.sh"
  sed 's/\r$//' "$SCRIPT" >"$TEST_SCRIPT"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "[seed-blue-baseline] rejects non-prod input before checking tools or AWS" {
  run bash "$TEST_SCRIPT" --env preprod --pin-file "$REPO_ROOT/deployments/prod/version.yaml"
  [ "$status" -eq 2 ]
  [[ "$output" == *"seeds only --env prod"* ]]
}

@test "[seed-blue-baseline] requires an explicit pin file" {
  run bash "$TEST_SCRIPT" --env prod
  [ "$status" -eq 2 ]
  [[ "$output" == *"--pin-file is required"* ]]
}

@test "[seed-blue-baseline] routes QA reads and prod writes to separate profiles" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s|%s\n' "${AWS_PROFILE:-unset}" "$*" >>"${AWS_CALLS:?}"
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export AWS_CALLS="$TEST_DIR/aws-calls"
  export QA_PROFILE=digibro-eu-qa PROD_PROFILE=renate-prod REGION=eu-central-1
  grep -E '^(qa_aws|prod_aws)\(\)' "$TEST_SCRIPT" >"$TEST_DIR/functions.sh"
  # This is the same dispatch boundary used by every S3/SSM operation in the
  # script: an accidental profile swap can read or mutate the wrong account.
  run bash -c "source '$TEST_DIR/functions.sh'; qa_aws s3api head-object --bucket qa --key x; prod_aws s3api put-object --bucket prod --key x --body y"
  [ "$status" -eq 0 ]
  grep -Fq -- '--profile digibro-eu-qa --region eu-central-1 s3api head-object' "$TEST_DIR/aws-calls"
  grep -Fq -- '--profile renate-prod --region eu-central-1 s3api put-object' "$TEST_DIR/aws-calls"
}

@test "[seed-blue-baseline] never writes selectors itself" {
  # Selector creation is a separate explicit activation step; this prevents a
  # partial seed from making an incomplete baseline live.
  run ! grep -Fq 'ssm put-parameter' "$SCRIPT"
  grep -Fq 'selectors remain absent' "$SCRIPT"
}