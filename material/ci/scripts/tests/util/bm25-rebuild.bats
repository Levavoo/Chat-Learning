#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/util/bm25-rebuild.sh
# Covers: success, SSM failure, Lambda invocation failure, FunctionError, missing NumChunks.
# #590: NumChunks parsing uses jq (not python3 — the CI node-aws image has no python3).

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/util/bm25-rebuild.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"

  export PATH="$TEST_DIR/bin:$PATH"
  export AWS_DEFAULT_REGION="eu-central-1"
  export AWS_ACCESS_KEY_ID="FAKEID"
  export AWS_SECRET_ACCESS_KEY="FAKESECRET"
  export AWS_SESSION_TOKEN="FAKETOKEN"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Build an aws stub.
# Args:
#   ssm_result:    function name returned by ssm get-parameter, or "FAIL" to simulate error.
#   invoke_result: "OK", "CLI_FAIL", "FUNCTION_ERROR", "MISSING_NUMCHUNKS", or "MALFORMED_JSON"
#   num_chunks:    NumChunks value written in the OK response (default 42)
_aws_stub() {
  local ssm_result="${1:-my-builder-fn}"
  local invoke_result="${2:-OK}"
  local num_chunks="${3:-42}"
  local throttle_count="${4:-0}"

  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"

if [[ "\$CMD" == *"ssm get-parameter"* ]]; then
  if [ "${ssm_result}" = "FAIL" ]; then
    echo "An error occurred (ParameterNotFound)" >&2
    exit 1
  fi
  echo "${ssm_result}"
  exit 0
fi

if [[ "\$CMD" == *"lambda invoke"* ]]; then
  # Record the full invoke command so tests can assert on the flags passed.
  echo "\$CMD" >> "$TEST_DIR/invoke_cmd"
  # Find the response file (last positional arg after all flags)
  RESPONSE_FILE="\${@: -1}"
  case "${invoke_result}" in
    CLI_FAIL)
      echo "An error occurred (ResourceNotFoundException)" >&2
      exit 255
      ;;
    ALWAYS_THROTTLE)
      # Every invoke is throttled — exercises the bounded-retry-then-fail path.
      echo "An error occurred (TooManyRequestsException) when calling the Invoke operation (reached max retries: 2): Rate Exceeded." >&2
      echo "Reason: ReservedFunctionConcurrentInvocationLimitExceeded" >&2
      exit 254
      ;;
    THROTTLE_THEN_OK)
      # Throttle the first ${throttle_count} calls, then succeed — exercises
      # retry-with-backoff recovery once the (simulated) flood drains.
      COUNT_FILE="$TEST_DIR/invoke_count"
      N=0; [ -f "\$COUNT_FILE" ] && N=\$(cat "\$COUNT_FILE")
      N=\$((N + 1)); echo "\$N" > "\$COUNT_FILE"
      if [ "\$N" -le "${throttle_count}" ]; then
        echo "An error occurred (TooManyRequestsException): Rate Exceeded." >&2
        echo "Reason: ReservedFunctionConcurrentInvocationLimitExceeded" >&2
        exit 254
      fi
      echo '{}' > "\${RESPONSE_FILE}.meta"
      echo '{"NumChunks":${num_chunks}}' > "\${RESPONSE_FILE}"
      exit 0
      ;;
    FUNCTION_ERROR)
      # Write FunctionError to .meta file (simulated by writing to the response-meta path)
      # The script writes stdout/stderr of the invoke call to RESPONSE_FILE.meta
      echo '{"FunctionError":"Unhandled","StatusCode":200}' > "\${RESPONSE_FILE}.meta"
      echo '{"errorMessage":"index build failed"}' > "\${RESPONSE_FILE}"
      exit 0
      ;;
    MISSING_NUMCHUNKS)
      echo '{}' > "\${RESPONSE_FILE}.meta"
      echo '{"status":"ok"}' > "\${RESPONSE_FILE}"
      exit 0
      ;;
    MALFORMED_JSON)
      echo '{}' > "\${RESPONSE_FILE}.meta"
      echo 'not valid json' > "\${RESPONSE_FILE}"
      exit 0
      ;;
    OK)
      echo '{}' > "\${RESPONSE_FILE}.meta"
      echo '{"NumChunks":${num_chunks}}' > "\${RESPONSE_FILE}"
      exit 0
      ;;
  esac
fi

exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

# ── Success path ───────────────────────────────────────────────────────────────

@test "[bm25-rebuild] success: resolves SSM, invokes Lambda, prints chunk count" {
  _aws_stub "my-bm25-builder-fn" "OK" 42

  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [[ "$output" == *"my-bm25-builder-fn"* ]]
  [[ "$output" == *"42"* ]]
  [[ "$output" == *"✅"* ]]
}

@test "[bm25-rebuild] invoke sets an extended --cli-read-timeout (rebuild exceeds the CLI 60s default)" {
  # The synchronous invoke must wait out a multi-minute rebuild rather than
  # aborting at the AWS CLI's 60s default ("Read timeout on endpoint URL",
  # observed on the post-#848 run).
  _aws_stub "my-fn" "OK" 5

  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q -- "--cli-read-timeout 600" "$TEST_DIR/invoke_cmd"
}

