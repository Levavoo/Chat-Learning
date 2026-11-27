#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/deploy/deploy-etl-dev.sh

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-etl-dev.sh"
REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../.." && pwd)"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk"
  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::831926590742:role/ki-lab-digibro-dev-cdk-deploy"

  _aws_stub "AKID SECRET TOKEN"
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$REPO_ROOT/outputs-etl.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
}

teardown() {
  rm -rf "$TEST_DIR"
  rm -f "$REPO_ROOT/outputs-etl.json"
}

_aws_stub() {
  local sts_output="$1"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role"* ]]; then printf '%s\n' "$sts_output"; exit 0; fi
if [[ "\$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "\$*" == *"cloudformation describe-stacks"* ]]; then
  printf '[]\n'; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[deploy-etl-dev] role var unset → exit 1 with var name in message" {
  unset CDK_DEPLOY_ROLE_ARN_DEV
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CDK_DEPLOY_ROLE_ARN_DEV"* ]]
}

@test "[deploy-etl-dev] deploys renate-etl-kb-dev with env=dev" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "renate-etl-kb-dev" "$TEST_DIR/npx_args"
  grep -q "env=dev" "$TEST_DIR/npx_args"
}

@test "[deploy-etl-dev] no ETL_IMAGE_TAG_OVERRIDE → no etlImageTag context passed" {
  unset ETL_IMAGE_TAG_OVERRIDE
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  ! grep -q "etlImageTag" "$TEST_DIR/npx_args"
}

@test "[deploy-etl-dev] ETL_IMAGE_TAG_OVERRIDE set → passes --context etlImageTag=<value> (manual rollback)" {
  export ETL_IMAGE_TAG_OVERRIDE="v1.23.0"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q -- "--context etlImageTag=v1.23.0" "$TEST_DIR/npx_args"
}

@test "[deploy-etl-dev] STS failure → exit 1" {
  _aws_stub ""
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}
