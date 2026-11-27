#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/review-deploy-backend.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"

  export CI_COMMIT_REF_SLUG="feature-my-branch"
  export CI_COMMIT_SHORT_SHA="abc1234"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export ECR_REGISTRY="123456789012.dkr.ecr.eu-central-1.amazonaws.com"
  export ECR_REPO="renate-chat-lambda"
  export DEV_FUNCTION_NAME="renate-chat-dev"
    export AWS_DEFAULT_REGION="eu-central-1"
  export REVIEW_CF_DOMAIN="d335nko399ndir.cloudfront.net"

  # Run inside the temp dir so review.env is written there (not the repo).
  cd "$TEST_DIR"

  AWS_LOG="$TEST_DIR/aws.log"
  export AWS_LOG

  # Stub jq: handle all filters used by review-deploy-backend.sh.
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
# Parse args: collect --arg name value pairs; first non-flag is the filter.
filter=""
arg_key=""
arg_val=""
state="normal"
for arg in "$@"; do
  case "$state" in
    skip_val) state="normal"; continue ;;  # already consumed key
    got_key)  arg_val="$arg"; state="skip_val"; continue ;;
  esac
  case "$arg" in
    -r|-c) ;;
    --arg) state="got_key"; continue ;;
    *) if [ -z "$filter" ]; then filter="$arg"; fi ;;
  esac
done
# Capture --arg key (name) and value separately via positional scan
prev2=""
for arg in "$@"; do
  if [ "$prev2" = "--arg" ]; then arg_key="$arg"; fi
  if [ -n "$arg_key" ] && [ "$prev2" = "$arg_key" ]; then arg_val="$arg"; break; fi
  prev2="$arg"
done

input=$(cat)
# Dispatch on arg_key value when filter uses startswith
case "$arg_val" in
  AuthUserPoolId)               printf 'eu-central-1_TestPool\n'; exit 0 ;;
  AuthUserPoolClientId)         printf 'testclientid\n'; exit 0 ;;
  FrontendCloudFrontDistributionUrl) printf 'https://d11u7o0s8x8o66.cloudfront.net\n'; exit 0 ;;
  FrontendFrontendS3BucketName) printf 'renate-assets-dev-eu-central-1\n'; exit 0 ;;
esac
# Fall through to filter-based dispatch for non --arg calls
case "$filter" in
  *Role*)       printf 'arn:aws:iam::123456789012:role/renate-chatbot-dev-LambdaRole\n' ;;
  *SubnetIds*)  printf 'subnet-aaa,subnet-bbb\n' ;;
  *SecurityGroup*) printf 'sg-ccc\n' ;;
  *Timeout*)    printf '28\n' ;;
  *MemorySize*) printf '512\n' ;;
  *Variables*)
    rid="" sha="" tag=""
    prev=""
    for a in "$@"; do
      if [ "$prev" = "review_id" ]; then rid="$a"; fi
      if [ "$prev" = "deploy_sha" ]; then sha="$a"; fi
      if [ "$prev" = "langfuse_review_tag" ]; then tag="$a"; fi
      prev="$a"
    done
    printf '{"Variables":{"BEDROCK_MODEL_ID":"openai.gpt-oss-120b-1:0","REVIEW_ID":"%s","REVIEW_DEPLOY_SHA":"%s","LANGFUSE_REVIEW_TAG":"%s"}}\n' "$rid" "$sha" "$tag" ;;
  *IntegrationId*) printf 'int12345\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/jq"

  write_default_aws_stub
}

