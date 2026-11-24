#!/usr/bin/env bats
# #629 tests for the retrieval-promotion job-start tooling guard.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/validate/assert-retrieval-tooling.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk/bin"
  touch "$TEST_DIR/cdk/bin/infrastructure.ts"
  # Stub binaries for jq/node/aws are added per test; PATH is scoped to only
  # this bin dir (plus /usr/bin and /bin for bash's own coreutils needs) so a
  # missing stub genuinely means "not found", not "found on the real PATH".
}

teardown() {
  rm -rf "$TEST_DIR"
}

_stub() {
  cat >"$TEST_DIR/bin/$1" <<'EOF'
#!/bin/sh
exit 0
EOF
  chmod +x "$TEST_DIR/bin/$1"
}

@test "[#629 tooling] all tools present and CDK entry exists → OK" {
  _stub jq
  _stub node
  _stub aws
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"all present"* ]]
}

@test "[#629 tooling] missing jq → exit 1, names jq" {
  _stub node
  _stub aws
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"jq"* ]]
}

@test "[#629 tooling] missing node → exit 1, names node" {
  _stub jq
  _stub aws
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"node"* ]]
}

@test "[#629 tooling] missing aws → exit 1, names aws" {
  _stub jq
  _stub node
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"aws"* ]]
}

@test "[#629 tooling] missing CDK entry point → exit 1, names the path" {
  _stub jq
  _stub node
  _stub aws
  rm "$TEST_DIR/cdk/bin/infrastructure.ts"
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"infrastructure.ts"* ]]
}

@test "[#629 tooling] multiple missing tools are all listed together" {
  _stub aws
  rm "$TEST_DIR/cdk/bin/infrastructure.ts"
  run bash -c "REPO_ROOT='$TEST_DIR' PATH='$TEST_DIR/bin' /bin/bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"jq"* ]]
  [[ "$output" == *"node"* ]]
  [[ "$output" == *"infrastructure.ts"* ]]
}
