#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/verify/etl-readiness-check.sh
# Covers: no-active-release no-op, DLQ baseline+increase, grace+consecutive-
# empty success, timeout, KB FAILED, stale-COMPLETE-before-timestamp rejection,
# chunking-absent skip-not-fail.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/verify/etl-readiness-check.sh"

TRANSFORM_Q="arn:aws:sqs:eu-central-1:123456789012:transform-queue"
TRANSFORM_DLQ="arn:aws:sqs:eu-central-1:123456789012:transform-dlq"
BM25_Q="arn:aws:sqs:eu-central-1:123456789012:bm25-queue"
BM25_DLQ="arn:aws:sqs:eu-central-1:123456789012:bm25-dlq"
CHUNKING_Q="arn:aws:sqs:eu-central-1:123456789012:chunking-queue"
CHUNKING_DLQ="arn:aws:sqs:eu-central-1:123456789012:chunking-dlq"
KB_ID="ABCD123456"
DS_ID="XYZ987654"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  export AWS_DEFAULT_REGION="eu-central-1"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Builds an aws stub.
# Args (all env-driven via files under $TEST_DIR for simplicity):
#   $TEST_DIR/queue_depths   -- "arnsuffix depth" lines (visible; not-visible=0)
#   $TEST_DIR/dlq_depths     -- "arnsuffix depth" lines; each successive call
#                                for the SAME queue advances to the next line
#                                (simulates depth changing between baseline
#                                capture and later polls).
#   $TEST_DIR/kb_jobs.json   -- ingestionJobSummaries response
_aws_stub() {
  cat >"$TEST_DIR/bin/aws" <<'STUB'
#!/bin/bash
CMD="$*"

if [[ "$CMD" == *"sqs get-queue-attributes"* ]]; then
  for arg in "$@"; do
    if [[ "$arg" == *"/"* && "$arg" == *"sqs"* ]]; then
      QUEUE_URL="$arg"
    fi
  done
  NAME="${QUEUE_URL##*/}"
  if [[ "$CMD" == *"ApproximateNumberOfMessagesNotVisible"* ]]; then
    DEPTH=$(grep "^${NAME} " "$TEST_DIR_ENV/queue_depths" 2>/dev/null | tail -1 | awk '{print $2}')
    DEPTH="${DEPTH:-0}"
    printf '{"Attributes":{"ApproximateNumberOfMessages":"%s","ApproximateNumberOfMessagesNotVisible":"0"}}\n' "$DEPTH"
  else
    # Sequential-call cursor per queue name: each call for the same NAME
    # advances to the next matching line, then sticks on the last one.
    CURSOR_FILE="$TEST_DIR_ENV/.dlq_cursor_${NAME}"
    CALL=1
    if [ -f "$CURSOR_FILE" ]; then CALL=$(($(cat "$CURSOR_FILE") + 1)); fi
    echo "$CALL" >"$CURSOR_FILE"
    DEPTH=$(grep "^${NAME} " "$TEST_DIR_ENV/dlq_depths" 2>/dev/null | sed -n "${CALL}p" | awk '{print $2}')
    if [ -z "$DEPTH" ]; then
      # Past the last recorded line — stick on the last value.
      DEPTH=$(grep "^${NAME} " "$TEST_DIR_ENV/dlq_depths" 2>/dev/null | tail -1 | awk '{print $2}')
    fi
    DEPTH="${DEPTH:-0}"
    printf '{"Attributes":{"ApproximateNumberOfMessages":"%s"}}\n' "$DEPTH"
  fi
  exit 0
fi

if [[ "$CMD" == *"list-ingestion-jobs"* ]]; then
  if [ -f "$TEST_DIR_ENV/kb_job_complete_now" ]; then
    # Evaluated fresh on every call — always >= any START_TS the script
    # could have captured, regardless of clock drift since test setup.
    NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    printf '{"ingestionJobSummaries":[{"startedAt":"%s","status":"COMPLETE"}]}\n' "$NOW"
  elif [ -f "$TEST_DIR_ENV/kb_job_failed_now" ]; then
    NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    printf '{"ingestionJobSummaries":[{"startedAt":"%s","status":"FAILED"}]}\n' "$NOW"
  elif [ -f "$TEST_DIR_ENV/kb_jobs.json" ]; then
    cat "$TEST_DIR_ENV/kb_jobs.json"
  else
    echo '{"ingestionJobSummaries":[]}'
  fi
  exit 0
fi

exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR_ENV="$TEST_DIR"
}

