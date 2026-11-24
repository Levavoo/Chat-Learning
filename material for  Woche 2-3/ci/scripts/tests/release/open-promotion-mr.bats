#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/open-promotion-mr.sh"
ETL_A="v1.47.0"
ETL_B="v1.49.0"

_write_pin() {
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$2" "$3" "$4" >"$1"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/preprod" \
    "$TEST_DIR/deployments/prod" "$TEST_DIR/deployments/qa" "$TEST_DIR/bin"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.49.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.50.0" "v1.48.0" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/prod/version.yaml" "1.50.0" "v1.48.0" "$ETL_A"
  # Note: tests that need already-at-version overwrite preprod.yaml inline.

  export PATH="$TEST_DIR/bin:$PATH"
  export CI_SERVER_HOST="gitlab.test"
  export CI_JOB_TOKEN="test-token"
  export CI_PROJECT_PATH="group/project"
  export CI_API_V4_URL="https://gitlab.test/api/v4"
  export CI_PROJECT_ID="123"
  export CI_DEFAULT_BRANCH="test-default"
  export GL_TOKEN="test-token"

  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"

  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/bin/bash
if [[ "$*" == *"-X POST"* ]]; then echo '{"id":1,"iid":7}'; exit 0; fi
echo '[]'
EOF
  chmod +x "$TEST_DIR/bin/curl"

  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
# Minimal jq stub: handle the specific patterns used in promote-mr.sh
if [[ "$*" == *"length"* ]] || [[ "${@: -1}" == *"length"* ]]; then
  input=$(cat)
  if [[ "$input" == "[]" ]]; then echo 0; else echo 1; fi
  exit 0
fi
if [[ "$*" == *".[0].iid"* ]] || [[ "$*" == *".iid"* ]]; then
  echo 7; exit 0
fi
# jq -n for payload construction — return minimal JSON
if [[ "$*" == *"-n"* ]]; then echo '{"ok":true}'; exit 0; fi
echo '1'
EOF
  chmod +x "$TEST_DIR/bin/jq"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_run() {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa preprod"
}

_run_prod() {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa prod"
}

# ── argument validation ───────────────────────────────────────────────────────

@test "[open-promotion-mr] no args → exit 1 with usage message" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "[open-promotion-mr] missing from pin file → exit 1" {
  run bash -c "cd '$TEST_DIR' && bash '$SCRIPT' staging preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Source pin file not found"* ]]
}

@test "[open-promotion-mr] missing to pin file → exit 1" {
  run bash -c "cd '$TEST_DIR' && bash '$SCRIPT' qa demo"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Target pin file not found"* ]]
}

# ── idempotency ───────────────────────────────────────────────────────────────

@test "[open-promotion-mr] already at version → exit 0, no git called" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.49.0" "$ETL_B"
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
echo "FAIL: git called when already at version" >&2; exit 1
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing to do"* ]]
}

@test "[open-promotion-mr] same chatbot version with different data creates a promotion" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.48.0" "$ETL_B"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]]
  grep -qx 'data_artifact_version: v1.49.0' \
    "$TEST_DIR/deployments/preprod/version.yaml"
}

@test "[open-promotion-mr] same chatbot and data with different ETL creates a promotion" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.49.0" "$ETL_A"
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]]
  grep -qx "etl_version: $ETL_B" "$TEST_DIR/deployments/preprod/version.yaml"
}

# ── MR creation ───────────────────────────────────────────────────────────────

@test "[open-promotion-mr] new version → creates MR with version in title" {
  _run
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]]
  [[ "$output" == *"1.51.1"* ]]
  [ "$(wc -l <"$TEST_DIR/deployments/preprod/version.yaml" | tr -d ' ')" -eq 3 ]
  grep -qx 'data_artifact_version: v1.49.0' "$TEST_DIR/deployments/preprod/version.yaml"
  grep -qx "etl_version: $ETL_B" "$TEST_DIR/deployments/preprod/version.yaml"
}

@test "[#670 open-promotion-mr] qa → prod creates the prod pin MR" {
  _run_prod
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]]
  grep -qx 'version: 1.51.1' "$TEST_DIR/deployments/prod/version.yaml"
  grep -qx 'data_artifact_version: v1.49.0' \
    "$TEST_DIR/deployments/prod/version.yaml"
  grep -qx "etl_version: $ETL_B" "$TEST_DIR/deployments/prod/version.yaml"
}

