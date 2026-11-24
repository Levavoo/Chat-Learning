#!/usr/bin/env bats

# Tests for .gitlab/ci/scripts/deploy/deploy-frontend.sh (#648).
#
# Uses real jq (installed on all runners); stubs only aws + npm. The
# script's util/get-stack-outputs.sh runs against the aws stub and produces
# a real JSON file that the script then parses with real jq.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-frontend.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"

  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export ROLE_ARN="arn:aws:iam::123456789012:role/ki-lab-digibro-dev-frontend-deploy"
  export AWS_DEFAULT_REGION="eu-central-1"

  cd "$TEST_DIR"

  # Frontend workspace: point FRONTEND_DIR at a fake dir under the tempdir so
  # the script's `cd $FRONTEND_DIR` + npm run + maintenance copy have somewhere
  # to land.
  export FRONTEND_DIR="frontend"
  mkdir -p "${FRONTEND_DIR}/src/maintenance-page"
  touch "${FRONTEND_DIR}/src/maintenance-page/index.html"

  # Config fixtures per env — the script reads deployments/<env>/config.yaml.
  mkdir -p deployments/dev deployments/qa deployments/preprod deployments/prod
  cat >deployments/dev/config.yaml     <<<'anonymousAccess: false
intern: true'
  cat >deployments/qa/config.yaml      <<<'anonymousAccess: true
intern: false'
  cat >deployments/preprod/config.yaml <<<'anonymousAccess: false
intern: false'
  cat >deployments/prod/config.yaml    <<<'anonymousAccess: false
intern: false'

  AWS_LOG="$TEST_DIR/aws.log"
  NPM_LOG="$TEST_DIR/npm.log"
  export AWS_LOG NPM_LOG

  write_default_stubs
}

write_default_stubs() {
  # aws stub: returns fake describe-stacks JSON in AWS format.
  # get-stack-outputs.sh will re-shape it into CDK format, then our script
  # runs real jq against that file.
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*)
    printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0 ;;
  *"get-caller-identity"*) exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '%s\n' '[{"OutputKey":"FrontendCloudFrontDistributionIdC60423D7","OutputValue":"EDEV111DIST"},{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"FrontendCloudFrontDistributionUrl650AAAFD","OutputValue":"https://d11u7o0s8x8o66.cloudfront.net"},{"OutputKey":"AuthUserPoolIdC0605E59","OutputValue":"eu-central-1_devpool"},{"OutputKey":"AuthUserPoolClientId8216BF9A","OutputValue":"devclient"}]'
    exit 0 ;;
  *"s3 sync"*) exit 0 ;;
  *"cloudfront create-invalidation"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"

  # npm stub: logs the invocation with NG_APP_* env for assertion, and
  # materialises the dist output the maintenance-copy + s3 sync steps rely on.
  cat >"$TEST_DIR/bin/npm" <<EOF
#!/bin/bash
{
  printf 'npm %s' "\$*"
  for v in NG_APP_API_ENDPOINT NG_APP_USER_POOL_ID NG_APP_USER_POOL_CLIENT_ID \\
           NG_APP_REGION NG_APP_ANONYMOUS_ACCESS NG_APP_INTERN; do
    printf ' %s=%q' "\$v" "\${!v-}"
  done
  printf '\n'
} >> "$NPM_LOG"
# Emulate ng build output.
mkdir -p dist/ng-digibro-frontend/browser
cat >dist/ng-digibro-frontend/browser/index.html <<'HTML'
<!doctype html><html><body><drv-root></drv-root><script src="runtime.js" type="module"></script><script src="main.js" type="module"></script></body></html>
HTML
printf 'console.log("deployed bundle");\n' >dist/ng-digibro-frontend/browser/main.js
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npm"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Argument + required-var guards ────────────────────────────────────────────

@test "[deploy-frontend] missing env arg → exit non-zero" {
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] unsupported env (demo) → exit non-zero" {
  run bash "$SCRIPT" demo
  [ "$status" -ne 0 ]
  [[ "$output" == *"unsupported env"* ]]
}

@test "[deploy-frontend] missing GITLAB_OIDC_TOKEN → exit non-zero" {
  unset GITLAB_OIDC_TOKEN
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] missing ROLE_ARN → exit non-zero" {
  unset ROLE_ARN
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] missing CI_JOB_ID → exit non-zero" {
  unset CI_JOB_ID
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] missing AWS_DEFAULT_REGION → exit non-zero" {
  unset AWS_DEFAULT_REGION
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

