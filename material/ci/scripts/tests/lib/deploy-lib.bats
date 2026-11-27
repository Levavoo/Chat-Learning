#!/usr/bin/env bats

LIB="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/lib/deploy.sh"
ETL_A="v1.48.0"
ETL_B="v1.49.0"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk"
  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"

  # Default jq stub (real jq may not be on PATH in minimal images)
  if ! command -v jq &>/dev/null; then
    cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
echo "true"
exit 0
EOF
    chmod +x "$TEST_DIR/bin/jq"
  fi
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── assume_deploy_role ────────────────────────────────────────────────────────

@test "[deploy-lib] assume_deploy_role: empty STS output → return 1" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
[[ "$*" == *"assume-role"* ]] && printf '' && exit 0
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && assume_deploy_role 'arn:aws:iam::123:role/test'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[deploy-lib] assume_deploy_role: partial creds (no session token) → return 1" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
[[ "$*" == *"assume-role"* ]] && printf 'AKID SECRETKEY\n' && exit 0
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && assume_deploy_role 'arn:aws:iam::123:role/test'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[deploy-lib] assume_deploy_role: valid creds → exports and calls get-caller-identity" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role"* ]]; then printf 'AKID SECRET TOKEN\n'; exit 0; fi
if [[ "\$*" == *"get-caller-identity"* ]]; then touch "$TEST_DIR/identity_called"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && assume_deploy_role 'arn:aws:iam::123:role/test'"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/identity_called" ]
}

@test "[deploy-lib] assume_deploy_role: missing GITLAB_OIDC_TOKEN → exit 1" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run env -u GITLAB_OIDC_TOKEN bash -c "source '$LIB' && assume_deploy_role 'arn:aws:iam::123:role/test'"
  [ "$status" -ne 0 ]
}

# ── ensure_ecr_image ──────────────────────────────────────────────────────────

@test "[deploy-lib] ensure_ecr_image: image not found → return 1 with error message" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
[[ "$*" == *"ecr describe-images"* ]] && echo "ImageNotFoundException" >&2 && exit 1
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && ensure_ecr_image '123456789012' 'renate-chat-lambda' '1.0.0'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not found"* ]]
}

@test "[deploy-lib] ensure_ecr_image: image exists → return 0" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
[[ "$*" == *"ecr describe-images"* ]] && exit 0
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && ensure_ecr_image '123456789012' 'renate-chat-lambda' '1.0.0'"
  [ "$status" -eq 0 ]
}

# ── assert_version_on_qa ──────────────────────────────────────────────────────
#
# Note: cases (b)+(c) below fall through the current-pin check into a `git
# ls-remote origin refs/tags/...` call. Tests stub `git` on PATH to control
# that lookup; without a stub, real git would try to reach origin and hang or
# fail unpredictably in the test sandbox.

_stub_git_no_tag() {
  # git stub that always reports "no tag on origin" (exit 2 = ls-remote --exit-code miss)
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then exit 2; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

_stub_git_with_tag() {
  # git stub that reports the tag exists on origin (exit 0)
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then
  printf 'deadbeef\trefs/tags/qa-deployed-1.40.0\n'
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

_stub_git_ls_remote_fail() {
  # git stub that simulates a network/auth failure to origin.
  # ls-remote exit 128 = "could not talk to remote" per git-ls-remote(1);
  # distinct from exit 2 which means "talked to remote, ref absent".
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then
  echo "fatal: unable to access 'https://origin/': Could not resolve host" >&2
  exit 128
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

@test "[deploy-lib] assert_version_on_qa: matches current qa pin → return 0" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/preprod" "$TEST_DIR/deployments/qa"
  echo "version: 1.51.1" >"$TEST_DIR/deployments/qa/version.yaml"
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.51.1' deployments/qa/version.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"matches current qa pin"* ]]
}

@test "[deploy-lib] assert_version_on_qa: version != current pin AND no qa-deployed tag → return 1" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/preprod" "$TEST_DIR/deployments/qa"
  echo "version: 1.51.1" >"$TEST_DIR/deployments/qa/version.yaml"
  _stub_git_no_tag
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.40.0' deployments/qa/version.yaml"
  [ "$status" -eq 1 ]
  [[ "$output" == *"never smoke-tested on qa"* ]]
  [[ "$output" == *"qa-deployed-1.40.0"* ]]
}

@test "[deploy-lib] assert_version_on_qa: version != current pin BUT qa-deployed tag exists → return 0" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/qa"
  echo "version: 1.51.1" >"$TEST_DIR/deployments/qa/version.yaml"
  _stub_git_with_tag
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.40.0' deployments/qa/version.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa-deployed tag qa-deployed-1.40.0 found"* ]]
}

