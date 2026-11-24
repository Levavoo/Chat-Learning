#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/open-qa-mr.sh"
ETL_A="v0.8.0"
ETL_B="v1.0.1"

_write_pin() {
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$2" "$3" "$4" >"$1"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments/qa" "$TEST_DIR/bin"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.0.0" "v0.9.0" "$ETL_A"

  export PATH="$TEST_DIR/bin:$PATH"
  export CI_SERVER_HOST="gitlab.test"
  export CI_JOB_TOKEN="test-token"
  export CI_PROJECT_PATH="group/project"
  export CI_API_V4_URL="https://gitlab.test/api/v4"
  export CI_PROJECT_ID="123"
  export CI_DEFAULT_BRANCH="test-default"
  export CI_COMMIT_SHA="deadbeef"
  export NEW_TAG="1.2.3"
  export DATA_ARTIFACT_VERSION="v1.1.0"
  export ETL_VERSION="$ETL_B"
  export GL_TOKEN="test-token"

  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"

  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
if [[ "$*" == *"-X POST"* ]]; then echo '{"id":1}'; exit 0; fi
echo '[]'
EOF
  chmod +x "$TEST_DIR/bin/curl"

  cat >"$TEST_DIR/bin/node" <<'EOF'
#!/bin/bash
if [ "$1" = "-e" ] && [[ "$2" == *"JSON.parse"* ]]; then
  json="$3"
  if [ "$json" = "[]" ]; then echo 0; exit 0; fi
  if [[ "$2" == *".length"* ]]; then echo 1; exit 0; fi
  if [[ "$2" == *".iid"* ]];    then echo 1; exit 0; fi
  if [[ "$2" == *".title"* ]];  then echo "QA Promotion auf ${NEW_TAG}"; exit 0; fi
  echo 1; exit 0
fi
exit 1
EOF
  chmod +x "$TEST_DIR/bin/node"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_run() {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
}

@test "[open-qa-mr] BUMPED unset → exit 0, no git called" {
  unset BUMPED
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
echo "FAIL: git called with BUMPED unset" >&2; exit 1
EOF
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping QA promotion"* ]]
}

@test "[open-qa-mr] BUMPED=false → exit 0, no git called" {
  export BUMPED=false
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
echo "FAIL: git called with BUMPED=false" >&2; exit 1
EOF
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping QA promotion"* ]]
}

@test "[open-qa-mr] missing data artifact version fails closed" {
  export BUMPED=true
  unset DATA_ARTIFACT_VERSION
  _run
  [ "$status" -ne 0 ]
  [[ "$output" == *"DATA_ARTIFACT_VERSION is required"* ]]
}

@test "[open-qa-mr] missing ETL version fails closed" {
  export BUMPED=true
  unset ETL_VERSION
  _run
  [ "$status" -ne 0 ]
  [[ "$output" == *"ETL_VERSION is required"* ]]
}

@test "[open-qa-mr] idempotent: QA_VERSION==NEW_TAG → exit 0, no git called" {
  export BUMPED=true
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.2.3" "v1.1.0" "$ETL_B"
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
echo "FAIL: git called when already at version" >&2; exit 1
EOF
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing to do"* ]]
}

@test "[open-qa-mr] same chatbot version with different data still updates the pin" {
  export BUMPED=true
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.2.3" "v1.0.0" "$ETL_B"
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
if [[ "\$*" == *"commit"* ]]; then touch "$TEST_DIR/commit_called"; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/commit_called" ]
  grep -qx 'data_artifact_version: v1.1.0' "$TEST_DIR/deployments/qa/version.yaml"
}

@test "[open-qa-mr] accepts the composite brochure+FAQ data coordinate" {
  export BUMPED=true
  export DATA_ARTIFACT_VERSION="v1.92.0-data.1"
  _run
  [ "$status" -eq 0 ]
  grep -qx "data_artifact_version: $DATA_ARTIFACT_VERSION" \
    "$TEST_DIR/deployments/qa/version.yaml"
  [ "$(wc -l <"$TEST_DIR/deployments/qa/version.yaml" | tr -d ' ')" -eq 3 ]
}

@test "[open-qa-mr] promotion commit message has no [skip ci]" {
  export BUMPED=true
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
if [[ "\$*" == *"commit"* ]]; then
  echo "\$*" > "$TEST_DIR/git_commit_args"
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/git_commit_args" ]
  [[ "$(cat "$TEST_DIR/git_commit_args")" == *"chore(deploy): QA Promotion auf"* ]]
  [[ "$(cat "$TEST_DIR/git_commit_args")" != *"[skip ci]"* ]]
  [ "$(wc -l <"$TEST_DIR/deployments/qa/version.yaml" | tr -d ' ')" -eq 3 ]
  grep -qx 'version: 1.2.3' "$TEST_DIR/deployments/qa/version.yaml"
  grep -qx 'data_artifact_version: v1.1.0' "$TEST_DIR/deployments/qa/version.yaml"
  grep -qx "etl_version: $ETL_B" "$TEST_DIR/deployments/qa/version.yaml"
}

@test "[open-qa-mr] open MR exists → updates title and description, skips POST" {
  export BUMPED=true
  export NEW_TAG="1.2.3"
  export QA_VERSION="1.2.2"
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
# FAIL if POST is called
if [[ "$*" == *"-X POST"* ]]; then
  echo "FAIL: curl POST called when MR already open" >&2; exit 1
fi
# Handle PUT update — library sends JSON --data payload
if [[ "$*" == *"-X PUT"* ]]; then
  # Collect --data argument
  body=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--data" ]]; then body="$2"; fi
    shift
  done
  [[ "$body" == *"1.2.3"* ]] || { echo "FAIL: version not in body: $body" >&2; exit 1; }
  echo '{}'
  exit 0
fi
# Handle GET (list open MRs) — return one existing MR
echo '[{"id":10,"iid":5}]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  # also need jq for the library
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
if [[ "$*" == *"length"* ]] || [[ "${@: -1}" == *"length"* ]]; then
  input=$(cat); [[ "$input" == "[]" ]] && echo 0 || echo 1; exit 0; fi
if [[ "$*" == *".[0].iid"* ]] || [[ "$*" == *".iid"* ]]; then echo 5; exit 0; fi
if [[ "$*" == *"-n"* ]]; then
  # Return JSON with the args visible so tests can check content
  for a in "$@"; do
    if [[ "$a" == *"1.2.3"* ]]; then printf '{"title":"QA Promotion auf 1.2.3","description":"x"}'; exit 0; fi
  done
  echo '{"ok":true}'; exit 0; fi
echo '1'
EOF
  chmod +x "$TEST_DIR/bin/jq"
  _run
  [ "$status" -eq 0 ]
}

@test "[open-qa-mr] no open MR → curl POST called with version in description" {
  export BUMPED=true
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then
  touch "$TEST_DIR/post_called"
  echo "\$*" > "$TEST_DIR/post_body"
  echo '{"id":2}'
  exit 0
fi
echo '[]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/post_called" ]
  [[ "$output" == *"Created MR"* ]]
  [[ "$(cat "$TEST_DIR/post_body")" == *"1.2.3"* ]]
  [[ "$(cat "$TEST_DIR/post_body")" == *"Automatisierte"* ]]
}

@test "[open-qa-mr] git push failure → exit non-zero" {
  export BUMPED=true
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$*" == *"push"* ]]; then
  echo "error: failed to push some refs" >&2; exit 1
fi
exit 0
EOF
  _run
  [ "$status" -ne 0 ]
}

@test "[open-qa-mr] SMOKE_TEST=true → creates MR, closes MR and deletes branch on exit" {
  export BUMPED=true
  export NEW_TAG="99.99.99-test"
  export SMOKE_TEST=true
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then echo '{"id":2,"iid":1}'; exit 0; fi
if [[ "\$*" == *"-X PUT"* ]]; then touch "$TEST_DIR/mr_closed"; exit 0; fi
echo '[]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
if [[ "\$*" == *"--delete"* ]]; then touch "$TEST_DIR/branch_deleted"; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]]
  [ -f "$TEST_DIR/mr_closed" ]
  [ -f "$TEST_DIR/branch_deleted" ]
}