# ── OIDC / STS ────────────────────────────────────────────────────────────────

@test "[deploy-frontend] empty STS creds → exit 1" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then printf ''; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

# ── Stack name is parameterized per env ───────────────────────────────────────

@test "[deploy-frontend] dev → describe-stacks renate-chatbot-dev" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "cloudformation describe-stacks .*renate-chatbot-dev" "$AWS_LOG"
}

@test "[deploy-frontend] qa → describe-stacks renate-chatbot-qa" {
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  grep -q "cloudformation describe-stacks .*renate-chatbot-qa" "$AWS_LOG"
}

@test "[deploy-frontend] preprod → describe-stacks renate-chatbot-preprod" {
  run bash "$SCRIPT" preprod
  [ "$status" -eq 0 ]
  grep -q "cloudformation describe-stacks .*renate-chatbot-preprod" "$AWS_LOG"
}

@test "[deploy-frontend] prod → describe-stacks renate-chatbot-prod" {
  run bash "$SCRIPT" prod
  [ "$status" -eq 0 ]
  grep -q "cloudformation describe-stacks .*renate-chatbot-prod" "$AWS_LOG"
}

# ── Per-env npm build script (mirrors resolveBuildScript in CDK) ──────────────

@test "[deploy-frontend] dev → npm run build:dev" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "npm run build:dev" "$NPM_LOG"
}

@test "[deploy-frontend] qa → npm run build:qa" {
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  grep -q "npm run build:qa" "$NPM_LOG"
}

@test "[deploy-frontend] preprod → npm run build:prod" {
  run bash "$SCRIPT" preprod
  [ "$status" -eq 0 ]
  grep -q "npm run build:prod" "$NPM_LOG"
}

@test "[deploy-frontend] prod → npm run build:prod" {
  run bash "$SCRIPT" prod
  [ "$status" -eq 0 ]
  grep -q "npm run build:prod" "$NPM_LOG"
}

# ── NG_APP_* env plumbing ─────────────────────────────────────────────────────

@test "[deploy-frontend] NG_APP_API_ENDPOINT is empty (matches chatbot-stack.ts:285)" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  # Note: printf %q renders empty as ''.
  grep -qE "NG_APP_API_ENDPOINT=('')?( |$)" "$NPM_LOG"
}

@test "[deploy-frontend] NG_APP_USER_POOL_ID + client come from stack outputs" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "NG_APP_USER_POOL_ID=eu-central-1_devpool" "$NPM_LOG"
  grep -q "NG_APP_USER_POOL_CLIENT_ID=devclient" "$NPM_LOG"
}

@test "[deploy-frontend] NG_APP_REGION comes from AWS_DEFAULT_REGION" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "NG_APP_REGION=eu-central-1" "$NPM_LOG"
}

read_flag() {
  grep "^$1:" "deployments/$2/config.yaml" | awk '{print $2}'
}

@test "[deploy-frontend] dev config → NG_APP_* mirrors deployments/dev/config.yaml" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "NG_APP_ANONYMOUS_ACCESS=$(read_flag anonymousAccess dev)" "$NPM_LOG"
  grep -q "NG_APP_INTERN=$(read_flag intern dev)" "$NPM_LOG"
}

@test "[deploy-frontend] qa config → NG_APP_* mirrors deployments/qa/config.yaml" {
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  grep -q "NG_APP_ANONYMOUS_ACCESS=$(read_flag anonymousAccess qa)" "$NPM_LOG"
  grep -q "NG_APP_INTERN=$(read_flag intern qa)" "$NPM_LOG"
}

@test "[deploy-frontend] missing config.yaml → NG_APP_ANONYMOUS_ACCESS/INTERN default to false" {
  rm deployments/dev/config.yaml
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "NG_APP_ANONYMOUS_ACCESS=false" "$NPM_LOG"
  grep -q "NG_APP_INTERN=false" "$NPM_LOG"
}

# ── S3 sync goes to bucket root (not /review/<slug>/) ─────────────────────────

@test "[deploy-frontend] s3 sync targets bucket root with --delete" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -qE "s3 sync .*frontend/dist/ng-digibro-frontend/browser/ s3://renate-assets-dev-eu-central-1/ --delete" "$AWS_LOG"
}

# ── CloudFront invalidation covers /* ─────────────────────────────────────────