@test "[bm25-rebuild] --cli-read-timeout is overridable via BM25_INVOKE_READ_TIMEOUT" {
  _aws_stub "my-fn" "OK" 5
  export BM25_INVOKE_READ_TIMEOUT=123

  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q -- "--cli-read-timeout 123" "$TEST_DIR/invoke_cmd"
}

@test "[bm25-rebuild] defaults to 'dev' environment when no arg given" {
  _aws_stub "fn-dev" "OK" 5

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/dev/renate/bm25-builder-function-name"* ]]
}

@test "[bm25-rebuild] uses provided environment name in SSM path" {
  _aws_stub "fn-qa" "OK" 10

  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"/qa/renate/bm25-builder-function-name"* ]]
}

@test "[bm25-rebuild] NumChunks=0 is treated as a failure (empty/malformed index)" {
  # Issue #590 requires failing on "zero/unexpected chunk count" — a
  # legitimate rebuild must always index at least one chunk.
  _aws_stub "my-fn" "OK" 0

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"0 chunks"* ]]
}

@test "[bm25-rebuild] negative NumChunks → exit 1" {
  _aws_stub "my-fn" "OK" "-5"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a positive integer"* ]]
}

@test "[bm25-rebuild] non-numeric NumChunks → exit 1" {
  _aws_stub "my-fn" "OK" '"abc"'

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a positive integer"* ]]
}

# ── SSM failure ────────────────────────────────────────────────────────────────

@test "[bm25-rebuild] SSM get-parameter failure → exit 1 with error message" {
  _aws_stub "FAIL" "OK"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌"* ]]
  [[ "$output" == *"SSM parameter"* ]]
}

# ── Lambda CLI failure ─────────────────────────────────────────────────────────

@test "[bm25-rebuild] Lambda invoke AWS CLI failure → exit 1 with error message" {
  _aws_stub "my-fn" "CLI_FAIL"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌"* ]]
}

# ── Concurrency-throttle retry (#590 fix — pipeline #2714) ──────────────────────

@test "[bm25-rebuild] throttled invoke is retried and eventually succeeds" {
  # Throttle the first 3 invokes (ReservedFunctionConcurrentInvocationLimitExceeded),
  # then succeed — simulates the reprocess flood draining and freeing a slot.
  _aws_stub "my-fn" "THROTTLE_THEN_OK" 42 3
  export BM25_INVOKE_RETRY_DELAY=0
  export BM25_INVOKE_MAX_ATTEMPTS=10

  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [[ "$output" == *"throttled (attempt 1/10)"* ]]
  [[ "$output" == *"throttled (attempt 3/10)"* ]]
  [[ "$output" == *"42 chunks indexed"* ]]
}

@test "[bm25-rebuild] persistent throttling fails closed after the retry budget" {
  _aws_stub "my-fn" "ALWAYS_THROTTLE"
  export BM25_INVOKE_RETRY_DELAY=0
  export BM25_INVOKE_MAX_ATTEMPTS=4

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"still throttled after 4 attempts"* ]]
}

@test "[bm25-rebuild] a NON-throttle invoke failure is NOT retried (fails immediately)" {
  _aws_stub "my-fn" "CLI_FAIL"
  export BM25_INVOKE_RETRY_DELAY=0
  export BM25_INVOKE_MAX_ATTEMPTS=10

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"AWS CLI lambda invoke failed"* ]]
  # Must not have entered the retry loop for a non-throttle error.
  [[ "$output" != *"throttled (attempt"* ]]
}

# ── FunctionError ──────────────────────────────────────────────────────────────

@test "[bm25-rebuild] Lambda FunctionError in response → exit 1" {
  _aws_stub "my-fn" "FUNCTION_ERROR"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"FunctionError"* ]]
}

# ── Missing / malformed NumChunks ───────────────────────────────────────────────

@test "[bm25-rebuild] response payload missing NumChunks key → exit 1" {
  _aws_stub "my-fn" "MISSING_NUMCHUNKS"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"NumChunks missing"* ]]
}

@test "[bm25-rebuild] malformed (non-JSON) response payload → exit 1" {
  _aws_stub "my-fn" "MALFORMED_JSON"

  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"NumChunks missing"* ]]
}

# ── Temp file cleanup ──────────────────────────────────────────────────────────

@test "[bm25-rebuild] temp files are cleaned up on success" {
  _aws_stub "my-fn" "OK" 1

  # Count tmp files before
  BEFORE=$(find /tmp -maxdepth 1 -name 'tmp.*' 2>/dev/null | wc -l)

  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]

  # Count tmp files after — should not have grown (trap cleans up)
  AFTER=$(find /tmp -maxdepth 1 -name 'tmp.*' 2>/dev/null | wc -l)
  [ "$AFTER" -le "$BEFORE" ]
}
