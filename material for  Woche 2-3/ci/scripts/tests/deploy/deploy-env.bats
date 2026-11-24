#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-env.sh"
REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../.." && pwd)"
ETL_A="v1.38.0"
ETL_B="v1.49.0"

_write_pin() {
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$2" "$3" "$4" >"$1"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk" "$TEST_DIR/deployments" "$TEST_DIR/deployments/dev" "$TEST_DIR/deployments/preprod" "$TEST_DIR/deployments/qa"
  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/ki-lab-digibro-preprod-cdk-deploy"
  export CDK_DEPLOY_ROLE_ARN_QA="arn:aws:iam::571600837515:role/ki-lab-digibro-qa-cdk-deploy"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::831926590742:role/ki-lab-digibro-dev-cdk-deploy"
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"

  _aws_stub "AKID SECRET TOKEN"
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$REPO_ROOT/outputs.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"

  # Default: no qa-deployed tag on origin. Prevents assert_version_on_qa from
  # reaching the real origin during the ls-remote fallthrough. Override in
  # individual tests when a tag hit is required (see #560).
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then exit 2; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

teardown() {
  rm -rf "$TEST_DIR"
  rm -f "$REPO_ROOT/outputs.json"
}

_aws_stub() {
  local sts_output="$1"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role"* ]]; then printf '%s\n' "$sts_output"; exit 0; fi
if [[ "\$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "\$*" == *"ecr describe-images"* ]]; then exit 0; fi
if [[ "\$*" == *"ssm get-parameter"* ]]; then exit 1; fi
if [[ "\$*" == *"ssm put-parameter"* ]]; then exit 0; fi
if [[ "\$*" == *"cloudformation describe-stacks"* ]]; then
  printf '[{"OutputKey":"ApiUrl","OutputValue":"https://test.example.com/"}]\n'; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

# ── validation ────────────────────────────────────────────────────────────────

@test "[deploy-env] no argument → exit 1 (unknown env)" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
}

@test "[deploy-env] unknown env → exit 1" {
  run bash "$SCRIPT" staging
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown env"* ]]
}

@test "[deploy-env] role var unset → exit 1 with var name in message" {
  unset CDK_DEPLOY_ROLE_ARN_DEV
  _write_pin "$TEST_DIR/deployments/dev/version.yaml" "1.99.0" "v1.50.0" "$ETL_A"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CDK_DEPLOY_ROLE_ARN_DEV"* ]]
}

@test "[deploy-env] missing pin file → exit 1" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Pin file not found"* ]]
}

# ── preprod (#641 dedicated foundation operation only) ───────────────────────

@test "[deploy-env] preprod: refuses the obsolete standalone deployment path" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Direct preprod deployment is disabled"* ]]
  [[ "$output" == *"preprod-retrieval-promotion"* ]]
  [ ! -e "$TEST_DIR/npx_args" ]
}

# ── qa (#492 owns the complete transaction) ──────────────────────────────────

@test "[deploy-env] qa: refuses the obsolete standalone deployment path" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Direct QA deployment is disabled by #492"* ]]
  [ ! -e "$TEST_DIR/npx_args" ]
}

# ── dev ───────────────────────────────────────────────────────────────────────

@test "[deploy-env] dev: reads version from pin file, skips ECR/SSM (build-lambda owns those)" {
  _write_pin "$TEST_DIR/deployments/dev/version.yaml" "1.99.0" "v1.50.0" "$ETL_A"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "\$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "\$*" == *"ecr describe-images"* ]]; then touch "$TEST_DIR/ecr_called"; exit 0; fi
if [[ "\$*" == *"ssm put-parameter"* ]]; then touch "$TEST_DIR/ssm_called"; exit 0; fi
if [[ "\$*" == *"cloudformation"* ]]; then
  printf '[{"OutputKey":"ApiUrl","OutputValue":"https://x.com/"}]\n'; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "cd '$TEST_DIR' && REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 0 ]
  grep -q "renate-chatbot-dev" "$TEST_DIR/npx_args"
  grep -q "env=dev" "$TEST_DIR/npx_args"
  # dev must NOT call ECR DescribeImages or write SSM (role lacks permission)
  [ ! -f "$TEST_DIR/ecr_called" ]
  [ ! -f "$TEST_DIR/ssm_called" ]
}

@test "[deploy-env] dev: missing pin file → exit 1" {
  run bash -c "cd '$TEST_DIR' && REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 1 ]
}

# ── deploy-version.env (consumed by the render-deployment-page step) ──────────
# deploy-env.sh runs as its own process, so exports don't survive past it; it
# writes the resolved version to a file the caller sources instead. TKT-DDP-04:
# qa/preprod must not fall back to cocogitto's NEW_TAG (empty on promotion-only
# pipelines), so this must reflect the *pin file*, matching what was deployed.

@test "[deploy-env] dev: deploy-version.env holds pin file version" {
  _write_pin "$TEST_DIR/deployments/dev/version.yaml" "1.99.0" "v1.50.0" "$ETL_A"
  run bash -c "cd '$TEST_DIR' && REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 0 ]
  grep -qx "DEPLOY_VERSION=1.99.0" "$TEST_DIR/deploy-version.env"
}

# ── STS failure (shared path) ─────────────────────────────────────────────────

@test "[deploy-env] STS failure → exit 1 with error message" {
  _write_pin "$TEST_DIR/deployments/dev/version.yaml" "1.99.0" "v1.50.0" "$ETL_A"
  _aws_stub ""
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' dev"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}
