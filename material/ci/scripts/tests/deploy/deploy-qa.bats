#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-qa.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments/qa"
  printf 'version: 1.28.5\ndata_artifact_version: v1.27.0\netl_version: v1.26.0\n' \
    >"$TEST_DIR/deployments/qa/version.yaml"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[deploy-qa] obsolete standalone wrapper fails before AWS or CDK" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Direct QA deployment is disabled by #492"* ]]
}
