#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/validate/check-maintenance-rehearsal.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments/preprod"
  export PATH="$TEST_DIR/bin:$PATH"
  echo "version: 1.90.0" >"$TEST_DIR/deployments/preprod/version.yaml"

  # Default git stub: zero rehearsal tags on origin. Tests that need tags
  # override this.
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_stub_git_two_tags() {
  local version="$1"
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
if [[ "\$1" == "ls-remote" ]]; then
  printf 'deadbeef1 refs/tags/maintenance-rehearsed-qa-${version}-1001\n'
  printf 'deadbeef2 refs/tags/maintenance-rehearsed-qa-${version}-1002\n'
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

@test "[check-maintenance-rehearsal] no env arg → exit 1" {
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[check-maintenance-rehearsal] unsupported env (qa) → exit 1" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa"
  [ "$status" -eq 1 ]
  [[ "$output" == *"unsupported env"* ]]
}

@test "[check-maintenance-rehearsal] missing pin file → exit 1" {
  rm "$TEST_DIR/deployments/preprod/version.yaml"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Pin file not found"* ]]
}

@test "[check-maintenance-rehearsal] maintenance key absent → skip, exit 0" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping rehearsal check"* ]]
}

@test "[check-maintenance-rehearsal] maintenance: false → skip, exit 0" {
  printf 'version: 1.90.0\nmaintenance: false\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping rehearsal check"* ]]
}

@test "[check-maintenance-rehearsal] maintenance: true with 0 rehearsal tags → exit 1" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"only 0 rehearsal(s)"* ]]
}

@test "[check-maintenance-rehearsal] maintenance: true with 2 rehearsal tags for the promoted version → exit 0" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  _stub_git_two_tags "1.90.0"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"enough qa rehearsals"* ]]
}

@test "[check-maintenance-rehearsal] maintenance: true with 2 tags for a DIFFERENT version → exit 1 (version-scoped)" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  _stub_git_two_tags "1.40.0"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"only 0 rehearsal(s)"* ]]
}

@test "[check-maintenance-rehearsal] maintenance: true with trailing comment, 2 tags → exit 0" {
  printf 'env: preprod\nmaintenance: true  # incident window\nversion: 1.90.0\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  _stub_git_two_tags "1.90.0"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
}
