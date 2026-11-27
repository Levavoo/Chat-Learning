#!/usr/bin/env bats
# #665 (TKT-RO-03) — build-qa-green-candidate.sh has no main() guard: sourcing
# the whole script runs the real 15-step QA green-candidate pipeline against
# live AWS. Tests extract individual functions by brace depth and source only
# those, with a fake `aws` on PATH, instead of mocking the entire pipeline.

bats_require_minimum_version 1.5.0

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/build-qa-green-candidate.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  TEST_SCRIPT="$TEST_DIR/build-qa-green-candidate.sh"
  sed 's/\r$//' "$SCRIPT" >"$TEST_SCRIPT"
  chmod +x "$TEST_SCRIPT"
  TMP_DIR="$(mktemp -d)"
  REGION="eu-central-1"
  DEV_PROFILE="digibro-eu-dev"
  QA_PROFILE="digibro-eu-qa"
  FUNCS="$TEST_DIR/functions.sh"
}

teardown() {
  rm -rf "$TEST_DIR" "$TMP_DIR"
}

# Extracts one function body from $SCRIPT by counting brace depth, so nested
# {} (jq filters, case blocks) don't truncate the extraction early the way a
# naive `sed -n '/^name() {/,/^}/p'` range would.
extract() {
  local name="$1"
  awk -v fn="$name" '
    $0 ~ "^" fn "\\(\\) \\{" { capture=1 }
    capture {
      print
      o = gsub(/\{/, "{"); c = gsub(/\}/, "}")
      depth += o - c
      if (depth == 0) exit
    }
  ' "$TEST_SCRIPT"
}

# Sources one or more functions (in dependency order) into $FUNCS so a test
# can call the function under test without running the script's top-level
# pipeline.
load_functions() {
  : >"$FUNCS"
  local name
  for name in "$@"; do
    extract "$name" >>"$FUNCS"
    echo >>"$FUNCS"
  done
}

# ── CLI argument validation (env-init) ─────────────────────────────────────
# Critical: this is the only gate stopping an operator from accidentally
# combining two mutually-exclusive mutation modes before any AWS call fires.

@test "[build-qa-green] rejects --replace-live combined with --chatbot-only-successor" {
  run "$TEST_SCRIPT" --replace-live --chatbot-only-successor
  [ "$status" -eq 2 ]
  [[ "$output" == *"--replace-live and --chatbot-only-successor cannot be combined"* ]]
}

@test "[build-qa-green] rejects an unknown flag before touching AWS" {
  run "$TEST_SCRIPT" --bogus
  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown argument: --bogus"* ]]
}

# ── S3 write-once semantics (put_write_once / object_exists) ──────────────
# Critical: this is the only thing preventing a rebuild from silently
# overwriting an already-published immutable green artifact with different
# bytes. A false "match" here corrupts the QA green candidate undetected.

@test "[build-qa-green] put_write_once creates the object when it doesn't exist yet" {
  load_functions sha256_base64 fail log_value dev_aws qa_aws cloud_aws object_exists put_write_once
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$TEST_DIR/aws-calls.log"
case "\$*" in
  *"s3api head-object"*) echo "An error occurred (404) NoSuchKey" >&2; exit 254 ;;
  *"s3api put-object"*) exit 0 ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  printf 'payload' >"$TEST_DIR/file.bin"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE
  run bash -c "source '$FUNCS' && put_write_once qa my-bucket my-key '$TEST_DIR/file.bin'"
  [ "$status" -eq 0 ]
  grep -q 's3api put-object' "$TEST_DIR/aws-calls.log"
  grep -q -- '--if-none-match \*' "$TEST_DIR/aws-calls.log"
}

