#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/teardown/review-check-cleanup.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments/review"
  export PATH="$TEST_DIR/bin:$PATH"

  export CI_COMMIT_REF_SLUG="feature-my-branch"
  # No ROLE_ARN set by default → AWS section skipped in git-only tests.

  cd "$TEST_DIR"

  # Default git stub: no tracked *.yml files.
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [ "$1" = "ls-files" ]; then
  # Return nothing by default (no active trigger file).
  exit 0
fi
exec /usr/bin/git "$@"
EOF
  chmod +x "$TEST_DIR/bin/git"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ---------------------------------------------------------------------------
# AC (a): branch has a tracked deployments/review/*.yml → FAILS
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] trigger file present → exit 1 with message" {
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [ "$1" = "ls-files" ]; then
  printf 'deployments/review/my-branch.yml\n'
  exit 0
fi
exec /usr/bin/git "$@"
EOF
  chmod +x "$TEST_DIR/bin/git"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"my-branch.yml"* ]]
}

# ---------------------------------------------------------------------------
# AC (b): no *.yml in deployments/review/ → PASSES
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] no trigger file → exit 0" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# AC (c): TEMPLATE present (no .yml suffix) → PASSES
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] TEMPLATE file only (no .yml) → exit 0" {
  # git stub still returns empty for *.yml glob — TEMPLATE not matched.
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# AWS check: no leftover resources → PASSES
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] AWS check: no resources → exit 0" {
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export AWS_DEFAULT_REGION="eu-central-1"

  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
case "$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKID\tSECRET\tTOKEN\n' ;;
  *"get-function"*)
    exit 1 ;;  # Lambda not found
  *"apigatewayv2 get-apis"*)
    printf 'None\n' ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameXYZ","OutputValue":"test-bucket"}]}]}\n' ;;
  *"s3api list-objects-v2"*)
    printf '0\n' ;;
  *"ecr describe-images"*)
    printf 'None\n' ;;
  *"cognito-idp admin-get-user"*)
    exit 1 ;;  # test user not found
  *)
    printf 'None\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
cat | grep -o '"OutputValue":"[^"]*"' | head -1 | sed 's/"OutputValue":"//;s/"//' || true
EOF
  chmod +x "$TEST_DIR/bin/jq"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"AWS check passed"* ]]
}

# ---------------------------------------------------------------------------
# AWS check: lingering Lambda found → FAILS
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] AWS check: Lambda exists → exit 1" {
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export AWS_DEFAULT_REGION="eu-central-1"

  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
case "$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKID\tSECRET\tTOKEN\n' ;;
  *"get-function"*)
    exit 0 ;;  # Lambda EXISTS
  *"apigatewayv2 get-apis"*)
    printf 'None\n' ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[]}]}\n' ;;
  *"s3api list-objects-v2"*)
    printf '0\n' ;;
  *"ecr describe-images"*)
    printf 'None\n' ;;
  *)
    printf 'None\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
cat | grep -o '"OutputValue":"[^"]*"' | head -1 | sed 's/"OutputValue":"//;s/"//' || true
EOF
  chmod +x "$TEST_DIR/bin/jq"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"LEFTOVER"* ]]
  [[ "$output" == *"Lambda"* ]]
}

# ---------------------------------------------------------------------------
# AWS check: lingering ECR image found → FAILS
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] AWS check: ECR image exists → exit 1" {
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export AWS_DEFAULT_REGION="eu-central-1"

  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
case "$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKID\tSECRET\tTOKEN\n' ;;
  *"get-function"*)
    exit 1 ;;  # Lambda gone
  *"apigatewayv2 get-apis"*)
    printf 'None\n' ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[]}]}\n' ;;
  *"s3api list-objects-v2"*)
    printf '0\n' ;;
  *"ecr list-images"*)
    printf 'review-feature-my-branch-deadbee\n' ;;  # leftover review image
  *)
    printf 'None\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
cat | grep -o '"OutputValue":"[^"]*"' | head -1 | sed 's/"OutputValue":"//;s/"//' || true
EOF
  chmod +x "$TEST_DIR/bin/jq"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"LEFTOVER"* ]]
  [[ "$output" == *"ECR"* ]]
}

# ---------------------------------------------------------------------------
# AWS check: lingering Cognito test user found → FAILS
# ---------------------------------------------------------------------------
@test "[review-check-cleanup] AWS check: test user exists → exit 1" {
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export AWS_DEFAULT_REGION="eu-central-1"

  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
case "$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKID\tSECRET\tTOKEN\n' ;;
  *"get-function"*)
    exit 1 ;;  # Lambda gone
  *"apigatewayv2 get-apis"*)
    printf 'None\n' ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n' ;;
  *"s3api list-objects-v2"*)
    printf '0\n' ;;
  *"ecr describe-images"*)
    printf 'None\n' ;;
  *"cognito-idp admin-get-user"*)
    exit 0 ;;  # test user STILL EXISTS
  *)
    printf 'None\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
cat | grep -o '"OutputValue":"[^"]*"' | head -1 | sed 's/"OutputValue":"//;s/"//' || true
EOF
  chmod +x "$TEST_DIR/bin/jq"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"LEFTOVER"* ]]
  [[ "$output" == *"test user"* ]]
}