@test "[deploy-lib] assert_version_on_qa: ls-remote network/auth failure → return 1 with distinct error (#560)" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/qa"
  echo "version: 1.51.1" >"$TEST_DIR/deployments/qa/version.yaml"
  _stub_git_ls_remote_fail
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.40.0' deployments/qa/version.yaml"
  [ "$status" -eq 1 ]
  # Must NOT falsely accuse the operator of promoting an un-smoke-tested version
  # when the real problem is that we couldn't reach origin.
  [[ "$output" != *"never smoke-tested on qa"* ]]
  [[ "$output" == *"could not reach origin"* ]]
  [[ "$output" == *"exit 128"* ]]
  [[ "$output" == *"retry"* ]]
}

@test "[deploy-lib] assert_version_on_qa: missing qa pin → return 1" {
  mkdir -p "$TEST_DIR/deployments"
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.51.1' deployments/qa/version.yaml"
  [ "$status" -eq 1 ]
  [[ "$output" == *"qa pin not found"* ]]
}

@test "[deploy-lib] assert_version_on_qa: exact match only (no 1.51.1 vs 1.51.10)" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/qa"
  echo "version: 1.51.10" >"$TEST_DIR/deployments/qa/version.yaml"
  _stub_git_no_tag
  # 1.51.1 must NOT match current pin 1.51.10 and no tag exists → refuse
  run bash -c "cd '$TEST_DIR' && source '$LIB' && assert_version_on_qa '1.51.1' deployments/qa/version.yaml"
  [ "$status" -eq 1 ]
}

# ── three-line promotion pins (#490) ─────────────────────────────────────────

@test "[deploy-lib] validate_promotion_pin: accepts exactly three version lines" {
  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: %s\n' \
    "$ETL_A" >"$TEST_DIR/pin.yaml"
  run bash -c "source '$LIB' && validate_promotion_pin '$TEST_DIR/pin.yaml'"
  [ "$status" -eq 0 ]
}

@test "[deploy-lib] validate_promotion_pin: accepts a composite data coordinate without a fourth field" {
  composite="v1.92.0-data.1"
  printf 'version: 1.109.0\ndata_artifact_version: %s\netl_version: %s\n' \
    "$composite" "$ETL_A" >"$TEST_DIR/pin.yaml"
  run bash -c "source '$LIB' && validate_promotion_pin '$TEST_DIR/pin.yaml'"
  [ "$status" -eq 0 ]
  [ "$(wc -l <"$TEST_DIR/pin.yaml" | tr -d ' ')" -eq 3 ]
}

@test "[deploy-lib] validate_promotion_pin: rejects missing or extra lines" {
  printf 'version: 1.51.1\n' >"$TEST_DIR/pin.yaml"
  run bash -c "source '$LIB' && validate_promotion_pin '$TEST_DIR/pin.yaml'"
  [ "$status" -eq 1 ]

  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: %s\nextra: nope\n' \
    "$ETL_A" >"$TEST_DIR/pin.yaml"
  run bash -c "source '$LIB' && validate_promotion_pin '$TEST_DIR/pin.yaml'"
  [ "$status" -eq 1 ]
}

@test "[deploy-lib] validate_promotion_pin: rejects legacy commit-SHA ETL versions" {
  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: git-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' \
    >"$TEST_DIR/pin.yaml"
  run bash -c "source '$LIB' && validate_promotion_pin '$TEST_DIR/pin.yaml'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"invalid etl_version"* ]]
}

@test "[deploy-lib] assert_pin_on_qa: data version is part of QA identity" {
  printf 'version: 1.51.1\ndata_artifact_version: v1.49.0\netl_version: %s\n' \
    "$ETL_A" >"$TEST_DIR/pin.yaml"
  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: %s\n' \
    "$ETL_A" >"$TEST_DIR/qa.yaml"
  _stub_git_no_tag
  run bash -c "source '$LIB' && assert_pin_on_qa '$TEST_DIR/pin.yaml' '$TEST_DIR/qa.yaml'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"1.51.1 + v1.49.0 + $ETL_A was never smoke-tested on qa"* ]]
}

@test "[deploy-lib] assert_pin_on_qa: ETL version is part of QA identity" {
  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: %s\n' \
    "$ETL_A" >"$TEST_DIR/pin.yaml"
  printf 'version: 1.51.1\ndata_artifact_version: v1.50.0\netl_version: %s\n' \
    "$ETL_B" >"$TEST_DIR/qa.yaml"
  _stub_git_no_tag
  run bash -c "source '$LIB' && assert_pin_on_qa '$TEST_DIR/pin.yaml' '$TEST_DIR/qa.yaml'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"1.51.1 + v1.50.0 + $ETL_A was never smoke-tested on qa"* ]]
}

# ── promote_image_tag_ssm ─────────────────────────────────────────────────────

@test "[deploy-lib] promote_image_tag_ssm: unknown env → return 1" {
  run bash -c "source '$LIB' && promote_image_tag_ssm 'staging' '1.0.0'"
  [ "$status" -eq 1 ]
}

