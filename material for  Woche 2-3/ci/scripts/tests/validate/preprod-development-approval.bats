#!/usr/bin/env bats
# #643/#670 — the parameterized temporary development policy is explicit and
# cannot be selected through a pipeline variable. It performs no token-bearing
# API request and makes no spoofable identity claim.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
RECORD="$REPO_ROOT/.gitlab/ci/scripts/validate/record-retrieval-promotion-development-approval.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export TEST_DIR
}

teardown() { rm -rf "$TEST_DIR"; }

@test "[#643 development approval] exact reviewed policy succeeds and is explicit" {
  cd "$TEST_DIR"
  run "$RECORD" preprod development-single-operator
  [ "$status" -eq 0 ]
  [[ "$output" == *"DEVELOPMENT MODE"* ]]
  [[ "$output" == *"one operator may approve"* ]]
  [[ "$output" == *"Four-eyes separation is intentionally not claimed"* ]]
  jq -e '
    .environment == "preprod"
    and .policy == "development-single-operator"
    and .audit_authority == "gitlab-manual-job-and-deployment-record"
    and .identity_claimed_by_artifact == false
    and .four_eyes_claimed == false
  ' preprod-retrieval-promotion-approval.json >/dev/null
}

@test "[#670 development approval] prod uses the same policy and writes evidence" {
  cd "$TEST_DIR"
  CI_PIPELINE_URL=https://gitlab.test/pipelines/1 \
  CI_JOB_URL=https://gitlab.test/jobs/2 \
    run "$RECORD" prod development-single-operator
  [ "$status" -eq 0 ]
  jq -e '
    .environment == "prod"
    and .pipeline_url == "https://gitlab.test/pipelines/1"
    and .job_url == "https://gitlab.test/jobs/2"
  ' prod-retrieval-promotion-approval.json >/dev/null
}

@test "[#643 development approval] missing or unknown policy fails closed" {
  run "$RECORD"
  [ "$status" -ne 0 ]
  [[ "$output" == *"expected environment"* ]]

  run "$RECORD" prod four-eyes
  [ "$status" -ne 0 ]
  [[ "$output" == *"expected the reviewed policy argument"* ]]
}

@test "[#643 development approval] spoofed CI variables never trigger an API call" {
  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
touch "$TEST_DIR/curl-called"
exit 99
EOF
  chmod +x "$TEST_DIR/bin/curl"

  PATH="$TEST_DIR/bin:$PATH" \
  CI_API_V4_URL=https://attacker.example \
  CI_PROJECT_ID=999 \
  CI_COMMIT_SHA=spoofed \
  GITLAB_USER_LOGIN=spoofed \
  GITLAB_USER_ID=999 \
  FOUR_EYES_API_TOKEN=secret \
  APPROVAL_EVIDENCE_FILE="$TEST_DIR/spoof-test-evidence.json" \
    run "$RECORD" prod development-single-operator

  [ "$status" -eq 0 ]
  [ ! -e "$TEST_DIR/curl-called" ]
  [[ "$output" != *"spoofed"* ]]
}