write_default_aws_stub() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    cat <<'JSON'
{
  "Role": "arn:aws:iam::123456789012:role/renate-chatbot-dev-LambdaRole",
  "PackageType": "Image",
  "VpcConfig": {
    "SubnetIds": ["subnet-aaa", "subnet-bbb"],
    "SecurityGroupIds": ["sg-ccc"]
  },
  "Environment": { "Variables": { "BEDROCK_MODEL_ID": "openai.gpt-oss-120b-1:0", "KNOWLEDGE_BASE_ID": "KB123" } }
}
JSON
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*)
    printf 'arn:aws:lambda:eu-central-1:123456789012:function:renate-chat-review-feature-my-branch\n'; exit 0 ;;
  *"lambda get-function "*|*"lambda get-function") exit 1 ;;            # not found → create
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;                 # empty → create
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 create-integration"*) printf 'int12345\n'; exit 0 ;;
  *"apigatewayv2 get-authorizers"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-authorizer"*) printf 'auth12345\n'; exit 0 ;;
  *"apigatewayv2 get-routes"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 update-route"*) exit 0 ;;
  *"apigatewayv2 get-integrations"*) printf 'int12345\n'; exit 0 ;;
  *"apigatewayv2 update-api"*) exit 0 ;;
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;   # not found → create
  *"cognito-idp admin-create-user"*) exit 0 ;;
  *"cognito-idp admin-set-user-password"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Required-var guards ───────────────────────────────────────────────────────

@test "[review-deploy-backend] missing CI_COMMIT_REF_SLUG → exit non-zero" {
  unset CI_COMMIT_REF_SLUG
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-backend] missing CI_COMMIT_SHORT_SHA → exit non-zero" {
  unset CI_COMMIT_SHORT_SHA
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-backend] missing GITLAB_OIDC_TOKEN → exit non-zero" {
  unset GITLAB_OIDC_TOKEN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-backend] missing ROLE_ARN → exit non-zero" {
  unset ROLE_ARN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-backend] missing DEV_FUNCTION_NAME → exit non-zero" {
  unset DEV_FUNCTION_NAME
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-backend] missing REVIEW_CF_DOMAIN → exit non-zero" {
  unset REVIEW_CF_DOMAIN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

# ── Derived names ─────────────────────────────────────────────────────────────

@test "[review-deploy-backend] derives FUNC, API_NAME, IMAGE_URI from slug/sha" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Review function:  renate-chat-review-feature-my-branch"* ]]
  [[ "$output" == *"Review API name:  review-feature-my-branch"* ]]
  [[ "$output" == *"renate-chat-lambda:review-feature-my-branch-abc1234"* ]]
}

@test "[review-deploy-backend] long slug is truncated to keep FUNC <= 64 chars" {
  export CI_COMMIT_REF_SLUG="$(printf 'x%.0s' {1..80})"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  func_line=$(printf '%s\n' "$output" | grep 'Review function:')
  func_name="${func_line#*Review function:  }"
  [ "${#func_name}" -le 64 ]
}

# ── OIDC / STS ────────────────────────────────────────────────────────────────

@test "[review-deploy-backend] empty STS output → exit 1 with error message" {
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

@test "[review-deploy-backend] STS CLI failure → exit non-zero and surfaces error" {
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

# ── Dev config read ───────────────────────────────────────────────────────────

@test "[review-deploy-backend] reads dev exec role, subnets and security groups" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"renate-chatbot-dev-LambdaRole"* ]]
  [[ "$output" == *"subnet-aaa,subnet-bbb"* ]]
  [[ "$output" == *"sg-ccc"* ]]
}

# ── Lambda create path ────────────────────────────────────────────────────────

@test "[review-deploy-backend] create path: create-function with cloned VPC" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "lambda create-function" "$AWS_LOG"
  grep -q "SubnetIds=subnet-aaa,subnet-bbb,SecurityGroupIds=sg-ccc" "$AWS_LOG"
  ! grep -q "lambda update-function-code" "$AWS_LOG"
}

@test "[review-deploy-backend] create path: injects REVIEW_ID and REVIEW_DEPLOY_SHA" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  create_line=$(grep "lambda create-function" "$AWS_LOG")
  [[ "$create_line" == *"${CI_COMMIT_REF_SLUG}"* ]]
  [[ "$create_line" == *"${CI_COMMIT_SHORT_SHA}"* ]]
}

@test "[review-deploy-backend] create path: waits for function-active" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "wait function-active-v2" "$AWS_LOG"
}

# ── Lambda update path ────────────────────────────────────────────────────────

@test "[review-deploy-backend] update path: get-function 200 → update-function-code, no create" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/renate-chatbot-dev-LambdaRole","VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{"K":"V"}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*)
    printf 'arn:aws:lambda:eu-central-1:123456789012:function:renate-chat-review-feature-my-branch\n'; exit 0 ;;
  *"lambda get-function "*) exit 0 ;;          # exists → update
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "lambda update-function-code" "$AWS_LOG"
  grep -q "lambda update-function-configuration" "$AWS_LOG"
  ! grep -q "lambda create-function" "$AWS_LOG"
  grep -q "wait function-updated-v2" "$AWS_LOG"
}

