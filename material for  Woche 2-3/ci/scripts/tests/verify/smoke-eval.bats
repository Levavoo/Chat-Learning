#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/smoke-eval.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"

  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="99"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_aws_stub() {
  local sts_output="$1"
  local api_url="${2:-https://example.execute-api.eu-central-1.amazonaws.com/prod/}"
  # Note: ${3-...} (no colon) so an explicit empty string is kept, not defaulted.
  local cf_url="${3-https://d123.cloudfront.net}"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role-with-web-identity"* ]]; then
  printf '%s\n' "$sts_output"
  exit 0
fi
if [[ "\$*" == *"FrontendCloudFrontDistributionUrl"* ]]; then
  echo "$cf_url"
  exit 0
fi
if [[ "\$*" == *"describe-stacks"* ]]; then
  echo "$api_url"
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[smoke-eval] empty STS output → exit 1 with error message" {
  _aws_stub ""
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[smoke-eval] valid STS + empty API URL → exit 1 with error message" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then
  printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'
  exit 0
fi
if [[ "$*" == *"describe-stacks"* ]]; then
  printf ''
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ApiUrl not found"* ]]
}

@test "[smoke-eval] valid STS + curl success → exit 0 with OK message" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Smoke eval [dev]: OK"* ]]
}

@test "[smoke-eval] valid STS + curl failure → exit 1" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 1
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 1 ]
}

@test "[smoke-eval] API ok + CloudFront URL served → GET frontend + exit 0" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 0 ]
  [[ "$output" == *"GET https://d123.cloudfront.net/ (frontend)"* ]]
  [[ "$output" == *"Smoke eval [dev]: OK"* ]]
}

@test "[smoke-eval] API ok but CloudFront request fails → exit 1" {
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w"
  # Health (API GW) succeeds; the CloudFront GET fails.
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
[[ "$*" == *"cloudfront"* ]] && exit 1
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 1 ]
}

@test "[smoke-eval] CloudFront URL output missing → exit 1 with error message" {
  # ApiUrl resolves, but the FrontendCloudFrontDistributionUrl output is empty.
  _aws_stub "AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w" \
    "https://example.execute-api.eu-central-1.amazonaws.com/prod/" ""
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$SCRIPT" "arn:aws:iam::123:role/test" "renate-chatbot-dev" "dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"FrontendCloudFrontDistributionUrl not found"* ]]
}

@test "[smoke-eval] smoke-eval-dev.sh passes correct args (role, stack, label)" {
  WRAPPER="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/smoke-eval-dev.sh"
  CAPTURED="$TEST_DIR/args"
  cat >"$TEST_DIR/bin/bash" <<EOF
#!/bin/bash
# Intercept exec bash .../smoke-eval.sh <args>
shift  # drop the script path
echo "\$@" > "$CAPTURED"
EOF
  chmod +x "$TEST_DIR/bin/bash"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::831926590742:role/test-dev-role"
  run /bin/bash "$WRAPPER"
  [ -f "$CAPTURED" ]
  [[ "$(cat "$CAPTURED")" == *"renate-chatbot-dev"* ]]
  [[ "$(cat "$CAPTURED")" == *"dev"* ]]
  [[ "$(cat "$CAPTURED")" == *"$CDK_DEPLOY_ROLE_ARN_DEV"* ]]
}

@test "[smoke-eval] smoke-eval-qa.sh passes correct args (role, stack, label)" {
  WRAPPER="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/smoke-eval-qa.sh"
  CAPTURED="$TEST_DIR/args"
  cat >"$TEST_DIR/bin/bash" <<EOF
#!/bin/bash
shift
echo "\$@" > "$CAPTURED"
EOF
  chmod +x "$TEST_DIR/bin/bash"
  export CDK_DEPLOY_ROLE_ARN_QA="arn:aws:iam::571600837515:role/test-qa-role"
  run /bin/bash "$WRAPPER"
  [ -f "$CAPTURED" ]
  [[ "$(cat "$CAPTURED")" == *"renate-chatbot-qa"* ]]
  [[ "$(cat "$CAPTURED")" == *"qa"* ]]
  [[ "$(cat "$CAPTURED")" == *"$CDK_DEPLOY_ROLE_ARN_QA"* ]]
}

