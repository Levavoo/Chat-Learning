#!/usr/bin/env bats

# Verifies the grep/sed idiom used in cdk-deploy:qa to parse the version from
# deployments/qa/version.yaml.  The expression must survive format variations so that
# a CI regression is caught before the job ever runs.

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments/qa"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_parse() {
  grep '^version:' "$TEST_DIR/deployments/qa/version.yaml" | sed 's/version: //'
}

@test "[qa-yaml] bare semver extracted correctly" {
  echo "version: 1.28.5" >"$TEST_DIR/deployments/qa/version.yaml"
  [ "$(_parse)" = "1.28.5" ]
}

@test "[qa-yaml] no trailing whitespace in result" {
  printf 'version: 1.28.5\n' >"$TEST_DIR/deployments/qa/version.yaml"
  result="$(_parse)"
  [ "$result" = "1.28.5" ]
  [[ "$result" != *" "* ]]
}

@test "[qa-yaml] version field among other keys still parsed" {
  printf 'env: qa\nversion: 2.0.0\nregion: eu-central-1\n' >"$TEST_DIR/deployments/qa/version.yaml"
  [ "$(_parse)" = "2.0.0" ]
}
