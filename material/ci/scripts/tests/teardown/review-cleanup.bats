#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/teardown/review-cleanup.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"

  export CI_COMMIT_REF_SLUG="feature-my-branch"
  export CI_COMMIT_SHORT_SHA="abc1234"
  export REVIEW_ASSETS_BUCKET="renate-assets-review-dev-eu-central-1"
  export REVIEW_CF_DISTRIBUTION_ID="EH5CFH3DYCCUQ"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export AWS_DEFAULT_REGION="eu-central-1"

  cd "$TEST_DIR"

  AWS_LOG="$TEST_DIR/aws.log"
  export AWS_LOG

  # jq stub: handle the calls made by review-cleanup.sh
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
filter=""
skip_next=0
for arg in "$@"; do
  if [ "$skip_next" -gt 0 ]; then skip_next=$((skip_next - 1)); continue; fi
  case "$arg" in -r|-c) ;; --arg) skip_next=2 ;; *) [ -z "$filter" ] && filter="$arg" ;; esac
done
# Extract --arg key value for startswith-based dispatch
arg_key=""
arg_val=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--arg" ]; then arg_key="$arg"; fi
  if [ -n "$arg_key" ] && [ "$prev" = "$arg_key" ]; then arg_val="$arg"; break; fi
  prev="$arg"
done
input=$(cat)
case "$arg_val" in
  AuthUserPoolId)               printf 'eu-central-1_TestPool\n'; exit 0 ;;
  FrontendFrontendS3BucketName) printf 'renate-assets-dev-eu-central-1\n'; exit 0 ;;
esac

case "$filter" in
  *FrontendFrontendS3BucketName*)
    printf 'renate-assets-dev-eu-central-1\n' ;;
  *AuthUserPoolId*)
    printf 'eu-central-1_TestPool\n' ;;
  *'.Items[]'*|*'Items[]'*)
    # Only emit items if input has actual Items content (not empty array)
    if printf '%s' "$input" | grep -q '"Items":\[\]'; then
      : # empty — emit nothing
    else
      printf '{"session_id":{"S":"review/feature-my-branch#sess1"},"message_id":{"S":"msg1"}}\n'
      printf '{"session_id":{"S":"review/feature-my-branch#sess2"},"message_id":{"S":"msg2"}}\n'
    fi ;;
  *'.session_id.S'*)
    printf '%s\n' "$input" | grep -o '"S":"[^"]*"' | head -1 | sed 's/"S":"//;s/"//' ;;
  *'.message_id.S'*)
    printf '%s\n' "$input" | grep -o '"S":"[^"]*"' | tail -1 | sed 's/"S":"//;s/"//' ;;
  *)
    printf '%s\n' "$input" ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/jq"

  write_default_aws_stub
}

# Default stub: all resources absent / already deleted; Cognito user absent.
write_default_aws_stub() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*"DYNAMODB_TABLE_NAME"*)
    printf 'renate-conversations-dev\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_HOST"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_SECRET_NAME"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_REVIEW_TAG"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*)
    printf 'abc1234\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;  # 404 — already deleted / verify passes
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr list-images"*)
    printf 'review-feature-my-branch-abc1234\n'; exit 0 ;;
  *"ecr batch-delete-image"*) exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;  # image gone
  *"dynamodb scan"*"COUNT"*)
    printf '0\n'; exit 0 ;;
  *"dynamodb scan"*)
    printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"dynamodb delete-item"*) exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;   # user already gone (idempotent)
  *"cognito-idp admin-delete-user"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Required-var guards ───────────────────────────────────────────────────────

@test "[review-cleanup] missing CI_COMMIT_REF_SLUG → exit non-zero" {
  unset CI_COMMIT_REF_SLUG
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing CI_COMMIT_SHORT_SHA → exit non-zero" {
  unset CI_COMMIT_SHORT_SHA
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing GITLAB_OIDC_TOKEN → exit non-zero" {
  unset GITLAB_OIDC_TOKEN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing ROLE_ARN → exit non-zero" {
  unset ROLE_ARN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing CI_JOB_ID → exit non-zero" {
  unset CI_JOB_ID
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing AWS_DEFAULT_REGION → exit non-zero" {
  unset AWS_DEFAULT_REGION
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing REVIEW_ASSETS_BUCKET → exit non-zero" {
  unset REVIEW_ASSETS_BUCKET
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-cleanup] missing REVIEW_CF_DISTRIBUTION_ID → exit non-zero" {
  unset REVIEW_CF_DISTRIBUTION_ID
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