@test "[smoke-eval] smoke-eval-preprod.sh delegates to smoke-eval-env.sh with preprod arg" {
  WRAPPER="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/smoke-eval-preprod.sh"
  # The wrapper uses exec .../smoke-eval-env.sh preprod — verify it passes 'preprod'
  # by running with a mock that captures the resolved env argument
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test-preprod-role"
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "$*" == *"describe-stacks"* ]]; then echo "https://x.example.com/prod/"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Smoke eval [preprod]: OK"* ]]
}

SMOKE_ENV_SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/smoke-eval-env.sh"

@test "[smoke-eval-env] unknown env → exit 1" {
  run bash "$SMOKE_ENV_SCRIPT" staging
  [ "$status" -eq 1 ]
}

@test "[smoke-eval-env] role var unset → exit 1 with var name" {
  unset CDK_DEPLOY_ROLE_ARN_PREPROD || true
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 1 ]
  [[ "$output" == *"CDK_DEPLOY_ROLE_ARN_PREPROD"* ]]
}

@test "[smoke-eval-env] valid role + health OK → exit 0 on first attempt" {
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "$*" == *"describe-stacks"* ]]; then echo "https://x.example.com/prod/"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 0 ]
  [[ "$output" == *"Smoke eval [preprod]: OK"* ]]
}

@test "[smoke-eval-env] transient curl failure → retries and succeeds" {
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "$*" == *"describe-stacks"* ]]; then echo "https://x.example.com/prod/"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  # Fail first attempt, succeed on second
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
COUNT_FILE="$TEST_DIR/curl_count"
count=\$(cat "\$COUNT_FILE" 2>/dev/null || echo 0)
count=\$(( count + 1 ))
echo "\$count" > "\$COUNT_FILE"
[ "\$count" -ge 2 ] && exit 0
exit 1
EOF
  chmod +x "$TEST_DIR/bin/curl"
  # Speed up: base delay 0, max 1
  export SMOKE_BASE_DELAY_S=0 SMOKE_MAX_DELAY_S=1
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 0 ]
  [[ "$output" == *"retry"* ]]
  [[ "$output" == *"Smoke eval [preprod]: OK"* ]]
}

@test "[smoke-eval-env] all attempts fail → exit 1 with FAILED message" {
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "$*" == *"describe-stacks"* ]]; then echo "https://x.example.com/prod/"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 1
EOF
  chmod +x "$TEST_DIR/bin/curl"
  export SMOKE_MAX_ATTEMPTS=2 SMOKE_BASE_DELAY_S=0 SMOKE_MAX_DELAY_S=1
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}

# Query-aware stub: ApiUrl query → API GW URL, CloudFront query → cloudfront URL.
_aws_stub_env() {
  # ${1-...} (no colon) so an explicit empty string is kept, not defaulted.
  local cf_url="${1-https://d456.cloudfront.net}"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "\$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "\$*" == *"FrontendCloudFrontDistributionUrl"* ]]; then echo "$cf_url"; exit 0; fi
if [[ "\$*" == *"describe-stacks"* ]]; then echo "https://x.example.com/prod/"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[smoke-eval-env] health ok but CloudFront fails → exit 1 with frontend FAILED" {
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test"
  _aws_stub_env
  # Health (API GW) succeeds; every CloudFront GET fails.
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
[[ "$*" == *"cloudfront"* ]] && exit 1
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  export SMOKE_MAX_ATTEMPTS=2 SMOKE_BASE_DELAY_S=0 SMOKE_MAX_DELAY_S=1
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 1 ]
  [[ "$output" == *"frontend FAILED"* ]]
}

@test "[smoke-eval-env] CloudFront URL output missing → exit 1 with error message" {
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test"
  _aws_stub_env ""
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
  export GITLAB_OIDC_TOKEN="tok"
  export CI_JOB_ID="1"
  run bash "$SMOKE_ENV_SCRIPT" preprod
  [ "$status" -eq 1 ]
  [[ "$output" == *"FrontendCloudFrontDistributionUrl not found"* ]]
}
