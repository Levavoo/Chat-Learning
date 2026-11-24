#!/usr/bin/env bats

# #668/#717 — the prod pin. Two concerns:
#   1. the grep/sed idiom deploy-env.sh uses to parse the version still works on
#      a three-line pin (mirrors preprod-yaml.bats);
#   2. the committed deployments/prod/version.yaml keeps EXACTLY the three
#      expected keys (version, data_artifact_version, etl_version) and nothing
#      else — its pin-change promotion path is inert (#668), so this shape must
#      not drift.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
PROD_PIN="$REPO_ROOT/deployments/prod/version.yaml"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments/prod"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_parse() {
  grep '^version:' "$TEST_DIR/deployments/prod/version.yaml" | sed 's/version: //'
}

@test "[prod-yaml] bare semver extracted correctly" {
  echo "version: 3.29.0" >"$TEST_DIR/deployments/prod/version.yaml"
  [ "$(_parse)" = "3.29.0" ]
}

@test "[prod-yaml] no trailing whitespace in result" {
  printf 'version: 3.29.0\n' >"$TEST_DIR/deployments/prod/version.yaml"
  result="$(_parse)"
  [ "$result" = "3.29.0" ]
  [[ "$result" != *" "* ]]
}

@test "[prod-yaml] version field among the three-line pin still parsed" {
  printf 'version: 3.29.0\ndata_artifact_version: v3.22.1-data.1\netl_version: v3.28.1\n' \
    >"$TEST_DIR/deployments/prod/version.yaml"
  [ "$(_parse)" = "3.29.0" ]
}

@test "[prod-yaml] only the version: line matches ^version: (siblings excluded)" {
  printf 'version: 3.29.0\ndata_artifact_version: v3.22.1-data.1\netl_version: v3.28.1\n' \
    >"$TEST_DIR/deployments/prod/version.yaml"
  # the ^version: parser must match exactly one line
  [ "$(grep -c '^version:' "$TEST_DIR/deployments/prod/version.yaml")" -eq 1 ]
}

@test "[prod-yaml] committed prod pin has exactly the three expected keys" {
  [ -f "$PROD_PIN" ]
  # exactly three non-empty lines, one per key
  local lines
  lines="$(grep -c '.' "$PROD_PIN")"
  [ "$lines" -eq 3 ]
  grep -q '^version: ' "$PROD_PIN"
  grep -q '^data_artifact_version: ' "$PROD_PIN"
  grep -q '^etl_version: ' "$PROD_PIN"
  # no unexpected top-level keys
  local keys
  keys="$(grep -oE '^[a-z_]+:' "$PROD_PIN" | sort | tr '\n' ' ')"
  [ "$keys" = "data_artifact_version: etl_version: version: " ]
}

@test "[prod-yaml] committed prod pin version parses to a semver" {
  run bash -c "grep '^version:' '$PROD_PIN' | sed 's/version: //'"
  [ "$status" -eq 0 ]
  [[ "$output" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}