# ── Derived names ─────────────────────────────────────────────────────────────

@test "[review-cleanup] derives renate-chat-review-feature-my-branch" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Review function:  renate-chat-review-feature-my-branch"* ]]
  [[ "$output" == *"Review API name:  review-feature-my-branch"* ]]
}

@test "[review-cleanup] long slug (80 chars) → FUNC name ≤ 64 chars" {
  export CI_COMMIT_REF_SLUG="$(printf 'x%.0s' {1..80})"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  func_line=$(printf '%s\n' "$output" | grep 'Review function:')
  func_name="${func_line#*Review function:  }"
  [ "${#func_name}" -le 64 ]
}

# ── OIDC / STS ────────────────────────────────────────────────────────────────

@test "[review-cleanup] empty STS output → exit 1 with error message" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then printf ''; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[review-cleanup] STS CLI failure → exit non-zero" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then
  printf 'AccessDenied\n' >&2; exit 255
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

# ── APIGW deletion ────────────────────────────────────────────────────────────

@test "[review-cleanup] API absent → no delete-api, exit 0" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "apigatewayv2 delete-api" "$AWS_LOG"
  [[ "$output" == *"not found — already deleted"* ]]
}

# ── Lambda deletion ───────────────────────────────────────────────────────────

@test "[review-cleanup] Lambda 404 → no delete-function, exit 0" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "lambda delete-function" "$AWS_LOG"
  [[ "$output" == *"already deleted (idempotent)"* ]]
}

# ── S3 deletion ───────────────────────────────────────────────────────────────

@test "[review-cleanup] s3 rm called with correct prefix" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "s3 rm s3://renate-assets-review-dev-eu-central-1/feature-my-branch/ --recursive" "$AWS_LOG"
}

# ── CloudFront invalidation ───────────────────────────────────────────────────

@test "[review-cleanup] cloudfront create-invalidation called with correct distribution + path" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "cloudfront create-invalidation --distribution-id EH5CFH3DYCCUQ --paths /feature-my-branch/\*" "$AWS_LOG"
}

@test "[review-cleanup] cloudfront invalidation failure → logs WARNING, continues teardown" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*"DYNAMODB_TABLE_NAME"*) printf 'renate-conversations-dev\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_HOST"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_SECRET_NAME"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_REVIEW_TAG"*) printf 'None\n'; exit 0 ;;
  *"get-function-configuration"*) printf 'abc1234\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"cloudfront create-invalidation"*) printf 'AccessDenied\n' >&2; exit 1 ;;
  *"ecr list-images"*) printf '\n'; exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING: CloudFront invalidation failed"* ]]
  [[ "$output" == *"All resources verified deleted"* ]]
}

# ── ECR deletion ─────────────────────────────────────────────────────────────

@test "[review-cleanup] ECR lists and batch-deletes all images for the branch prefix" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "ecr list-images" "$AWS_LOG"
  grep -q "review-feature-my-branch-" "$AWS_LOG"
  grep -q "ecr batch-delete-image" "$AWS_LOG"
}

@test "[review-cleanup] ECR does NOT delete sibling-branch images (anchored match)" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*)
    printf 'renate-conversations-dev\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"lambda delete-function"*) exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr list-images"*)
    # own image + a sibling branch whose slug extends this one
    printf 'review-feature-my-branch-abc1234\treview-feature-my-branch-extra-def5678\n'; exit 0 ;;
  *"ecr batch-delete-image"*) exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # The own image is deleted; the sibling (review-feature-my-branch-extra-*) is NOT.
  delete_line=$(grep "ecr batch-delete-image" "$AWS_LOG")
  [[ "$delete_line" == *"imageTag=review-feature-my-branch-abc1234"* ]]
  [[ "$delete_line" != *"extra-def5678"* ]]
}

@test "[review-cleanup] ECR no matching images → skips batch-delete, exit 0" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*)
    printf 'renate-conversations-dev\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"lambda delete-function"*) exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr list-images"*) printf '\n'; exit 0 ;;   # no images
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "ecr batch-delete-image" "$AWS_LOG"
  [[ "$output" == *"already deleted (idempotent)"* ]]
}

# ── DynamoDB deletion ─────────────────────────────────────────────────────────

@test "[review-cleanup] empty DynamoDB scan → no delete-item, exit 0" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "dynamodb delete-item" "$AWS_LOG"
}

@test "[review-cleanup] DynamoDB targets table from Lambda env" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "dynamodb scan --table-name renate-conversations-dev" "$AWS_LOG"
  [[ "$output" == *"DynamoDB table:   renate-conversations-dev"* ]]
}