_set_queue_depth() {
  echo "$1 $2" >>"$TEST_DIR/queue_depths"
}

_set_dlq_depth() {
  echo "$1 $2" >>"$TEST_DIR/dlq_depths"
}

_set_kb_job_complete_now() {
  # Marker file (not a pre-baked timestamp): the aws stub's list-ingestion-jobs
  # branch checks for this file and, if present, computes "now" fresh on every
  # invocation. A timestamp baked in at test-setup time would compare against
  # the script's own START_TS (captured after setup, inside the script) — on
  # a loaded CI runner the gap between the two can cross a second boundary,
  # making a fixed pre-computed value earlier than START_TS and failing the
  # startedAt >= $start check nondeterministically.
  touch "$TEST_DIR/kb_job_complete_now"
}

_set_kb_job_failed_now() {
  # Same live-timestamp approach as the marker-file path in _aws_stub, to
  # avoid the same setup-time-vs-script-time clock race.
  touch "$TEST_DIR/kb_job_failed_now"
}

_set_kb_job_complete_stale() {
  # A COMPLETE job that started well BEFORE this run — must not satisfy the gate.
  printf '{"ingestionJobSummaries":[{"startedAt":"2000-01-01T00:00:00Z","status":"COMPLETE"}]}\n' \
    >"$TEST_DIR/kb_jobs.json"
}

# ---------------------------------------------------------------------------

@test "[etl-readiness] no active release → explicit success no-op, no polling" {
  _aws_stub
  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version ""
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing to process"* ]]
  [[ "$output" == *"READINESS_RESULT=nothing-to-process"* ]]
}

@test "[etl-readiness] missing required arg → exit 1" {
  run bash "$SCRIPT" --transform-queue-arn "$TRANSFORM_Q"
  [ "$status" -eq 1 ]
}

@test "[etl-readiness] success: queues drain after grace + consecutive empty polls, KB COMPLETE" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 30
  [ "$status" -eq 0 ]
  [[ "$output" == *"Readiness check passed"* ]]
  [[ "$output" == *"READINESS_RESULT=ready"* ]]
}

@test "[etl-readiness] DLQ increase over baseline → fail closed" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  # Sequential cursor: 1st call (baseline capture) reads 0; every call after
  # that reads 1 — simulating a new DLQ message arriving during the run.
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "transform-dlq" 1
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5
  [ "$status" -eq 1 ]
  [[ "$output" == *"DLQ increased"* ]]
}

@test "[etl-readiness] pre-existing DLQ baseline (non-zero, no increase) → does not fail" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  # Baseline captured as 1 and STAYS 1 (no increase) — must not fail.
  _set_dlq_depth "transform-dlq" 1
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 10
  [ "$status" -eq 0 ]
}

@test "[etl-readiness] non-empty bm25 rebuild queue does NOT block readiness (#590 fix — reprocess floods it with idempotent triggers)" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  # BM25 rebuild queue deep (as during a full-corpus reprocess) — must be
  # polled/logged but NOT gate readiness. Only transform (+ chunking) drain
  # and KB ingestion COMPLETE matter.
  _set_queue_depth "bm25-queue" 3000
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 10
  [ "$status" -eq 0 ]
  [[ "$output" == *"READINESS_RESULT=ready"* ]]
  # The bm25 depth is still surfaced for diagnostics even though it doesn't gate.
  [[ "$output" == *"bm25=3000"* ]]
}

@test "[etl-readiness] bm25 rebuild DLQ increase still fails closed (rebuild failures are NOT ignored)" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  # bm25 DLQ: baseline 0 on first read, then 1 — a rebuild failed mid-run.
  _set_dlq_depth "bm25-dlq" 0
  _set_dlq_depth "bm25-dlq" 1
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5
  [ "$status" -eq 1 ]
  [[ "$output" == *"bm25-rebuild DLQ increased"* ]]
}

@test "[etl-readiness] timeout waiting for queues to drain → fail closed" {
  _aws_stub
  _set_queue_depth "transform-queue" 5
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"Timeout"* ]]
}

@test "[etl-readiness] KB ingestion FAILED (started at/after run) → fail closed" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_failed_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAILED"* ]]
}

