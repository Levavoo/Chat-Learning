#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/push-qa-deployed-tag.sh"
ETL_A="v1.79.0"
ETL_B="v1.98.0"

_write_pin() {
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$2" "$3" "$4" >"$1"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments/qa"
  export PATH="$TEST_DIR/bin:$PATH"
  export CI_SERVER_HOST="gitlab.example.com"
  export CI_PROJECT_PATH="renate/digibro-monorepo"
  export CI_JOB_TOKEN="test-token"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.81.0" "v1.80.0" "$ETL_A"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_stub_git() {
  # Args: <ls-remote-exit-code> [<capture-file>]
  # ls-remote exit 0 = tag exists, exit 2 = tag missing.
  # Optional capture-file: writes each git invocation's args (one line per call)
  # so tests can assert what was pushed.
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

@test "[push-qa-deployed-tag] missing CI_SERVER_HOST → exit 1" {
  unset CI_SERVER_HOST
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CI_SERVER_HOST"* ]]
}

@test "[push-qa-deployed-tag] missing CI_JOB_TOKEN → exit 1" {
  unset CI_JOB_TOKEN
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CI_JOB_TOKEN"* ]]
}

@test "[push-qa-deployed-tag] missing qa pin → exit 1" {
  rm "$TEST_DIR/deployments/qa/version.yaml"
  _stub_git 2
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"promotion pin not found"* ]]
}

@test "[push-qa-deployed-tag] tag already exists on origin → skip (exit 0, no push)" {
  local capture="$TEST_DIR/git-calls"
  _stub_git 0 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"already exists on origin — skipping"* ]]
  # Only the ls-remote call should have happened; no `git tag` or `git push`.
  ! grep -q '^tag ' "$capture" || return 1
  ! grep -q '^push ' "$capture" || return 1
}

@test "[push-qa-deployed-tag] tag missing → create and push, then exit 0" {
  local capture="$TEST_DIR/git-calls"
  _stub_git 2 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Pushing tag qa-deployed-1.81.0--data-v1.80.0--etl-$ETL_A"* ]]
  [[ "$output" == *"Tag qa-deployed-1.81.0--data-v1.80.0--etl-$ETL_A pushed"* ]]
  # Lightweight tag: `git tag <name>` — no `-m` / no `--no-sign` (see #560 review).
  grep -qE '^tag qa-deployed-1\.81\.0--data-v1\.80\.0--etl-v1\.79\.0$' "$capture"
  grep -q "push .* refs/tags/qa-deployed-1.81.0--data-v1.80.0--etl-$ETL_A" "$capture"
}

@test "[push-qa-deployed-tag] tag name derived from pin file, not CI_COMMIT_TAG" {
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "2.0.0-rc1" "v1.99.0" "$ETL_B"
  export CI_COMMIT_TAG="some-other-tag"  # must be ignored
  local capture="$TEST_DIR/git-calls"
  _stub_git 2 "$capture"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "qa-deployed-2.0.0-rc1--data-v1.99.0--etl-$ETL_B" "$capture"
  ! grep -q 'some-other-tag' "$capture" || return 1
}

@test "[push-qa-deployed-tag] emitted tag name is a valid git ref (real git, no stub)" {
  # Regression guard for the 2026-09-15 incident: every other test in this
  # suite stubs `git`, so a syntactically invalid tag name (`,` + `:` — colon
  # is disallowed by git-check-ref-format rule 5) passed CI and only would
  # have failed at deploy time. This case runs real git against a scratch
  # repo so `git tag` itself enforces ref-name legality.
  # shellcheck source=/dev/null
  source "$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/lib/deploy.sh"
  local repo tag
  repo="$(mktemp -d)"
  tag="$(promotion_pin_attestation_tag "$TEST_DIR/deployments/qa/version.yaml")"
  # Inline user identity so this test does not require ambient git config
  # (CI runners have none) — `git commit` would otherwise exit 128 on
  # "please tell me who you are".
  ( cd "$repo" \
      && git init -q \
      && git -c user.email=ci@example.com -c user.name=ci \
           commit --allow-empty -qm init \
      && git tag "$tag" )
  # Sanity: the printed tag is the canonical (double-hyphen) format.
  [[ "$tag" == "qa-deployed-1.81.0--data-v1.80.0--etl-$ETL_A" ]]
  rm -rf "$repo"
}