@test "[open-promotion-mr] MR description from-version is target's current pin (1.50.0 → 1.51.1)" {
  # jq stub that echoes all --arg values into the payload so the POST body
  # carries both the from (target current) and to (new) versions.
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
if [[ "$*" == *"length"* ]] || [[ "${@: -1}" == *"length"* ]]; then
  input=$(cat); [[ "$input" == "[]" ]] && echo 0 || echo 1; exit 0; fi
if [[ "$*" == *".iid"* ]] || [[ "$*" == *".[0].iid"* ]]; then echo 7; exit 0; fi
if [[ "$*" == *"-n"* ]]; then
  out=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--arg" ]]; then out="${out} ${3}"; shift 3; continue; fi
    shift
  done
  printf '{"x":"%s"}' "$out"; exit 0; fi
echo '1'
EOF
  chmod +x "$TEST_DIR/bin/jq"
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then
  body=""
  while [[ \$# -gt 0 ]]; do [[ "\$1" == "--data" ]] && body="\$2"; shift; done
  echo "\$body" > "$TEST_DIR/post_body"
  echo '{"id":1,"iid":7}'; exit 0; fi
echo '[]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/post_body" ]
  # from = preprod's current pin (1.50.0), to = new (1.51.1)
  [[ "$(cat "$TEST_DIR/post_body")" == *"1.50.0"* ]]
  [[ "$(cat "$TEST_DIR/post_body")" == *"1.51.1"* ]]
  # MR title is conventional so the squash-merge commit lands cleanly for cocogitto
  [[ "$(cat "$TEST_DIR/post_body")" == *"chore(deploy):"* ]]
  [[ "$(cat "$TEST_DIR/post_body")" == *"PREPROD Promotion auf 1.51.1"* ]]
}

@test "[open-promotion-mr] commit message contains to-env and version" {
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
if [[ "\$*" == *"commit"* ]]; then echo "\$*" > "$TEST_DIR/git_commit_args"; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/git_commit_args" ]
  [[ "$(cat "$TEST_DIR/git_commit_args")" == *"PREPROD"* ]] || \
  [[ "$(cat "$TEST_DIR/git_commit_args")" == *"preprod"* ]]
  [[ "$(cat "$TEST_DIR/git_commit_args")" == *"1.51.1"* ]]
}

@test "[open-promotion-mr] promo branch is chore/preprod-promotion" {
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
echo "\$*" >> "$TEST_DIR/git_calls"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -eq 0 ]
  grep -q "chore/preprod-promotion" "$TEST_DIR/git_calls"
}

@test "[open-promotion-mr] checks out from origin/\$CI_DEFAULT_BRANCH not HEAD" {
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
}

# ── MR update (existing open MR) ─────────────────────────────────────────────

@test "[open-promotion-mr] existing open MR → PUT update, no POST" {
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then
  echo "FAIL: POST called when MR exists" >&2; exit 1; fi
if [[ "\$*" == *"-X PUT"* ]]; then touch "$TEST_DIR/put_called"; echo '{}'; exit 0; fi
echo '[{"id":5,"iid":3}]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
if [[ "$*" == *"length"* ]] || [[ "${@: -1}" == *"length"* ]]; then echo 1; exit 0; fi
if [[ "$*" == *".iid"* ]] || [[ "$*" == *".[0].iid"* ]]; then echo 3; exit 0; fi
if [[ "$*" == *"-n"* ]]; then echo '{"ok":true}'; exit 0; fi
echo '1'
EOF
  chmod +x "$TEST_DIR/bin/jq"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/put_called" ]
  [[ "$output" == *"Updated MR"* ]]
}

@test "[open-promotion-mr] existing open MR → PUT body carries conventional title" {
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then
  echo "FAIL: POST called when MR exists" >&2; exit 1; fi
if [[ "\$*" == *"-X PUT"* ]]; then
  body=""
  while [[ \$# -gt 0 ]]; do [[ "\$1" == "--data" ]] && body="\$2"; shift; done
  echo "\$body" > "$TEST_DIR/put_body"
  echo '{}'; exit 0; fi
echo '[{"id":5,"iid":3}]'
EOF
  chmod +x "$TEST_DIR/bin/curl"
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/bin/bash
if [[ "$*" == *"length"* ]] || [[ "${@: -1}" == *"length"* ]]; then echo 1; exit 0; fi
if [[ "$*" == *".iid"* ]] || [[ "$*" == *".[0].iid"* ]]; then echo 3; exit 0; fi
if [[ "$*" == *"-n"* ]]; then
  out=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--arg" ]]; then out="${out} ${3}"; shift 3; continue; fi
    shift
  done
  printf '{"x":"%s"}' "$out"; exit 0; fi
echo '1'
EOF
  chmod +x "$TEST_DIR/bin/jq"
  _run
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/put_body" ]
  [[ "$(cat "$TEST_DIR/put_body")" == *"chore(deploy):"* ]]
  [[ "$(cat "$TEST_DIR/put_body")" == *"PREPROD Promotion auf 1.51.1"* ]]
}

# ── SMOKE_TEST cleanup ────────────────────────────────────────────────────────

@test "[open-promotion-mr] SMOKE_TEST=true → MR closed and branch deleted on exit" {
  export SMOKE_TEST=true
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
if [[ "\$*" == *"-X POST"* ]]; then echo '{"id":2,"iid":9}'; exit 0; fi
if [[ "\$*" == *"-X PUT"* ]]; then touch "$TEST_DIR/mr_closed"; echo '{}'; exit 0; fi
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
  [ -f "$TEST_DIR/mr_closed" ]
  [ -f "$TEST_DIR/branch_deleted" ]
}

# ── git push failure ──────────────────────────────────────────────────────────

@test "[open-promotion-mr] git push failure → exit non-zero" {
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$*" == *"push"* ]]; then
  echo "error: failed to push some refs" >&2; exit 1; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  _run
  [ "$status" -ne 0 ]
}

# ── different env pair (regression check) ────────────────────────────────────

@test "[open-promotion-mr] dev→qa pair also works" {
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/preprod"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "2.0.0" "v1.8.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.9.0" "v1.7.0" "$ETL_A"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created MR"* ]] || [[ "$output" == *"Updated MR"* ]]
}
