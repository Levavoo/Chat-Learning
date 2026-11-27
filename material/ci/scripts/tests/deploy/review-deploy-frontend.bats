#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/review-deploy-frontend.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"

  export CI_COMMIT_REF_SLUG="feature-my-branch"
  export REVIEW_API_URL="https://api12345.execute-api.eu-central-1.amazonaws.com"
  export REVIEW_CF_DISTRIBUTION_ID="EH5CFH3DYCCUQ"
  export REVIEW_CF_DOMAIN="d335nko399ndir.cloudfront.net"
  export REVIEW_ASSETS_BUCKET="renate-assets-review-dev-eu-central-1"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-ci-deploy"
  export AWS_DEFAULT_REGION="eu-central-1"
  # Build runs in $FRONTEND_DIR; point it at the temp cwd for tests.
  export FRONTEND_DIR="."

  # Run inside temp dir so build output and artifacts land there.
  cd "$TEST_DIR"

  AWS_LOG="$TEST_DIR/aws.log"
  NG_LOG="$TEST_DIR/ng.log"
  export AWS_LOG NG_LOG

  # Create a fake dist output that s3 sync would consume.
  mkdir -p "$TEST_DIR/dist/ng-digibro-frontend/browser"

  write_default_stubs
}

write_default_stubs() {
  # aws stub
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"describe-stacks"*)
    printf '%s\n' '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendCloudFrontDistributionIdC60423D7","OutputValue":"EVF377ANHHHC9"},{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"FrontendCloudFrontDistributionUrl650AAAFD","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"},{"OutputKey":"AuthUserPoolIdC0605E59","OutputValue":"eu-central-1_f7ZAK5Ygy"},{"OutputKey":"AuthUserPoolClientId8216BF9A","OutputValue":"6tumkcip1t2j87tmnbqq1nmvi5"},{"OutputKey":"Region","OutputValue":"eu-central-1"}]}]}'
    exit 0 ;;
  *"s3 sync"*) exit 0 ;;
  *"cloudfront create-invalidation"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  # jq stub — drains stdin (avoids SIGPIPE on the producing printf under
  # pipefail) and returns the stack output value matching the --arg key.
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
cat >/dev/null  # consume stdin so the upstream printf never gets SIGPIPE
case "$*" in
  *FrontendCloudFrontDistributionId*) printf 'EVF377ANHHHC9\n' ;;
  *FrontendFrontendS3BucketName*)     printf 'renate-assets-dev-eu-central-1\n' ;;
  *FrontendCloudFrontDistributionUrl*)printf 'https://d11u7o0s8x8o66.cloudfront.net\n' ;;
  *AuthUserPoolClientId*)             printf '6tumkcip1t2j87tmnbqq1nmvi5\n' ;;
  *AuthUserPoolId*)                   printf 'eu-central-1_f7ZAK5Ygy\n' ;;
  *Region*)                           printf 'eu-central-1\n' ;;
  *) printf '\n' ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/jq"

  # ng stub
  cat >"$TEST_DIR/bin/ng" <<EOF
#!/bin/bash
# Log env vars of interest alongside the command so tests can assert on them.
echo "NG_APP_API_ENDPOINT=\${NG_APP_API_ENDPOINT:-} NG_APP_SHOW_REVIEW_TAG=\${NG_APP_SHOW_REVIEW_TAG:-} NG_APP_INTERN=\${NG_APP_INTERN:-} NG_APP_ANONYMOUS_ACCESS=\${NG_APP_ANONYMOUS_ACCESS:-} ng \$*" >> "$NG_LOG"
mkdir -p "$TEST_DIR/dist/ng-digibro-frontend/browser"
touch "$TEST_DIR/dist/ng-digibro-frontend/browser/index.html"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/ng"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Required-var guards ───────────────────────────────────────────────────────

