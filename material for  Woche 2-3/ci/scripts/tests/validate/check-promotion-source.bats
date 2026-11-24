#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/validate/check-promotion-source.sh"
ETL_A="v1.38.0"
ETL_B="v1.49.0"

_write_pin() {
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$2" "$3" "$4" >"$1"
}

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments" \
    "$TEST_DIR/deployments/preprod" "$TEST_DIR/deployments/prod" \
    "$TEST_DIR/deployments/qa"
  export PATH="$TEST_DIR/bin:$PATH"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/prod/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"

  # Default git stub: no qa-deployed tag exists on origin. Individual tests
  # that need a tag override this. Without a stub, assert_version_on_qa's
  # ls-remote fallthrough would attempt a real network call.
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then exit 2; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[check-promotion-source] no env arg → exit 1" {
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[check-promotion-source] unknown env → exit 1" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' staging"
  [ "$status" -eq 1 ]
}

@test "[check-promotion-source] missing pin file → exit 1" {
  rm "$TEST_DIR/deployments/preprod/version.yaml"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Pin file not found"* ]]
}

@test "[check-promotion-source] preprod version == current qa pin → OK" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa-promoted triple"* ]]
}

@test "[#670 check-promotion-source] prod version == current qa pin → OK" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' prod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa-promoted triple"* ]]
}

@test "[#670 check-promotion-source] unattested prod triple fails closed" {
  _write_pin "$TEST_DIR/deployments/prod/version.yaml" "9.9.9" "v9.9.8" "$ETL_A"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' prod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"never smoke-tested on qa"* ]]
}

@test "[check-promotion-source] preprod version == qa current pin → OK" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
}

@test "[check-promotion-source] preprod version != qa current pin AND no qa-deployed tag → exit 1" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "9.9.9" "v9.9.8" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"never smoke-tested on qa"* ]]
}

@test "[check-promotion-source] preprod version != qa current pin BUT qa-deployed tag exists → OK (#560)" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.40.0" "v1.39.0" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  # Override the setup stub: tag EXISTS on origin
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then
  printf 'deadbeef\trefs/tags/qa-deployed-1.40.0--data-v1.39.0--etl-v1.38.0\n'
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa-deployed-1.40.0--data-v1.39.0--etl-$ETL_A found"* ]]
}

@test "[check-promotion-source] legacy qa-deployed tag format still resolves (backward-compat)" {
  # Pre-migration tags in origin use the single-hyphen `-data-`/`-etl-` form.
  # Existing preprod/prod pins that reference such tags must keep resolving.
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.40.0" "v1.39.0" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  # New-format ls-remote misses (exit 2), legacy-format ls-remote hits (exit 0).
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then
  for arg in "$@"; do
    case "$arg" in
      *--data-*--etl-*) exit 2 ;;
      *-data-*-etl-*)
        printf 'deadbeef\trefs/tags/qa-deployed-1.40.0-data-v1.39.0-etl-v1.38.0\n'
        exit 0
        ;;
    esac
  done
  exit 2
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"legacy format"* ]]
}

@test "[check-promotion-source] transport error on new-format probe does not silently fall through to legacy" {
  # A network glitch on the first ls-remote must return "could not reach
  # origin", not silently retry as legacy. Otherwise a definitively-absent
  # new-format tag with a transient legacy-format transport error would be
  # indistinguishable from "never QA-deployed".
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.40.0" "v1.39.0" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  cat >"$TEST_DIR/bin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "ls-remote" ]]; then
  echo "fatal: unable to access 'https://origin/'" >&2
  exit 128
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"could not reach origin"* ]]
}

@test "[check-promotion-source] #642 preprod blue baseline coordinate → OK (exempt, not qa-promoted)" {
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.83.3" "v1.83.3-preprod-blue-baseline" "v1.83.3-preprod-blue-baseline"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 0 ]
  [[ "$output" == *"controlled preprod blue baseline"* ]]
}

@test "[check-promotion-source] baseline exemption is narrow: mismatched etl still requires qa promotion" {
  # data == baseline but etl is an ordinary coordinate → NOT exempt → must be qa-promoted.
  _write_pin "$TEST_DIR/deployments/preprod/version.yaml" "1.83.3" "v1.83.3-preprod-blue-baseline" "$ETL_A"
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.51.1" "v1.50.0" "$ETL_B"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' preprod"
  [ "$status" -eq 1 ]
  [[ "$output" == *"never smoke-tested on qa"* ]]
}

@test "[check-promotion-source] baseline exemption does not apply to qa env" {
  # The exemption is preprod-only: qa must not take the baseline-exempt path
  # (qa trivially self-compares, so exit status is not the discriminator here).
  _write_pin "$TEST_DIR/deployments/qa/version.yaml" "1.83.3" "v1.83.3-preprod-blue-baseline" "v1.83.3-preprod-blue-baseline"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' qa"
  [[ "$output" != *"controlled preprod blue baseline"* ]]
}