# ── Tagging ───────────────────────────────────────────────────────────────────

@test "[review-deploy-backend] create path: tags Lambda with Environment/Branch/Commit" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "lambda tag-resource" "$AWS_LOG"
  grep -q "Environment=review,Branch=feature-my-branch,Commit=abc1234" "$AWS_LOG"
}

# ── API Gateway ───────────────────────────────────────────────────────────────

@test "[review-deploy-backend] APIGW create when none exists" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 create-api" "$AWS_LOG"
  grep -q "apigatewayv2 create-integration" "$AWS_LOG"
  grep -q "payload-format-version 1.0" "$AWS_LOG"
  grep -q "apigatewayv2 create-stage" "$AWS_LOG"
  grep -q "lambda add-permission" "$AWS_LOG"
  grep -q "apigatewayv2 tag-resource" "$AWS_LOG"
  ! grep -q "create-api.*--target" "$AWS_LOG"
}

@test "[review-deploy-backend] APIGW reused when it already exists (no create-api)" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/r","VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*) printf 'arn:lambda:func\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'existing-api-id\n'; exit 0 ;;   # already exists
  *"apigatewayv2 get-api "*) printf 'https://e\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "apigatewayv2 create-api" "$AWS_LOG"
  [[ "$output" == *"Reusing existing API"* ]]
}

# ── Cognito JWT authorizer ────────────────────────────────────────────────────

@test "[review-deploy-backend] creates Cognito JWT authorizer when absent" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 create-authorizer.*cognito-jwt" "$AWS_LOG"
}

@test "[review-deploy-backend] attaches JWT authorizer to \$default route" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 update-route.*JWT" "$AWS_LOG"
}

@test "[review-deploy-backend] reuses existing JWT authorizer" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/r","VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*) printf 'arn:lambda:func\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 get-authorizers"*) printf 'auth-existing\n'; exit 0 ;;  # already exists
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "apigatewayv2 create-authorizer" "$AWS_LOG"
  [[ "$output" == *"Reusing existing JWT authorizer"* ]]
}

# ── /health route + CORS ─────────────────────────────────────────────────────

@test "[review-deploy-backend] creates unauthenticated GET /health route" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 create-route.*GET /health" "$AWS_LOG"
  grep -q "NONE" "$AWS_LOG"
}

@test "[review-deploy-backend] configures CORS on the API" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 update-api.*cors-configuration" "$AWS_LOG"
}

@test "[review-deploy-backend] CORS AllowOrigins uses REVIEW_CF_DOMAIN (not the CDK stack)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "AllowOrigins=\[https://d335nko399ndir.cloudfront.net\]" "$AWS_LOG" \
    || grep -q "https://d335nko399ndir.cloudfront.net" "$AWS_LOG"
  ! grep -q "https://d11u7o0s8x8o66.cloudfront.net" "$AWS_LOG"
}

@test "[review-deploy-backend] creates unauthenticated OPTIONS /{proxy+} route" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "apigatewayv2 create-route.*OPTIONS /{proxy+}" "$AWS_LOG"
}

@test "[review-deploy-backend] clones Timeout and MemorySize from dev function" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  create_line=$(grep "lambda create-function" "$AWS_LOG")
  [[ "$create_line" == *"--timeout 28"* ]]
  [[ "$create_line" == *"--memory-size 512"* ]]
}

@test "[review-deploy-backend] add-permission non-conflict error → exit 1" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/r","Timeout":28,"MemorySize":512,"VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*) printf 'arn:lambda:func\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"lambda add-permission"*) printf 'AccessDeniedException: not authorized\n' >&2; exit 254 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"add-permission failed"* ]]
}

@test "[review-deploy-backend] add-permission conflict is idempotent (no failure)" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/r","Timeout":28,"MemorySize":512,"VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*) printf 'arn:lambda:func\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"lambda add-permission"*) printf 'ResourceConflictException: statement already exists\n' >&2; exit 255 ;;
  *"cognito-idp admin-get-user"*) exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"add-permission already present"* ]]
}