@test "[open-qa-mr] branch is created from origin/\$CI_DEFAULT_BRANCH, not CI_COMMIT_SHA" {
  export BUMPED=true
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
echo "\$*" >> "$TEST_DIR/git_calls"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  grep -q "fetch --depth=1 origin test-default" "$TEST_DIR/git_calls"
  grep -qE "checkout -B .+ origin/test-default" "$TEST_DIR/git_calls"
  ! grep -qE "checkout -B .+ deadbeef" "$TEST_DIR/git_calls"
}

@test "[open-qa-mr] curl MR list failure → exit non-zero" {
  export BUMPED=true
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
echo "curl: (6) Could not resolve host" >&2; exit 6
EOF
  _run
  [ "$status" -ne 0 ]
}

# ── DEV_PIN_FILE path (#634) ──────────────────────────────────────────────────

@test "[open-qa-mr] DEV_PIN_FILE: reads version coords from pin file" {
  export BUMPED=true
  export DEV_PIN_FILE="deployments/dev/version.yaml"
  unset NEW_TAG DATA_ARTIFACT_VERSION ETL_VERSION
  mkdir -p "$TEST_DIR/deployments/dev"
  printf 'version: 2.0.0\ndata_artifact_version: v2.0.0\netl_version: v2.0.0\nmaintenance: false\n' \
    >"$TEST_DIR/deployments/dev/version.yaml"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"2.0.0"* ]]
}

@test "[open-qa-mr] DEV_PIN_FILE: missing pin file → exit 1" {
  export BUMPED=true
  export DEV_PIN_FILE="deployments/dev/version.yaml"
  unset NEW_TAG DATA_ARTIFACT_VERSION ETL_VERSION
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"DEV_PIN_FILE not found"* ]]
}

@test "[open-qa-mr] DEV_PIN_FILE: already at same version → skips MR" {
  export BUMPED=true
  export DEV_PIN_FILE="deployments/dev/version.yaml"
  unset NEW_TAG DATA_ARTIFACT_VERSION ETL_VERSION
  mkdir -p "$TEST_DIR/deployments/dev"
  # Pin matches current QA pin (1.0.0 / v0.9.0 / ETL_A set in setup)
  printf 'version: 1.0.0\ndata_artifact_version: v0.9.0\netl_version: %s\nmaintenance: false\n' \
    "$ETL_A" >"$TEST_DIR/deployments/dev/version.yaml"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"already at"* ]]
}
