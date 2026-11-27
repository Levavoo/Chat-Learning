#!/usr/bin/env bats

# Verifies the grep/sed idiom used in cdk-deploy:preprod to parse the version
# from deployments/preprod.yaml.

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/deployments" "$TEST_DIR/deployments/preprod"
}

teardown() {
  rm -rf "$TEST_DIR"
}

_parse() {
  grep '^version:' "$TEST_DIR/deployments/preprod/version.yaml" | sed 's/version: //'
}

@test "[preprod-yaml] bare semver extracted correctly" {
  echo "version: 1.51.1" >"$TEST_DIR/deployments/preprod/version.yaml"
  [ "$(_parse)" = "1.51.1" ]
}

@test "[preprod-yaml] no trailing whitespace in result" {
  printf 'version: 1.51.1\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  result="$(_parse)"
  [ "$result" = "1.51.1" ]
  [[ "$result" != *" "* ]]
}

@test "[preprod-yaml] version field among other keys still parsed" {
  printf 'env: preprod\nversion: 2.0.0\nregion: eu-central-1\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  [ "$(_parse)" = "2.0.0" ]
}