@test "[deploy-frontend] cloudfront create-invalidation --paths /*" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "cloudfront create-invalidation .*--distribution-id EDEV111DIST" "$AWS_LOG"
  # `/\*` because grep basic regex treats *; but literal string is fine here.
  grep -q "cloudfront create-invalidation .*--paths /\*" "$AWS_LOG"
}

# ── Maintenance-mode folder is copied into dist ───────────────────────────────

@test "[deploy-frontend] _maintenance/ folder is created inside dist" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ -f "frontend/dist/ng-digibro-frontend/browser/_maintenance/index.html" ]
}

# ── Full run + section wrappers ───────────────────────────────────────────────

@test "[deploy-frontend] happy path exits 0 and executes all steps in order" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q "assume-role-with-web-identity"      "$AWS_LOG"
  grep -q "cloudformation describe-stacks"     "$AWS_LOG"
  grep -q "npm run build:dev"                  "$NPM_LOG"
  grep -q "s3 sync"                            "$AWS_LOG"
  grep -q "cloudfront create-invalidation"     "$AWS_LOG"
  [[ "$output" == *"ng_build"* ]]
  [[ "$output" == *"s3_sync"* ]]
  [[ "$output" == *"FRONTEND DEPLOYED"* ]]
}

@test "[deploy-frontend] npm build failure → exit non-zero" {
  cat >"$TEST_DIR/bin/npm" <<'EOF'
#!/bin/bash
echo "build failed" >&2
exit 1
EOF
  chmod +x "$TEST_DIR/bin/npm"
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] s3 sync failure → exit non-zero" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '%s\n' '[{"OutputKey":"FrontendCloudFrontDistributionIdC60423D7","OutputValue":"EDEV111DIST"},{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"FrontendCloudFrontDistributionUrl650AAAFD","OutputValue":"https://cf/"},{"OutputKey":"AuthUserPoolIdC0605E59","OutputValue":"pool"},{"OutputKey":"AuthUserPoolClientId8216BF9A","OutputValue":"client"}]'
    exit 0 ;;
  *"s3 sync"*) echo "sync error" >&2; exit 1 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
}

@test "[deploy-frontend] emits deployed URL, EntryPoint fingerprint, and landing configuration to dotenv" {
  export DEPLOY_FRONTEND_DOTENV="$TEST_DIR/deploy-frontend.env"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ -f "$DEPLOY_FRONTEND_DOTENV" ]
  grep -q "^FRONTEND_DEPLOYED=true$" "$DEPLOY_FRONTEND_DOTENV"
  grep -q "^CF_URL=https://d11u7o0s8x8o66.cloudfront.net/$" "$DEPLOY_FRONTEND_DOTENV"
  grep -q "^FRONTEND_ENTRYPOINT_PATH=main.js$" "$DEPLOY_FRONTEND_DOTENV"
  expected_sha="$(sha256sum frontend/dist/ng-digibro-frontend/browser/main.js | awk '{print $1}')"
  grep -q "^FRONTEND_ENTRYPOINT_SHA256=${expected_sha}$" "$DEPLOY_FRONTEND_DOTENV"
  grep -q "^FRONTEND_ANONYMOUS_ACCESS=false$" "$DEPLOY_FRONTEND_DOTENV"
  [[ "$output" == *"EntryPoint SHA-256:"* ]]
}

@test "[deploy-frontend] missing main JavaScript EntryPoint fails closed" {
  cat >"$TEST_DIR/bin/npm" <<'EOF'
#!/bin/bash
mkdir -p dist/ng-digibro-frontend/browser
printf '<html><script src="runtime.js"></script></html>\n' \
  >dist/ng-digibro-frontend/browser/index.html
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npm"

  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"Could not find the main JavaScript EntryPoint"* ]]
}

@test "[deploy-frontend] empty distribution id in stack outputs → exit non-zero" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "aws \$*" >> "$AWS_LOG"
case "\$*" in
  *"assume-role-with-web-identity"*) printf 'k s t\n'; exit 0 ;;
  *"cloudformation describe-stacks"*)
    printf '%s\n' '[{"OutputKey":"FrontendFrontendS3BucketNameBBE87874","OutputValue":"renate-assets-dev-eu-central-1"},{"OutputKey":"AuthUserPoolIdC0605E59","OutputValue":"p"},{"OutputKey":"AuthUserPoolClientId8216BF9A","OutputValue":"c"}]'
    exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"FrontendCloudFrontDistributionId"* ]]
}