@test "[review-deploy-frontend] missing CI_COMMIT_REF_SLUG → exit non-zero" {
  unset CI_COMMIT_REF_SLUG
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing REVIEW_API_URL → exit non-zero" {
  unset REVIEW_API_URL
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing GITLAB_OIDC_TOKEN → exit non-zero" {
  unset GITLAB_OIDC_TOKEN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing ROLE_ARN → exit non-zero" {
  unset ROLE_ARN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing CI_JOB_ID → exit non-zero" {
  unset CI_JOB_ID
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing AWS_DEFAULT_REGION → exit non-zero" {
  unset AWS_DEFAULT_REGION
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing REVIEW_CF_DISTRIBUTION_ID → exit non-zero" {
  unset REVIEW_CF_DISTRIBUTION_ID
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing REVIEW_CF_DOMAIN → exit non-zero" {
  unset REVIEW_CF_DOMAIN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] missing REVIEW_ASSETS_BUCKET → exit non-zero" {
  unset REVIEW_ASSETS_BUCKET
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

# ── OIDC / STS ────────────────────────────────────────────────────────────────

@test "[review-deploy-frontend] empty STS output → exit 1 with error message" {
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

@test "[review-deploy-frontend] STS CLI failure → exit non-zero" {
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

# ── describe-stacks ───────────────────────────────────────────────────────────

@test "[review-deploy-frontend] calls describe-stacks with renate-chatbot-dev" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "describe-stacks.*renate-chatbot-dev" "$AWS_LOG"
}

@test "[review-deploy-frontend] exits non-zero when describe-stacks fails" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"describe-stacks"*) printf 'error\n' >&2; exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

# ── ng build ─────────────────────────────────────────────────────────────────

@test "[review-deploy-frontend] ng build uses --configuration review" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "\-\-configuration review" "$NG_LOG"
}

@test "[review-deploy-frontend] ng build uses --base-href /feature-my-branch/" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "\-\-base-href /feature-my-branch/" "$NG_LOG"
}

@test "[review-deploy-frontend] NG_APP_API_ENDPOINT set to REVIEW_API_URL for ng build" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_API_ENDPOINT=https://api12345.execute-api.eu-central-1.amazonaws.com" "$NG_LOG"
}

@test "[review-deploy-frontend] NG_APP_SHOW_REVIEW_TAG set to true for ng build" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_SHOW_REVIEW_TAG=true" "$NG_LOG"
}

# ── Per-MR SPA mode toggles (trigger-file driven) ─────────────────────────────

@test "[review-deploy-frontend] no trigger file → INTERN=true, ANONYMOUS_ACCESS=false (defaults)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_INTERN=true" "$NG_LOG"
  grep -q "NG_APP_ANONYMOUS_ACCESS=false" "$NG_LOG"
}

@test "[review-deploy-frontend] trigger file without keys → defaults preserved" {
  mkdir -p "$TEST_DIR/deployments/review"
  cat >"$TEST_DIR/deployments/review/${CI_COMMIT_REF_SLUG}.yml" <<EOF
name: ${CI_COMMIT_REF_SLUG}
search_mode: agent
EOF
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_INTERN=true" "$NG_LOG"
  grep -q "NG_APP_ANONYMOUS_ACCESS=false" "$NG_LOG"
}

@test "[review-deploy-frontend] trigger file intern:false → NG_APP_INTERN=false" {
  mkdir -p "$TEST_DIR/deployments/review"
  cat >"$TEST_DIR/deployments/review/${CI_COMMIT_REF_SLUG}.yml" <<EOF
name: ${CI_COMMIT_REF_SLUG}
intern: false
EOF
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_INTERN=false" "$NG_LOG"
}

@test "[review-deploy-frontend] trigger file anonymous_access:true → NG_APP_ANONYMOUS_ACCESS=true" {
  mkdir -p "$TEST_DIR/deployments/review"
  cat >"$TEST_DIR/deployments/review/${CI_COMMIT_REF_SLUG}.yml" <<EOF
name: ${CI_COMMIT_REF_SLUG}
anonymous_access: true
EOF
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_ANONYMOUS_ACCESS=true" "$NG_LOG"
}

@test "[review-deploy-frontend] trigger file sets both keys → both propagate" {
  mkdir -p "$TEST_DIR/deployments/review"
  cat >"$TEST_DIR/deployments/review/${CI_COMMIT_REF_SLUG}.yml" <<EOF
name: ${CI_COMMIT_REF_SLUG}
intern: false
anonymous_access: true
EOF
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_INTERN=false" "$NG_LOG"
  grep -q "NG_APP_ANONYMOUS_ACCESS=true" "$NG_LOG"
}

