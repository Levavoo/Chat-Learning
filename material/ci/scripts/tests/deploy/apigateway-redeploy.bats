#!/usr/bin/env bats

# Tests for .gitlab/ci/scripts/deploy/apigateway-redeploy.sh (#650).
#
# Stubs aws; leaves jq real (installed on all CI runners). The script's
# util/get-stack-outputs.sh runs against the aws stub and writes real JSON
# that the script then parses.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/apigateway-redeploy.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"

  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export CI_COMMIT_SHORT_SHA="abc1234"
  export ROLE_ARN="arn:aws:iam::123456789012:role/ki-lab-digibro-dev-cdk-deploy"
  export AWS_DEFAULT_REGION="eu-central-1"

  cd "$TEST_DIR"

  AWS_LOG="$TEST_DIR/aws.log"
  export AWS_LOG

  write_default_stubs
}

teardown() {
  rm -rf "$TEST_DIR"
}

# aws stub: assume-role returns creds; describe-stacks returns fake outputs
# in raw CFN shape (get-stack-outputs.sh reshapes them); create-deployment
# returns a fake deployment id.
write_default_stubs() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"cloudformation describe-stacks"*)
    # extract env from --stack-name renate-chatbot-<env>
    env=\$(printf '%s' "\$*" | sed -n 's/.*renate-chatbot-\([a-z0-9]*\).*/\1/p')
    printf '%s\n' '[{"OutputKey":"ApiGatewayApiGatewayId8E95341B","OutputValue":"my1nnjaur8"},{"OutputKey":"ApiGatewayApiStageNameA1B2C3D4","OutputValue":"'"\$env"'"},{"OutputKey":"ApiGatewayApiGatewayUrl123ABC","OutputValue":"https://x/'"\$env"'/"}]'
    exit 0 ;;
  *"apigateway create-deployment"*)
    printf 'depl-abc123\n'; exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

# ── Argument validation ──────────────────────────────────────────────────────

@test "[apigateway-redeploy] missing env arg → exits non-zero" {
  run "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"usage:"* ]]
}

@test "[apigateway-redeploy] unknown env → exits non-zero" {
  run "$SCRIPT" staging
  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown env"* ]]
}

@test "[apigateway-redeploy] dev/qa/preprod/prod all accepted" {
  for env in dev qa preprod prod; do
    run "$SCRIPT" "$env"
    [ "$status" -eq 0 ] || { echo "env=$env failed: $output"; return 1; }
  done
}

# ── Required environment ─────────────────────────────────────────────────────

@test "[apigateway-redeploy] missing ROLE_ARN → exits non-zero" {
  unset ROLE_ARN
  run "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"ROLE_ARN is required"* ]]
}

@test "[apigateway-redeploy] missing AWS_DEFAULT_REGION → exits non-zero" {
  unset AWS_DEFAULT_REGION
  run "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"AWS_DEFAULT_REGION is required"* ]]
}

# ── OIDC + role assumption ───────────────────────────────────────────────────

@test "[apigateway-redeploy] assumes ROLE_ARN via OIDC" {
  run "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "assume-role-with-web-identity" "$AWS_LOG"
  grep -q "ki-lab-digibro-dev-cdk-deploy" "$AWS_LOG"
}

# ── Stack lookup ─────────────────────────────────────────────────────────────

@test "[apigateway-redeploy] queries the env's chatbot stack" {
  run "$SCRIPT" preprod
  [ "$status" -eq 0 ]
  grep -q "describe-stacks --stack-name renate-chatbot-preprod" "$AWS_LOG"
}

@test "[apigateway-redeploy] missing ApiGatewayId output → exits non-zero" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '%s\n' '[{"OutputKey":"SomethingElse","OutputValue":"nope"}]'
    exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"Missing ApiGatewayId"* ]]
}

# ── The actual redeploy call ─────────────────────────────────────────────────

@test "[apigateway-redeploy] calls create-deployment with the resolved API id + stage" {
  run "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "apigateway create-deployment --rest-api-id my1nnjaur8 --stage-name dev" "$AWS_LOG"
}

@test "[apigateway-redeploy] stage name comes from ApiStageName stack output (per-env)" {
  run "$SCRIPT" preprod
  [ "$status" -eq 0 ]
  grep -q -- "--stage-name preprod" "$AWS_LOG"
  ! grep -q -- "--stage-name prod " "$AWS_LOG"
}

@test "[apigateway-redeploy] missing ApiStageName output → exits non-zero" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '%s\n' '[{"OutputKey":"ApiGatewayApiGatewayId8E95341B","OutputValue":"my1nnjaur8"}]'
    exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"Missing ApiStageName"* ]]
}

@test "[apigateway-redeploy] includes commit SHA in deployment description" {
  run "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "post-cdk redeploy abc1234" "$AWS_LOG"
}

@test "[apigateway-redeploy] falls back to 'manual' description without CI_COMMIT_SHORT_SHA" {
  unset CI_COMMIT_SHORT_SHA
  run "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "post-cdk redeploy manual" "$AWS_LOG"
}
