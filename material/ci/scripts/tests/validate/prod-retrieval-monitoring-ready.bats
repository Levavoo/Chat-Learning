#!/usr/bin/env bats
# #671 tests for the fail-closed prod retrieval alarm-action gate.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/.gitlab/ci/scripts/validate/assert-prod-retrieval-monitoring-ready.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  CONFIG_FILE="$TEST_DIR/config.yaml"
  PROMOTED_RELEASE_ID="sha256-$(printf '%064d' 0 | tr 0 d)"
  SEEDED_RELEASE_ID="sha256-$(printf '%064d' 0 | tr 0 e)"
}

teardown() {
  rm -rf "$TEST_DIR"
}

make_manifest() {
  local release_id="$1" slot="$2"
  jq -cn --arg release_id "$release_id" --arg slot "$slot" '{
    schema_version: 3,
    release_id: $release_id,
    version: "3.29.0",
    data_artifact_version: "v3.22.1-data.1",
    etl_version: "v3.28.1",
    knowledge_base_id: (if $slot == "blue" then "P3OEBMERZQ" else "4RKYJFKOL0" end),
    data_source_id: (if $slot == "blue" then "OO8HRR87VW" else "GREEN12345" end),
    raw_bucket: "renate-s3-etl-source-prod-test",
    raw_prefix: "releases/v3.22.1-data.1/",
    processed_bucket: ("renate-s3-" + $slot + "-processed-prod-test"),
    processed_prefix: ("processed/releases/" + $release_id + "/"),
    bm25_bucket: ("renate-s3-" + $slot + "-processed-prod-test"),
    bm25_key: ("bm25_index/releases/" + $release_id + "/index.json"),
    bm25_tokenizer_revision: "cistem-decompound-v1",
    etl_image_digest: ("sha256:" + ("a" * 64)),
    retrieval_artifact_id: ("sha256-" + ("b" * 64)),
    retrieval_artifact_fingerprint: ("sha256:" + ("b" * 64)),
    chatbot_image_digest: ("sha256:" + ("c" * 64))
  }'
}

install_fake_aws() {
  cat >"$TEST_DIR/bin/aws" <<'FAKE_AWS'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${TEST_DIR:?}/aws-calls.log"

if [[ "$1 $2" == "sts get-caller-identity" ]]; then
  printf '%s\n' '{"Account":"718036735727"}'
  exit 0
fi

if [[ "$1 $2" == "ssm get-parameter" ]]; then
  name=""
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--name" ]]; then
      j=$((i + 1))
      name="${!j}"
    fi
  done
  case "$name" in
    /prod/renate/retrieval/active-manifest) file="$TEST_DIR/active.json" ;;
    /prod/renate/retrieval/previous-manifest) file="$TEST_DIR/previous.json" ;;
    /prod/renate/retrieval/health-check-state) file="$TEST_DIR/state.json" ;;
    *) echo "unexpected parameter: $name" >&2; exit 98 ;;
  esac
  [[ -s "$file" ]] || { echo "ParameterNotFound" >&2; exit 254; }
  cat "$file"
  exit 0
fi

echo "unexpected aws call: $*" >&2
exit 97
FAKE_AWS
  chmod +x "$TEST_DIR/bin/aws"
}

install_fake_node() {
  cat >"$TEST_DIR/bin/node" <<'FAKE_NODE'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *retrieval-environment.mjs* ]]; then
  exec env PATH="${PATH#*:}" node "$@"
fi
if [[ "$*" == *retrieval-release.mjs\ validate* ]]; then
  exit 0
fi
echo "unexpected node call: $*" >&2
exit 96
FAKE_NODE
  chmod +x "$TEST_DIR/bin/node"
}

set_promoted_selectors() {
  make_manifest "$PROMOTED_RELEASE_ID" green >"$TEST_DIR/active.json"
  make_manifest "$SEEDED_RELEASE_ID" blue >"$TEST_DIR/previous.json"
}

set_health_state() {
  local timestamp="$1" failed="${2:-false}"
  jq -cn --arg timestamp "$timestamp" --argjson failed "$failed" '{
    IngestionFailure: {last_failed: $failed, last_checked_at: $timestamp},
    CoherenceFailure: {last_failed: false, last_checked_at: $timestamp},
    RetentionPinMissing: {last_failed: false, last_checked_at: $timestamp}
  }' >"$TEST_DIR/state.json"
}

run_gate() {
  export TEST_DIR REPO_ROOT
  unset GITLAB_OIDC_TOKEN || true
  install_fake_node
  PATH="$TEST_DIR/bin:$PATH" run "$SCRIPT" prod "$CONFIG_FILE" "$@"
}

@test "[#671 alarm gate] activation mode requires the flag before AWS" {
  install_fake_aws
  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: false' >"$CONFIG_FILE"
  run_gate require-enabled
  [ "$status" -ne 0 ]
  [[ "$output" == *"must be true for the activation job"* ]]
  [ ! -f "$TEST_DIR/aws-calls.log" ]
}

@test "[#671 alarm gate] absent or false flags are zero-AWS no-ops" {
  install_fake_aws
  printf '%s\n' 'anonymousAccess: false' >"$CONFIG_FILE"
  run_gate
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/aws-calls.log" ]

  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: false' >"$CONFIG_FILE"
  run_gate
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/aws-calls.log" ]
}

@test "[#671 alarm gate] non-boolean and duplicate flags fail before AWS" {
  install_fake_aws
  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: yes' >"$CONFIG_FILE"
  run_gate
  [ "$status" -ne 0 ]
  [ ! -f "$TEST_DIR/aws-calls.log" ]

  printf '%s\n' \
    'retrievalHealthAlarmActionsEnabled: true' \
    'retrievalHealthAlarmActionsEnabled: false' >"$CONFIG_FILE"
  run_gate
  [ "$status" -ne 0 ]
  [ ! -f "$TEST_DIR/aws-calls.log" ]
}

@test "[#671 alarm gate] first promotion is required before actions can enable" {
  install_fake_aws
  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: true' >"$CONFIG_FILE"
  make_manifest "$SEEDED_RELEASE_ID" blue >"$TEST_DIR/active.json"
  set_health_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  run_gate
  [ "$status" -ne 0 ]
  [[ "$output" == *"previous-manifest"* ]]
}

@test "[#671 alarm gate] stale or failed health state is refused" {
  install_fake_aws
  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: true' >"$CONFIG_FILE"
  set_promoted_selectors

  set_health_state '2020-01-01T00:00:00Z'
  run_gate
  [ "$status" -ne 0 ]
  [[ "$output" == *"health state is incomplete, stale, failed, or malformed"* ]]

  set_health_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)" true
  run_gate
  [ "$status" -ne 0 ]
}

@test "[#671 alarm gate] fresh clean state after promotion permits the config deploy" {
  install_fake_aws
  printf '%s\n' 'retrievalHealthAlarmActionsEnabled: true' >"$CONFIG_FILE"
  set_promoted_selectors
  set_health_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  run_gate
  [ "$status" -eq 0 ]
  [[ "$output" == *"fresh clean health state verified"* ]]
  [[ "$output" == *"active ${PROMOTED_RELEASE_ID}"* ]]
  [[ "$output" == *"previous ${SEEDED_RELEASE_ID}"* ]]
}