# ── Cognito test user deletion ────────────────────────────────────────────────

@test "[review-cleanup] test user absent → skips deletion, exit 0" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "cognito-idp admin-delete-user" "$AWS_LOG"
  [[ "$output" == *"already deleted (idempotent)"* ]]
}

@test "[review-cleanup] test user present → deletes it" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*) printf 'abc1234\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr batch-delete-image"*) exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*)
    # First call: user exists (triggers deletion). Second call (verify): user gone.
    count=\$(grep -c "cognito-idp admin-get-user" "$AWS_LOG" 2>/dev/null || echo 0)
    [ "\$count" -le 1 ] && exit 0 || exit 1 ;;
  *"cognito-idp admin-delete-user"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "cognito-idp admin-delete-user" "$AWS_LOG"
}

# ── Verification ──────────────────────────────────────────────────────────────

@test "[review-cleanup] all gone → exit 0 and verified message" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All resources verified deleted"* ]]
}

@test "[review-cleanup] paginated DynamoDB COUNT (multi-page zeros) → exit 0" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*) printf 'sha123\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr batch-delete-image"*) exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n0\n0\n0\n0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All resources verified deleted"* ]]
  [[ "$output" != *"VERIFY FAIL"* ]]
}

@test "[review-cleanup] Lambda still present at verify → exit non-zero with VERIFY FAIL" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*) printf 'sha123\n'; exit 0 ;;
  *"lambda get-function "*) exit 0 ;;  # always exists → verify fails
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'
    exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr batch-delete-image"*) exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"VERIFY FAIL: Lambda"* ]]
}

@test "[review-cleanup] all resources already gone → exit 0 (full idempotency)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"All resources verified deleted"* ]]
}

# ── Langfuse trace deletion ───────────────────────────────────────────────────

# Helper: write aws stub that returns Langfuse vars from Lambda env
write_langfuse_aws_stub() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*"REVIEW_DEPLOY_SHA"*) printf 'abc1234\n'; exit 0 ;;
  *"get-function-configuration"*"DYNAMODB_TABLE_NAME"*) printf 'renate-conversations-dev\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_HOST"*) printf 'https://langfuse.example.com\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_SECRET_NAME"*) printf 'langfuse/dev/lambda-api-keys\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_REVIEW_TAG"*) printf 'review-feature-my-branch\n'; exit 0 ;;
  *"get-function-configuration"*) printf 'abc1234\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*) printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'; exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr list-images"*) printf '\n'; exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *"secretsmanager get-secret-value"*) printf '{"publicKey":"pk-test","secretKey":"sk-test"}\n'; exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

# Helper: write jq stub that handles Langfuse API responses.
# Reads body from the trailing file argument when present (new behavior after
# the events_only loud-fail rewrite — curl writes to body_file and jq reads
# it with a path arg); falls back to stdin for every other call site.
write_langfuse_jq_stub() {
  cat >"$TEST_DIR/bin/jq" <<'JQEOF'
#!/bin/bash
filter=""
file_arg=""
for arg in "$@"; do
  case "$arg" in
    -r|-c|-R|-s|-S) ;;
    --arg) ;;
    *)
      if [ -z "$filter" ]; then
        filter="$arg"
      elif [ -f "$arg" ]; then
        file_arg="$arg"
      fi
      ;;
  esac
done
if [ -n "$file_arg" ]; then
  input=$(cat "$file_arg")
else
  input=$(cat)
fi
case "$filter" in
  *FrontendFrontendS3BucketName*) printf 'renate-assets-dev-eu-central-1\n' ;;
  *AuthUserPoolId*)              printf 'eu-central-1_TestPool\n' ;;
  *'.Items[]'*|*'Items[]'*)
    if printf '%s' "$input" | grep -q '"Items":\[\]'; then :
    else
      printf '{"session_id":{"S":"review/feature-my-branch#s1"},"message_id":{"S":"m1"}}\n'
    fi ;;
  *'.session_id.S'*) printf 'review/feature-my-branch#s1\n' ;;
  *'.message_id.S'*) printf 'm1\n' ;;
  *'.publicKey'*) printf 'pk-test\n' ;;
  *'.secretKey'*) printf 'sk-test\n' ;;
  *'.data[].id'*)
    # Return trace IDs when input has data array with items
    if printf '%s' "$input" | grep -q '"id":"'; then
      printf '%s\n' "$input" | grep -o '"id":"[^"]*"' | sed 's/"id":"//;s/"//'
    fi ;;
  *'.meta.totalPages'*) printf '1\n' ;;
  *'split'*'select'*) printf '["trace-id-1","trace-id-2"]\n' ;;
  *) printf '%s\n' "$input" ;;
