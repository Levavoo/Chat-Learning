#!/usr/bin/env bats
# #670 — promotion and rollback outcomes share one environment-parameterized
# Rocket.Chat notifier without changing the existing deployment message.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/notify-rocketchat.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export TEST_DIR
  export ROCKETCHAT_AUTH_TOKEN=test-token
  export ROCKETCHAT_USER_ID=test-user
  export ROCKETCHAT_DEPLOYMENTS_CHANNEL=deployments
  export ROCKETCHAT_URL=https://rocketchat.test
  export CI_PIPELINE_URL=https://gitlab.test/pipelines/1

  cat >"$TEST_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$TEST_DIR/curl-args"
EOF
  chmod +x "$TEST_DIR/bin/curl"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "[#670 notify] existing deployment message remains the default" {
  CHATBOT_VERSION=3.31.0 PATH="$TEST_DIR/bin:$PATH" run "$SCRIPT" prod
  [ "$status" -eq 0 ]
  grep -q '\[prod\] Deployment' "$TEST_DIR/curl-args"
  grep -q '3.31.0' "$TEST_DIR/curl-args"
}

@test "[#670 notify] rollback message records the confirmed target release" {
  EXPECTED_TARGET_RELEASE_ID=sha256-seeded-blue \
    PATH="$TEST_DIR/bin:$PATH" run "$SCRIPT" prod rollback
  [ "$status" -eq 0 ]
  grep -q '\[prod\] Retrieval rollback' "$TEST_DIR/curl-args"
  grep -q 'sha256-seeded-blue' "$TEST_DIR/curl-args"
}

@test "[#670 notify] unknown event fails before sending" {
  PATH="$TEST_DIR/bin:$PATH" run "$SCRIPT" prod unknown
  [ "$status" -eq 2 ]
  [ ! -e "$TEST_DIR/curl-args" ]
}