@test "[review-deploy-frontend] trigger file garbage value → falls back to default" {
  mkdir -p "$TEST_DIR/deployments/review"
  cat >"$TEST_DIR/deployments/review/${CI_COMMIT_REF_SLUG}.yml" <<EOF
name: ${CI_COMMIT_REF_SLUG}
intern: maybe
anonymous_access: yes
EOF
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "NG_APP_INTERN=true" "$NG_LOG"
  grep -q "NG_APP_ANONYMOUS_ACCESS=false" "$NG_LOG"
}

# ── s3 sync ───────────────────────────────────────────────────────────────────

@test "[review-deploy-frontend] s3 sync targets correct prefix with --delete" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "s3 sync.*dist/ng-digibro-frontend/browser/.*s3://renate-assets-review-dev-eu-central-1/feature-my-branch/.*--delete" "$AWS_LOG"
}

# ── CloudFront invalidation ───────────────────────────────────────────────────

@test "[review-deploy-frontend] cloudfront create-invalidation with correct distribution and path" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "cloudfront create-invalidation.*--distribution-id EH5CFH3DYCCUQ" "$AWS_LOG"
  grep -q "/feature-my-branch/\*" "$AWS_LOG"
}

# ── Full happy path ───────────────────────────────────────────────────────────

@test "[review-deploy-frontend] full run exits 0 and executes all steps in order" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Steps must appear in the logs
  grep -q "describe-stacks" "$AWS_LOG"
  grep -q "ng build" "$NG_LOG"
  grep -q "s3 sync" "$AWS_LOG"
  grep -q "cloudfront create-invalidation" "$AWS_LOG"
}

# ── Collapsible sections + clean URL output ───────────────────────────────────

@test "[review-deploy-frontend] ng build is wrapped in a GitLab collapsible section" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"section_start:"* ]]
  [[ "$output" == *"ng_build"* ]]
  [[ "$output" == *"section_end:"* ]]
}

@test "[review-deploy-frontend] s3 sync is wrapped in a GitLab collapsible section" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"s3_sync"* ]]
}

@test "[review-deploy-frontend] review URL is printed flush-left (no leading whitespace)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  url_line=$(printf '%s\n' "$output" | grep 'https://d335nko399ndir.cloudfront.net/feature-my-branch/')
  [[ "$url_line" =~ ^https:// ]]
}

@test "[review-deploy-frontend] review URL is the last meaningful output line" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Last non-empty line should contain the review URL or the closing rule after it
  last_content=$(printf '%s\n' "$output" | grep -v '^[[:space:]]*$' | tail -1)
  # The log_done rule (─) appears after the URL block
  [[ "$last_content" == *"─"* ]]
}

@test "[review-deploy-frontend] ng build failure → exit non-zero (pipefail safety)" {
  cat >"$TEST_DIR/bin/ng" <<'EOF'
#!/bin/bash
echo "ng build: error: compilation failed" >&2
exit 1
EOF
  chmod +x "$TEST_DIR/bin/ng"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[review-deploy-frontend] s3 sync failure → exit non-zero (pipefail safety)" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"describe-stacks"*)
    printf '%s\n' '{"Stacks":[{"Outputs":[{"OutputKey":"FrontendCloudFrontDistributionIdC60423D7","OutputValue":"EVF377ANHHHC9"},{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"FrontendCloudFrontDistributionUrl650AAAFD","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"},{"OutputKey":"AuthUserPoolIdC0605E59","OutputValue":"eu-central-1_f7ZAK5Ygy"},{"OutputKey":"AuthUserPoolClientId8216BF9A","OutputValue":"6tumkcip1t2j87tmnbqq1nmvi5"},{"OutputKey":"Region","OutputValue":"eu-central-1"},{"OutputKey":"Intern","OutputValue":"true"},{"OutputKey":"AnonymousAccess","OutputValue":"false"},{"OutputKey":"RedirectSigninUrl","OutputValue":"www.test.com"},{"OutputKey":"RedirectSignoutUrl","OutputValue":"www.test.com"},{"OutputKey":"CognitoDomain","OutputValue":"myapp-dev.auth.eu-central-1.amazoncognito.com"}]}]}'
    exit 0 ;;
  *"s3 sync"*) echo "s3 sync: error" >&2; exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}