esac
JQEOF
  chmod +x "$TEST_DIR/bin/jq"
}

# Helper: write a curl stub that satisfies the new `curl -o FILE -w '%{http_code}'`
# shape used by delete_review_langfuse_traces after the events_only rewrite.
# Args:
#   $1 — body file content (what the real server would return)
#   $2 — status code to print on stdout for `-w '%{http_code}'`
#   $3 — exit code (default 0; set non-zero to simulate connect failure)
write_langfuse_curl_stub() {
  local body="$1" status="$2" rc="${3:-0}"
  CURL_LOG="$TEST_DIR/curl.log"
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$CURL_LOG"
out=""
want_status=0
while [ \$# -gt 0 ]; do
  case "\$1" in
    -o) out="\$2"; shift 2 ;;
    -w) [ "\$2" = '%{http_code}' ] && want_status=1; shift 2 ;;
    *) shift ;;
  esac
done
if [ -n "\$out" ]; then
  printf '%s' '$body' > "\$out"
fi
if [ "\$want_status" = 1 ]; then
  printf '%s' '$status'
fi
exit $rc
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/base64" <<'EOF'
#!/bin/bash
printf 'dGVzdA==\n'
EOF
  chmod +x "$TEST_DIR/bin/base64"
}

@test "[review-cleanup] Langfuse vars absent → skips trace deletion, exits 0" {
  # Default stub returns empty/None for Langfuse vars → block skipped
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping trace deletion"* ]]
  [[ "$output" == *"All resources verified deleted"* ]]
}

@test "[review-cleanup] Langfuse GET called with correct tag" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub
  write_langfuse_curl_stub '{"data":[],"meta":{"totalPages":1}}' '200' 0

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "review-feature-my-branch" "$CURL_LOG"
  grep -q "/api/public/traces" "$CURL_LOG"
  [[ "$output" == *"No Langfuse traces found"* ]]
}

@test "[review-cleanup] Langfuse DELETE called when traces found" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub

  # Dual-mode stub: GET uses `-o FILE -w %{http_code}` (new events_only path);
  # DELETE still uses `curl -sf -X DELETE ... >/dev/null`.
  CURL_LOG="$TEST_DIR/curl.log"
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$CURL_LOG"
if [[ "\$*" == *"-X DELETE"* ]]; then
  exit 0
fi
out=""
want_status=0
while [ \$# -gt 0 ]; do
  case "\$1" in
    -o) out="\$2"; shift 2 ;;
    -w) [ "\$2" = '%{http_code}' ] && want_status=1; shift 2 ;;
    *) shift ;;
  esac
done
body='{"data":[{"id":"trace-id-1"}],"meta":{"totalPages":1}}'
if [ -n "\$out" ]; then printf '%s' "\$body" > "\$out"; else printf '%s' "\$body"; fi
[ "\$want_status" = 1 ] && printf '200'
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/base64" <<'EOF'
#!/bin/bash
printf 'dGVzdA==\n'
EOF
  chmod +x "$TEST_DIR/bin/base64"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "\-X DELETE" "$CURL_LOG"
  [[ "$output" == *"Langfuse trace deletion complete"* ]]
}

@test "[review-cleanup] Langfuse GET network failure → logs WARNING, exits 0" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub
  # curl exits non-zero AND writes nothing to -o target. Pins the
  # `|| http_status="000"` idiom for the connect-failure branch.
  write_langfuse_curl_stub '' '' 7

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING: Langfuse GET traces page 1 connect failure"* ]]
}

@test "[review-cleanup] Langfuse GET returns events_only 404 → loud error banner, exits 0" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub
  # Marker body shape as returned by Langfuse OSS v4.61.0 live probe.
  write_langfuse_curl_stub \
    '{"error":"This endpoint is not available on deployments running in Langfuse v4 events_only mode."}' \
    '404' 0

  CI_COMMIT_REF_SLUG="feature-my-branch" run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ERROR: Langfuse cleanup unsupported under events_only"* ]]
  [[ "$output" == *"branch=feature-my-branch"* ]]
  [[ "$output" == *"tag=review-feature-my-branch"* ]]
  [[ "$output" == *"see #948"* ]]
  # The marker body is printed once for future-rename visibility.
  [[ "$output" == *"events_only mode"* ]]
  # Loop exits on first events_only detection — only one GET recorded.
  [ "$(grep -c '/api/public/traces' "$CURL_LOG")" -eq 1 ]
}