@test "[deploy-lib] promote_image_tag_ssm: saves previous and writes current" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"ssm get-parameter"* ]]; then printf '0.9.0\n'; exit 0; fi
if [[ "\$*" == *"ssm put-parameter"* && "\$*" == *"image-tag-previous"* ]]; then
  touch "$TEST_DIR/ssm_prev_written"; exit 0; fi
if [[ "\$*" == *"ssm put-parameter"* && "\$*" == *"image-tag "* ]]; then
  touch "$TEST_DIR/ssm_cur_written"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && promote_image_tag_ssm 'preprod' '1.0.0'"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/ssm_prev_written" ]
  [ -f "$TEST_DIR/ssm_cur_written" ]
}

@test "[deploy-lib] promote_image_tag_ssm: no existing tag → skips previous, writes current" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"ssm get-parameter"* ]]; then exit 1; fi
if [[ "\$*" == *"ssm put-parameter"* ]]; then touch "$TEST_DIR/ssm_written"; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash -c "source '$LIB' && promote_image_tag_ssm 'qa' '1.0.0'"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/ssm_written" ]
  [ ! -f "$TEST_DIR/ssm_prev_written" ]
}

# ── cdk_deploy_stack ──────────────────────────────────────────────────────────

@test "[deploy-lib] cdk_deploy_stack: npx succeeds and writes outputs" {
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
echo '{"renate-chatbot-preprod":{"ApiUrl":"https://x.com/"}}' > "$TEST_DIR/outputs.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
  # provide real jq for the JSON validation
  run bash -c "cd '$TEST_DIR' && source '$LIB' && cdk_deploy_stack 'renate-chatbot-preprod' 'preprod' '$TEST_DIR/outputs.json'"
  [ "$status" -eq 0 ]
  grep -q "renate-chatbot-preprod" "$TEST_DIR/npx_args"
  grep -q "env=preprod" "$TEST_DIR/npx_args"
}

@test "[deploy-lib] cdk_deploy_stack: missing outputs → fallback get-stack-outputs.sh called" {
  # npx succeeds but writes no outputs file
  cat >"$TEST_DIR/bin/npx" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
  # Provide a fake get-stack-outputs.sh that the lib can call
  mkdir -p "$TEST_DIR/scripts"
  cat >"$TEST_DIR/scripts/get-stack-outputs.sh" <<EOF
#!/bin/bash
echo '{"renate-chatbot-preprod":{}}' > "\$2"
touch "$TEST_DIR/fallback_called"
EOF
  chmod +x "$TEST_DIR/scripts/get-stack-outputs.sh"
  # Point the lib to the fake fallback by symlinking the scripts dir layout
  mkdir -p "$TEST_DIR/lib"
  cat >"$TEST_DIR/lib/deploy_test.sh" <<EOF
#!/usr/bin/env bash
source '$LIB'
# Override fallback path for test
cdk_deploy_stack() {
  local stack="\$1" env="\$2" outputs_file="\$3"
  rm -f "\$outputs_file"
  (cd cdk && npx cdk deploy "\$stack" --context "env=\${env}" --require-approval never --outputs-file "\$outputs_file") || true
  if [[ ! -f "\$outputs_file" ]]; then
    bash "$TEST_DIR/scripts/get-stack-outputs.sh" "\$stack" "\$outputs_file"
  fi
}
cdk_deploy_stack 'renate-chatbot-preprod' 'preprod' '$TEST_DIR/outputs.json'
EOF
  run bash "$TEST_DIR/lib/deploy_test.sh"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/fallback_called" ]
}

# ── cdk_deploy_stack: extra --context passthrough (#590) ─────────────────────

@test "[deploy-lib] cdk_deploy_stack: no extra context → only env context passed" {
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$TEST_DIR/outputs.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
  run bash -c "cd '$TEST_DIR' && source '$LIB' && cdk_deploy_stack 'renate-etl-kb-dev' 'dev' '$TEST_DIR/outputs.json'"
  [ "$status" -eq 0 ]
  grep -q "env=dev" "$TEST_DIR/npx_args"
  ! grep -q "etlImageTag" "$TEST_DIR/npx_args"
}

@test "[deploy-lib] cdk_deploy_stack: extra context arg is passed as an additional --context flag" {
  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$TEST_DIR/outputs.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"
  run bash -c "cd '$TEST_DIR' && source '$LIB' && cdk_deploy_stack 'renate-etl-kb-dev' 'dev' '$TEST_DIR/outputs.json' 'etlImageTag=v1.23.0'"
  [ "$status" -eq 0 ]
  grep -q "env=dev" "$TEST_DIR/npx_args"
  grep -q -- "--context etlImageTag=v1.23.0" "$TEST_DIR/npx_args"
}