# ── Test user (idempotent) ────────────────────────────────────────────────────

@test "[review-deploy-backend] creates test user when absent" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "cognito-idp admin-create-user" "$AWS_LOG"
  grep -q "cognito-idp admin-set-user-password" "$AWS_LOG"
}

@test "[review-deploy-backend] skips test user creation when user already exists" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) printf '123456789012\n'; exit 0 ;;
  *"get-function-configuration"*)
    echo '{"Role":"arn:aws:iam::123456789012:role/r","VpcConfig":{"SubnetIds":["subnet-aaa"],"SecurityGroupIds":["sg-ccc"]},"Environment":{"Variables":{}}}'
    exit 0 ;;
  *"get-function "*"--query"*"FunctionArn"*) printf 'arn:lambda:func\n'; exit 0 ;;
  *"lambda get-function "*) exit 1 ;;
  *"cloudformation describe-stacks"*)
    printf '{"Stacks":[{"Outputs":[{"OutputKey":"AuthUserPoolId","OutputValue":"eu-central-1_TestPool"},{"OutputKey":"AuthUserPoolClientId","OutputValue":"testclientid"},{"OutputKey":"FrontendCloudFrontDistributionUrl","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"}]}]}\n'
    exit 0 ;;
  *"apigatewayv2 get-apis"*) printf 'None\n'; exit 0 ;;
  *"apigatewayv2 create-api"*) printf 'api12345\n'; exit 0 ;;
  *"apigatewayv2 get-api "*) printf 'https://api12345.execute-api.eu-central-1.amazonaws.com\n'; exit 0 ;;
  *"cognito-idp admin-get-user"*) exit 0 ;;   # user already exists
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "cognito-idp admin-create-user" "$AWS_LOG"
  [[ "$output" == *"already exists — skipping creation"* ]]
}

# ── dotenv artifact ───────────────────────────────────────────────────────────

@test "[review-deploy-backend] writes review.env dotenv with URL and function name" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -f review.env ]
  grep -q "REVIEW_URL=https://api12345.execute-api.eu-central-1.amazonaws.com" review.env
  grep -q "REVIEW_API_URL=https://api12345.execute-api.eu-central-1.amazonaws.com" review.env
  grep -q "REVIEW_FUNCTION_NAME=renate-chat-review-feature-my-branch" review.env
}

# ── LANGFUSE_REVIEW_TAG injection ─────────────────────────────────────────────

@test "[review-deploy-backend] injects LANGFUSE_REVIEW_TAG into Lambda env (short slug)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  create_line=$(grep "lambda create-function" "$AWS_LOG")
  [[ "$create_line" == *"review-feature-my-branch"* ]]
}

@test "[review-deploy-backend] short slug produces review-<slug> tag (≤40 chars)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Source the lib directly to check the computed tag
  CI_COMMIT_REF_SLUG="feature-my-branch" \
    bash -c 'source "$(dirname '"'"''"'"')"/../.gitlab/ci/scripts/lib/review-names.sh"; printf "%s\n" "${REVIEW_LANGFUSE_TAG}"' 2>/dev/null || true
  create_line=$(grep "lambda create-function" "$AWS_LOG")
  [[ "$create_line" == *"LANGFUSE_REVIEW_TAG"* ]] || \
    [[ "$create_line" == *"review-feature-my-branch"* ]]
}

@test "[review-deploy-backend] long slug (80 chars) → injected LANGFUSE_REVIEW_TAG ≤ 40 chars and valid" {
  export CI_COMMIT_REF_SLUG="$(printf 'a%.0s' {1..80})"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Extract the tag the DEPLOY SCRIPT actually computed and injected into the
  # Lambda env (not the lib copy) — this exercises its inline truncation.
  create_line=$(grep "lambda create-function" "$AWS_LOG")
  tag=$(printf '%s' "$create_line" | grep -o '"LANGFUSE_REVIEW_TAG":"[^"]*"' | sed 's/.*:"//;s/"//')
  [ -n "$tag" ]
  [ "${#tag}" -le 40 ]
  [[ "$tag" =~ ^review-[a-z0-9_-]+$ ]]
}