@test "[review-cleanup] Langfuse GET non-events_only 404 → plain WARNING, no error banner" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub
  write_langfuse_curl_stub '{"error":"Not Found"}' '404' 0

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING: Langfuse GET traces page 1 returned 404"* ]]
  [[ "$output" != *"cleanup unsupported under events_only"* ]]
}

@test "[review-cleanup] Langfuse DELETE failure → logs WARNING, exits 0" {
  write_langfuse_aws_stub
  write_langfuse_jq_stub

  CURL_LOG="$TEST_DIR/curl.log"
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$CURL_LOG"
if [[ "\$*" == *"-X DELETE"* ]]; then exit 1; fi
out=""
want_status=0
while [ \$# -gt 0 ]; do
  case "\$1" in
    -o) out="\$2"; shift 2 ;;
    -w) [ "\$2" = '%{http_code}' ] && want_status=1; shift 2 ;;
    *) shift ;;
  esac
done
body='{"data":[{"id":"trace-id-1"}],"meta":{"totalPages":1}}'
if [ -n "\$out" ]; then printf '%s' "\$body" > "\$out"; else printf '%s' "\$body"; fi
[ "\$want_status" = 1 ] && printf '200'
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/base64" <<'EOF'
#!/bin/bash
printf 'dGVzdA==\n'
EOF
  chmod +x "$TEST_DIR/bin/base64"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING: Langfuse DELETE batch failed"* ]]
}

@test "[review-cleanup] secret fetch failure → logs WARNING, exits 0" {
  write_langfuse_aws_stub

  # Override aws to fail on secretsmanager call
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"get-function-configuration"*"REVIEW_DEPLOY_SHA"*) printf 'abc1234\n'; exit 0 ;;
  *"get-function-configuration"*"DYNAMODB_TABLE_NAME"*) printf 'renate-conversations-dev\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_HOST"*) printf 'https://langfuse.example.com\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_SECRET_NAME"*) printf 'langfuse/dev/lambda-api-keys\n'; exit 0 ;;
  *"get-function-configuration"*"LANGFUSE_REVIEW_TAG"*) printf 'review-feature-my-branch\n'; exit 0 ;;
  *"get-function-configuration"*) printf 'abc1234\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"cloudformation describe-stacks"*) printf '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"}]}]}\n'; exit 0 ;;
  *"s3 rm"*) exit 0 ;;
  *"ecr list-images"*) printf '\n'; exit 0 ;;
  *"ecr describe-images"*) exit 1 ;;
  *"dynamodb scan"*"COUNT"*) printf '0\n'; exit 0 ;;
  *"dynamodb scan"*) printf '{"Items":[],"Count":0}\n'; exit 0 ;;
  *"s3api list-objects-v2"*) printf '0\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *"secretsmanager get-secret-value"*) printf 'AccessDenied\n' >&2; exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING: Could not fetch Langfuse secret"* ]]
}

@test "[review-cleanup] secret values never printed in output" {
  write_langfuse_aws_stub

  # Override jq to return detectable fake key values
  cat >"$TEST_DIR/bin/jq" <<'JQEOF'
#!/bin/bash
filter=""
for arg in "$@"; do
  case "$arg" in -r|-c|-R|-s|-S) ;; --arg) ;; *) [ -z "$filter" ] && filter="$arg" ;; esac
done
input=$(cat)
case "$filter" in
  *FrontendFrontendS3BucketName*) printf 'renate-assets-dev-eu-central-1\n' ;;
  *AuthUserPoolId*) printf 'eu-central-1_TestPool\n' ;;
  *'.Items[]'*) : ;;
  *'.session_id.S'*) printf 'review/x#s1\n' ;;
  *'.message_id.S'*) printf 'm1\n' ;;
  *'.publicKey'*) printf 'DETECTABLE_PUBLIC_KEY\n' ;;
  *'.secretKey'*) printf 'DETECTABLE_SECRET_KEY\n' ;;
  *'.data[].id'*) ;;
  *'.meta.totalPages'*) printf '1\n' ;;
  *) printf '%s\n' "$input" ;;
esac
JQEOF
  chmod +x "$TEST_DIR/bin/jq"

  write_langfuse_curl_stub '{"data":[],"meta":{"totalPages":1}}' '200' 0

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" != *"DETECTABLE_PUBLIC_KEY"* ]]
  [[ "$output" != *"DETECTABLE_SECRET_KEY"* ]]
}