@test "[build-qa-green] put_write_once verifies (not re-uploads) when the checksum already matches" {
  load_functions sha256_base64 fail log_value dev_aws qa_aws cloud_aws object_exists put_write_once
  printf 'payload' >"$TEST_DIR/file.bin"
  EXPECTED_B64="$(openssl dgst -sha256 -binary "$TEST_DIR/file.bin" | openssl base64 -A)"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$TEST_DIR/aws-calls.log"
case "\$*" in
  *"--checksum-mode ENABLED"*"--query ChecksumSHA256"*) echo "$EXPECTED_B64"; exit 0 ;;
  *"s3api head-object"*) exit 0 ;;
  *"s3api put-object"*) echo "SHOULD NOT PUT" >&2; exit 1 ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE
  run bash -c "source '$FUNCS' && put_write_once qa my-bucket my-key '$TEST_DIR/file.bin'"
  [ "$status" -eq 0 ]
  run ! grep -q 's3api put-object' "$TEST_DIR/aws-calls.log"
}

@test "[build-qa-green] put_write_once fails closed when the existing object's bytes diverge" {
  load_functions sha256_base64 fail log_value dev_aws qa_aws cloud_aws object_exists put_write_once
  printf 'original-bytes' >"$TEST_DIR/file.bin"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"--checksum-mode ENABLED"*"--query ChecksumSHA256"*) echo "None"; exit 0 ;;
  *"s3api head-object"*) exit 0 ;;
  *"s3 cp"*)
    dest="\${@: -2:1}"
    printf 'different-bytes' >"\$dest"
    exit 0
    ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE
  run bash -c "source '$FUNCS' && put_write_once qa my-bucket my-key '$TEST_DIR/file.bin'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"contains divergent bytes"* ]]
}

# ── Bedrock ingestion wait/retry (start_and_wait_green_ingestion) ─────────
# Critical: this is the longest-running wait in the script (up to
# GREEN_BUILD_TIMEOUT_SECONDS) and the one place a ConflictException must be
# retried rather than treated as fatal — get this wrong and either the build
# retries forever on a real failure, or gives up on a transient conflict.

@test "[build-qa-green] start_and_wait_green_ingestion retries on ConflictException then succeeds" {
  load_functions fail log_value dev_aws qa_aws cloud_aws wait_for_no_active_green_ingestion start_and_wait_green_ingestion
  GREEN_KB_ID="KB1"
  GREEN_DATA_SOURCE_ID="DS1"
  RELEASE_ID="rel-1"
  GREEN_BUILD_TIMEOUT_SECONDS=30
  GREEN_BUILD_POLL_SECONDS=0
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
CALLS="${TEST_DIR:?}/start-calls"
case "$*" in
  *"list-ingestion-jobs"*) echo '{"ingestionJobSummaries":[]}'; exit 0 ;;
  *"start-ingestion-job"*)
    n=$(( $(cat "$CALLS" 2>/dev/null || echo 0) + 1 ))
    echo "$n" >"$CALLS"
    if [ "$n" -eq 1 ]; then
      echo "ConflictException: another ingestion job is running" >&2
      exit 1
    fi
    echo '{"ingestionJob":{"ingestionJobId":"job-1"}}'
    exit 0
    ;;
  *"get-ingestion-job"*"--query ingestionJob.status"*) echo "COMPLETE"; exit 0 ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE GREEN_KB_ID GREEN_DATA_SOURCE_ID RELEASE_ID GREEN_BUILD_TIMEOUT_SECONDS GREEN_BUILD_POLL_SECONDS
  run bash -c "source '$FUNCS' && start_and_wait_green_ingestion && echo GREEN_INGESTION_ID=\$GREEN_INGESTION_ID"
  [ "$status" -eq 0 ]
  [[ "$output" == *"GREEN_INGESTION_ID=job-1"* ]]
  [ "$(cat "$TEST_DIR/start-calls")" -eq 2 ]
}

