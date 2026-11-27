#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-dev.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk" \
    "$TEST_DIR/deployments/dev"

  export PATH="$TEST_DIR/bin:$PATH"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::123456789012:role/test-role"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="99"
  export REPO_ROOT="$TEST_DIR"

  printf 'version: 1.28.5\ndata_artifact_version: v1.0.0\netl_version: v1.28.0' \
    >"$TEST_DIR/deployments/dev/version.yaml"

  # Default npx stub — succeeds silently
  cat >"$TEST_DIR/bin/npx" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_aws_stub() {
  local sts_output="$1"
  # Mock AWS CLI to support deploy-dev.sh operations:
  # - assume-role-with-web-identity: return credentials for testing
  # - get-caller-identity: verify role assumption succeeded
  # - cloudformation describe-stacks: provide outputs when CDK fallback is triggered
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role-with-web-identity"* ]]; then
  printf '%s\n' "$sts_output"
  exit 0
fi
if [[ "\$*" == *"get-caller-identity"* ]]; then
  touch "$TEST_DIR/identity_called"
  exit 0
fi
if [[ "\$*" == *"cloudformation describe-stacks"* ]]; then
  # Return CloudFormation outputs in the format expected by get-stack-outputs.sh
  # when CDK deploy --outputs-file fails or is unavailable during testing
  printf '[{"OutputKey":"TestOutput","OutputValue":"TestValue"}]\n'
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[deploy-dev] empty STS output → exit 1 with error message" {
  _aws_stub ""
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[deploy-dev] partial STS (missing session token) → exit 1" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[deploy-dev] aws CLI failure → exit 1 with error message" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then
  echo "An error occurred (AccessDenied)" >&2; exit 255
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[deploy-dev] valid STS output → calls get-caller-identity then cdk deploy" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w"
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
  run bash -c "cd '$TEST_DIR' && REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/identity_called" ]
  grep -q "renate-chatbot-dev" "$TEST_DIR/npx_args"
  grep -q "env=dev" "$TEST_DIR/npx_args"
  grep -q -- "--require-approval never" "$TEST_DIR/npx_args"
  grep -qF -- "--outputs-file $TEST_DIR/outputs.json" "$TEST_DIR/npx_args"
}