@test "[etl-readiness] stale COMPLETE job (started before run) does not satisfy the gate → timeout" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_stale

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"Timeout"* ]]
}

@test "[etl-readiness] chunking ARNs absent → skipped, not failed" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 10
  [ "$status" -eq 0 ]
  # No chunking DLQ baseline is logged when the chunking ARNs are not passed —
  # confirms the signal is skipped entirely, not silently treated as depth 0.
  [[ "$output" != *"chunking DLQ baseline"* ]]
}

@test "[etl-readiness] chunking ARNs present and drained → succeeds" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_queue_depth "chunking-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_dlq_depth "chunking-dlq" 0
  _set_kb_job_complete_now

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --chunking-queue-arn "$CHUNKING_Q" --chunking-dlq-arn "$CHUNKING_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 10
  [ "$status" -eq 0 ]
}

@test "[etl-readiness] chunking queue non-empty blocks readiness when chunking is enabled" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_queue_depth "chunking-queue" 3
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_dlq_depth "chunking-dlq" 0

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --chunking-queue-arn "$CHUNKING_Q" --chunking-dlq-arn "$CHUNKING_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 1
  [ "$status" -eq 1 ]
  [[ "$output" == *"Timeout"* ]]
}

# ---------------------------------------------------------------------------
# #590 review fix: --start-ts / --*-dlq-baseline overrides, and the AWS CLI's
# real startedAt rendering (fractional seconds + "+00:00", never a bare "Z").
# ---------------------------------------------------------------------------

@test "[etl-readiness] --start-ts override: job started well before the caller's captured start is rejected as stale" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  _set_kb_job_complete_stale

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 1 \
    --start-ts "2026-01-01T00:00:00Z"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Timeout"* ]]
}

@test "[etl-readiness] --start-ts override: job with AWS CLI's real +00:00/fractional-second format at/after start is accepted" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0
  # Simulates the AWS CLI's actual --output json rendering for a `timestamp`
  # field — fractional seconds + "+00:00" offset, never a bare "Z". A raw
  # ISO8601 string compare against a "...Z" START_TS would incorrectly reject
  # this as stale within the same second; the epoch-normalized compare must
  # accept it.
  printf '{"ingestionJobSummaries":[{"startedAt":"2026-06-01T12:00:00.500000+00:00","status":"COMPLETE"}]}\n' \
    >"$TEST_DIR/kb_jobs.json"

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5 \
    --start-ts "2026-06-01T12:00:00Z"
  [ "$status" -eq 0 ]
  [[ "$output" == *"READINESS_RESULT=ready"* ]]
}

@test "[etl-readiness] --*-dlq-baseline overrides: a DLQ message already present at the overridden baseline does not fail" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_kb_job_complete_now
  # No _set_dlq_depth calls — the stub would report 0 for any live capture,
  # but we pass overrides claiming a baseline of 1 for transform. A current
  # depth of 0 (<=1) must not trigger a false "increase" failure.
  _set_dlq_depth "transform-dlq" 0
  _set_dlq_depth "bm25-dlq" 0

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5 \
    --transform-dlq-baseline 1 --bm25-dlq-baseline 0
  [ "$status" -eq 0 ]
  [[ "$output" == *"Using caller-supplied DLQ baselines"* ]]
  [[ "$output" == *"transform DLQ baseline: 1"* ]]
}

@test "[etl-readiness] --*-dlq-baseline overrides: current depth above the overridden baseline still fails closed" {
  _aws_stub
  _set_queue_depth "transform-queue" 0
  _set_queue_depth "bm25-queue" 0
  _set_kb_job_complete_now
  # Live stub reports 2 on every call for transform-dlq (single fixture line,
  # sticks). Overridden baseline of 0 means 2 > 0 must fail closed.
  _set_dlq_depth "transform-dlq" 2
  _set_dlq_depth "bm25-dlq" 0

  run bash "$SCRIPT" \
    --transform-queue-arn "$TRANSFORM_Q" --transform-dlq-arn "$TRANSFORM_DLQ" \
    --bm25-queue-arn "$BM25_Q" --bm25-dlq-arn "$BM25_DLQ" \
    --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --active-version "v1.0.0" \
    --grace-seconds 0 --poll-interval-seconds 0 --consecutive-empty 2 \
    --timeout-seconds 5 \
    --transform-dlq-baseline 0 --bm25-dlq-baseline 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"DLQ increased"* ]]
}