@test "[build-qa-green] start_and_wait_green_ingestion fails closed when the job ends FAILED" {
  load_functions fail log_value dev_aws qa_aws cloud_aws wait_for_no_active_green_ingestion start_and_wait_green_ingestion
  GREEN_KB_ID="KB1"
  GREEN_DATA_SOURCE_ID="DS1"
  RELEASE_ID="rel-1"
  GREEN_BUILD_TIMEOUT_SECONDS=30
  GREEN_BUILD_POLL_SECONDS=0
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"list-ingestion-jobs"*) echo '{"ingestionJobSummaries":[]}'; exit 0 ;;
  *"start-ingestion-job"*) echo '{"ingestionJob":{"ingestionJobId":"job-1"}}'; exit 0 ;;
  *"get-ingestion-job"*"--query ingestionJob.status"*) echo "FAILED"; exit 0 ;;
  *"get-ingestion-job"*) echo '{"status":"FAILED"}'; exit 0 ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE GREEN_KB_ID GREEN_DATA_SOURCE_ID RELEASE_ID GREEN_BUILD_TIMEOUT_SECONDS GREEN_BUILD_POLL_SECONDS
  run bash -c "source '$FUNCS' && start_and_wait_green_ingestion"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ended with FAILED"* ]]
}

# ── SQS drain wait/timeout (wait_for_qa_queues_empty) ──────────────────────
# Critical: per the RO ticket's own Befund, AWS waits like this one are the
# longest pauses in the pipeline — a poll loop that never re-checks the DLQs
# or never times out turns a real failure into a silent hang.

@test "[build-qa-green] wait_for_qa_queues_empty times out with all queues still draining" {
  load_functions fail log_value dev_aws qa_aws cloud_aws queue_url_from_arn queue_depth assert_queue_empty assert_all_dlqs_empty wait_for_qa_queues_empty
  QA_TRANSFORM_QUEUE_ARN="arn:aws:sqs:eu-central-1:111:qa-transform"
  BLUE_BM25_QUEUE_ARN="arn:aws:sqs:eu-central-1:111:blue-bm25"
  GREEN_BM25_QUEUE_ARN="arn:aws:sqs:eu-central-1:111:green-bm25"
  DEV_TRANSFORM_DLQ_ARN="arn:aws:sqs:eu-central-1:111:dev-transform-dlq"
  DEV_BM25_DLQ_ARN="arn:aws:sqs:eu-central-1:111:dev-bm25-dlq"
  DEV_CHUNKING_DLQ_ARN=""
  QA_TRANSFORM_DLQ_ARN="arn:aws:sqs:eu-central-1:111:qa-transform-dlq"
  BLUE_BM25_DLQ_ARN="arn:aws:sqs:eu-central-1:111:blue-bm25-dlq"
  GREEN_BM25_DLQ_ARN="arn:aws:sqs:eu-central-1:111:green-bm25-dlq"
  QA_CHUNKING_DLQ_ARN=""
  GREEN_BUILD_TIMEOUT_SECONDS=1
  GREEN_BUILD_POLL_SECONDS=1
  # DLQ queue URLs (derived from the *-dlq ARNs above) always report empty so
  # assert_all_dlqs_empty passes; the non-DLQ transform/bm25 queues always
  # report one message so the main drain condition never clears and the loop
  # runs out the GREEN_BUILD_TIMEOUT_SECONDS clock.
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"get-queue-attributes"*"-dlq"*)
    echo '{"Attributes":{"ApproximateNumberOfMessages":"0","ApproximateNumberOfMessagesNotVisible":"0"}}'
    exit 0
    ;;
  *"get-queue-attributes"*)
    echo '{"Attributes":{"ApproximateNumberOfMessages":"1","ApproximateNumberOfMessagesNotVisible":"0"}}'
    exit 0
    ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR TMP_DIR REGION DEV_PROFILE QA_PROFILE QA_TRANSFORM_QUEUE_ARN BLUE_BM25_QUEUE_ARN GREEN_BM25_QUEUE_ARN DEV_TRANSFORM_DLQ_ARN DEV_BM25_DLQ_ARN DEV_CHUNKING_DLQ_ARN QA_TRANSFORM_DLQ_ARN BLUE_BM25_DLQ_ARN GREEN_BM25_DLQ_ARN QA_CHUNKING_DLQ_ARN GREEN_BUILD_TIMEOUT_SECONDS GREEN_BUILD_POLL_SECONDS
  run bash -c "source '$FUNCS' && wait_for_qa_queues_empty"
  [ "$status" -eq 1 ]
  [[ "$output" == *"timed out waiting for QA queues to empty"* ]]
}
