#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/push-maintenance-rehearsed-tag.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments/qa"
  export PATH="$TEST_DIR/bin:$PATH"
  export CI_SERVER_HOST="gitlab.example.com"
  export CI_PROJECT_PATH="renate/digibro-monorepo"
  export CI_JOB_TOKEN="test-token"
  export CI_PIPELINE_ID="4242"
  echo "version: 1.90.0" >"$TEST_DIR/deployments/qa/version.yaml"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_stub_git() {
  # Args: <ls-remote-exit-code> [<capture-file>]
  # ls-remote exit 0 = tag exists, exit 2 = tag missing.
  local ls_exit="$1"
  local capture_file="${2:-}"
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
${capture_file:+echo "\$@" >> "$capture_file"}
if [[ "\$1" == "ls-remote" ]]; then exit $ls_exit; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

@test "[push-maintenance-rehearsed-tag] missing CI_SERVER_HOST → exit 1" {
  unset CI_SERVER_HOST
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CI_SERVER_HOST"* ]]
}

@test "[push-maintenance-rehearsed-tag] missing CI_JOB_TOKEN → exit 1" {
  unset CI_JOB_TOKEN
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CI_JOB_TOKEN"* ]]
}

@test "[push-maintenance-rehearsed-tag] missing CI_PIPELINE_ID → exit 1" {
  unset CI_PIPELINE_ID
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CI_PIPELINE_ID"* ]]
}

@test "[push-maintenance-rehearsed-tag] missing qa pin → exit 1" {
  rm "$TEST_DIR/deployments/qa/version.yaml"
  _stub_git 2
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"qa pin not found"* ]]
}

@test "[push-maintenance-rehearsed-tag] tag already exists on origin → skip (exit 0, no push)" {
  local capture="$TEST_DIR/git-calls"
  _stub_git 0 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"already exists on origin — skipping"* ]]
  ! grep -q '^tag ' "$capture" || return 1
  ! grep -q '^push ' "$capture" || return 1
}

@test "[push-maintenance-rehearsed-tag] tag missing → create and push, then exit 0" {
  local capture="$TEST_DIR/git-calls"
  _stub_git 2 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Pushing tag maintenance-rehearsed-qa-1.90.0-4242"* ]]
  [[ "$output" == *"Tag maintenance-rehearsed-qa-1.90.0-4242 pushed"* ]]
  grep -qE '^tag maintenance-rehearsed-qa-1\.90\.0-4242$' "$capture"
  grep -q 'push .* refs/tags/maintenance-rehearsed-qa-1.90.0-4242' "$capture"
}

@test "[push-maintenance-rehearsed-tag] tag name derived from qa pin version and CI_PIPELINE_ID" {
  echo "version: 2.0.0-rc1" >"$TEST_DIR/deployments/qa/version.yaml"
  export CI_PIPELINE_ID="777"
  local capture="$TEST_DIR/git-calls"
  _stub_git 2 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q 'maintenance-rehearsed-qa-2.0.0-rc1-777' "$capture"
}
