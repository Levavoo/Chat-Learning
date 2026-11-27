#!/usr/bin/env bash
# etl-readiness-check.sh
# Reusable readiness gate: waits for the transform (and, when enabled,
# chunking) SQS queue to drain, all DLQs to stay clean, and Bedrock KB
# ingestion to reach COMPLETE. Fails closed on timeout, DLQ activity, or
# ingestion FAILED. The BM25 rebuild queue is polled/logged but NOT gated on
# (its depth is not a meaningful readiness signal — see step 4). Designed to
# be called with explicit coordinates (arguments) so #492 (deploy-kb-swap,
# RFC 04) can reuse it against a different (green) KB id / data source — no
# hardcoded /dev/renate SSM lookups live here; those live in the dev wrapper
# (etl-readiness-dev.sh).
#
# Usage:
#   etl-readiness-check.sh \
#     --transform-queue-arn <arn> --transform-dlq-arn <arn> \
#     --bm25-queue-arn <arn> --bm25-dlq-arn <arn> \
#     [--chunking-queue-arn <arn> --chunking-dlq-arn <arn>] \
#     --knowledge-base-id <id> --data-source-id <id> \
#     [--active-version <version-or-empty>] \
#     [--grace-seconds N] [--poll-interval-seconds N] [--consecutive-empty N] \
#     [--timeout-seconds N] \
#     [--start-ts <ISO8601>] \
#     [--transform-dlq-baseline N] [--bm25-dlq-baseline N] \
#     [--chunking-dlq-baseline N]
#
# Chunking flags are OPTIONAL — when absent, chunking signals are skipped
# (not failed). Dev default has chunking disabled.
#
# --active-version: if passed as an empty string, this is a fresh environment
# with no active data release — reports an explicit successful no-op and exits
# 0 without polling anything (spec: "no active release ⇒ nothing to process").
# Omit the flag entirely to skip this shortcut (caller has no concept of an
# active-version pointer, e.g. a future non-dev caller).
#
# --start-ts / --*-dlq-baseline: OPTIONAL overrides for the "start of run"
# timestamp and DLQ baselines. Omit to capture them fresh at the top of this
# script (the pre-#590-review-fix behavior). Callers whose triggering action
# (CDK deploy → SourceReprocessTrigger, or a data-artifact publish) happens
# BEFORE this script starts MUST pass these explicitly, captured immediately
# before that triggering action — otherwise a fast reprocess/publish can
# already be mid-flight or complete by the time this script's own "start" is
# recorded, causing:
#   (a) a real ingestion job to be wrongly rejected as "stale" (started
#       before our late-captured START_TS) → false timeout, and
#   (b) a DLQ message from the CURRENT run landing before our late-captured
#       baseline → silently absorbed into "pre-existing", never detected as
#       an increase.
# See etl-changed:dev's deploy-etl-dev.sh caller for the canonical usage.
#
# Exit codes:
#   0  Ready (or explicit no-op — no active release).
#   1  Fail closed: timeout, DLQ increase over baseline, or ingestion FAILED.
#
# Required tools: aws, jq. No python3 (matches the other node-aws scripts).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/qa-retrieval-common.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-common.sh"
# shellcheck source=lib/qa-retrieval-auth.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-auth.sh"
# shellcheck source=lib/qa-retrieval-polling.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-polling.sh"
# shellcheck source=lib/qa-retrieval-s3.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-s3.sh"
# shellcheck source=lib/qa-retrieval-validation.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/qa-retrieval-validation.sh"

# ── Defaults ──────────────────────────────────────────────────────────────────
GRACE_SECONDS=30
POLL_INTERVAL_SECONDS=15
CONSECUTIVE_EMPTY_REQUIRED=3
TIMEOUT_SECONDS=900

TRANSFORM_QUEUE_ARN=""
TRANSFORM_DLQ_ARN=""
BM25_QUEUE_ARN=""
BM25_DLQ_ARN=""
CHUNKING_QUEUE_ARN=""
CHUNKING_DLQ_ARN=""
KNOWLEDGE_BASE_ID=""
DATA_SOURCE_ID=""
ACTIVE_VERSION_SET="false"
ACTIVE_VERSION=""
START_TS_OVERRIDE=""
TRANSFORM_DLQ_BASELINE_OVERRIDE=""
BM25_DLQ_BASELINE_OVERRIDE=""
CHUNKING_DLQ_BASELINE_OVERRIDE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --transform-queue-arn) TRANSFORM_QUEUE_ARN="$2"; shift 2 ;;
    --transform-dlq-arn) TRANSFORM_DLQ_ARN="$2"; shift 2 ;;
    --bm25-queue-arn) BM25_QUEUE_ARN="$2"; shift 2 ;;
    --bm25-dlq-arn) BM25_DLQ_ARN="$2"; shift 2 ;;
    --chunking-queue-arn) CHUNKING_QUEUE_ARN="$2"; shift 2 ;;
    --chunking-dlq-arn) CHUNKING_DLQ_ARN="$2"; shift 2 ;;
    --knowledge-base-id) KNOWLEDGE_BASE_ID="$2"; shift 2 ;;
    --data-source-id) DATA_SOURCE_ID="$2"; shift 2 ;;
    --active-version) ACTIVE_VERSION_SET="true"; ACTIVE_VERSION="$2"; shift 2 ;;
    --grace-seconds) GRACE_SECONDS="$2"; shift 2 ;;
    --poll-interval-seconds) POLL_INTERVAL_SECONDS="$2"; shift 2 ;;
    --consecutive-empty) CONSECUTIVE_EMPTY_REQUIRED="$2"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --start-ts) START_TS_OVERRIDE="$2"; shift 2 ;;
    --transform-dlq-baseline) TRANSFORM_DLQ_BASELINE_OVERRIDE="$2"; shift 2 ;;
    --bm25-dlq-baseline) BM25_DLQ_BASELINE_OVERRIDE="$2"; shift 2 ;;
    --chunking-dlq-baseline) CHUNKING_DLQ_BASELINE_OVERRIDE="$2"; shift 2 ;;
    *) echo "etl-readiness-check: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

# ── No active release: explicit successful no-op ────────────────────────────
if [ "$ACTIVE_VERSION_SET" = "true" ] && [ -z "$ACTIVE_VERSION" ]; then
  echo "No active data-artifact version — fresh environment, nothing to process."
  echo "READINESS_RESULT=nothing-to-process"
  exit 0
fi

: "${TRANSFORM_QUEUE_ARN:?--transform-queue-arn is required}"
: "${TRANSFORM_DLQ_ARN:?--transform-dlq-arn is required}"
: "${BM25_QUEUE_ARN:?--bm25-queue-arn is required}"
: "${BM25_DLQ_ARN:?--bm25-dlq-arn is required}"
: "${KNOWLEDGE_BASE_ID:?--knowledge-base-id is required}"
: "${DATA_SOURCE_ID:?--data-source-id is required}"

_queue_depth() {
  # Delegates to the shared lib (#494) — was a private duplicate of
  # qa_retrieval_queue_depth (visible + not-visible).
  qa_retrieval_queue_depth "$1"
}

_dlq_depth() {
  # Delegates to the shared lib (#494) — was a private duplicate of
  # qa_retrieval_dlq_depth (visible only).
  qa_retrieval_dlq_depth "$1"
}

# ── 1. Capture DLQ baselines (precondition — a pre-existing message from a
#       prior incident must not fail an otherwise-healthy run). Overrides take
#       priority — see --start-ts / --*-dlq-baseline doc above: a caller whose
#       triggering action happens before this script starts must capture these
#       BEFORE that action, not here. ──────────────────────────────────────────
if [ -n "$TRANSFORM_DLQ_BASELINE_OVERRIDE" ] || [ -n "$BM25_DLQ_BASELINE_OVERRIDE" ] || [ -n "$CHUNKING_DLQ_BASELINE_OVERRIDE" ]; then
  echo "Using caller-supplied DLQ baselines (captured before the triggering action)..."
  : "${TRANSFORM_DLQ_BASELINE_OVERRIDE:?--transform-dlq-baseline is required when any baseline override is passed}"
  : "${BM25_DLQ_BASELINE_OVERRIDE:?--bm25-dlq-baseline is required when any baseline override is passed}"
  TRANSFORM_DLQ_BASELINE="$TRANSFORM_DLQ_BASELINE_OVERRIDE"
  BM25_DLQ_BASELINE="$BM25_DLQ_BASELINE_OVERRIDE"
  CHUNKING_DLQ_BASELINE="${CHUNKING_DLQ_BASELINE_OVERRIDE:-0}"
else
  echo "Capturing DLQ baselines..."
  TRANSFORM_DLQ_BASELINE=$(_dlq_depth "$TRANSFORM_DLQ_ARN")
  BM25_DLQ_BASELINE=$(_dlq_depth "$BM25_DLQ_ARN")
  CHUNKING_DLQ_BASELINE=0
  if [ -n "$CHUNKING_DLQ_ARN" ]; then
    CHUNKING_DLQ_BASELINE=$(_dlq_depth "$CHUNKING_DLQ_ARN")
  fi
fi
echo "  transform DLQ baseline: ${TRANSFORM_DLQ_BASELINE}"
echo "  bm25 DLQ baseline:      ${BM25_DLQ_BASELINE}"
[ -n "$CHUNKING_DLQ_ARN" ] && echo "  chunking DLQ baseline:  ${CHUNKING_DLQ_BASELINE}"

_check_dlq_no_increase() {
  local arn="$1" baseline="$2" label="$3"
  local current
  current=$(_dlq_depth "$arn")
  if [ "$current" -gt "$baseline" ]; then
    echo "❌ ${label} DLQ increased: baseline=${baseline} current=${current}" >&2
    return 1
  fi
  return 0
}

# ── 2. Capture ingestion start timestamp (so a stale earlier COMPLETE cannot
#       pass the gate prematurely) ────────────────────────────────────────────
# ── 2. Capture ingestion start timestamp (so a stale earlier COMPLETE cannot
#       pass the gate prematurely). Override takes priority — see doc above. ─
if [ -n "$START_TS_OVERRIDE" ]; then
  START_TS="$START_TS_OVERRIDE"
  echo "Readiness check start (caller-supplied): ${START_TS}"
else
  START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "Readiness check start: ${START_TS}"
fi
# Normalized to epoch seconds via the shared qa_retrieval_epoch_seconds
# helper (not the shell's `date -d`/`date -j`, whose flags differ between
# GNU/Linux — the CI runner — and BSD/macOS local dev shells) so the
# comparison below is portable and always correct.
START_TS_EPOCH=$(qa_retrieval_epoch_seconds "$START_TS")

# ── 3. Grace phase ────────────────────────────────────────────────────────────
echo "Grace phase: waiting ${GRACE_SECONDS}s before polling..."
sleep "$GRACE_SECONDS"

# ── 4. Poll loop: transform (+ chunking) drained (N consecutive) + DLQs clean
#       + timeout.
#
#       The BM25 rebuild queue is DELIBERATELY excluded from the drain
#       condition (it is still polled + logged for diagnostics, and its DLQ is
#       still checked). Reason: a full-corpus reprocess re-emits one
#       docs/*.md S3 event per document (thousands), and the BM25 builder
#       rebuilds the ENTIRE index on every invocation (idempotent), so the
#       queue holds thousands of redundant, self-collapsing rebuild triggers
#       that drain far slower than any sane readiness timeout — blocking on it
#       is both wrong and guaranteed to time out (first observed on the live
#       #590 run, pipeline #2705). The authoritative BM25 signal is the
#       explicit bm25-rebuild.sh direct invoke (NumChunks > 0 check) that runs
#       after this gate; rebuild FAILURES are still caught here via the BM25
#       DLQ check above.
DEADLINE=$(( $(date +%s) + TIMEOUT_SECONDS ))
CONSECUTIVE_EMPTY=0

while true; do
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ]; then
    echo "❌ Timeout after ${TIMEOUT_SECONDS}s waiting for queues to drain." >&2
    exit 1
  fi

  _check_dlq_no_increase "$TRANSFORM_DLQ_ARN" "$TRANSFORM_DLQ_BASELINE" "transform" || exit 1
  _check_dlq_no_increase "$BM25_DLQ_ARN" "$BM25_DLQ_BASELINE" "bm25-rebuild" || exit 1
  if [ -n "$CHUNKING_DLQ_ARN" ]; then
    _check_dlq_no_increase "$CHUNKING_DLQ_ARN" "$CHUNKING_DLQ_BASELINE" "chunking" || exit 1
  fi

  TRANSFORM_DEPTH=$(_queue_depth "$TRANSFORM_QUEUE_ARN")
  BM25_DEPTH=$(_queue_depth "$BM25_QUEUE_ARN")
  CHUNKING_DEPTH=0
  if [ -n "$CHUNKING_QUEUE_ARN" ]; then
    CHUNKING_DEPTH=$(_queue_depth "$CHUNKING_QUEUE_ARN")
  fi

  echo "Poll: transform=${TRANSFORM_DEPTH} bm25=${BM25_DEPTH} chunking=${CHUNKING_DEPTH:-skip} consecutive_empty=${CONSECUTIVE_EMPTY}/${CONSECUTIVE_EMPTY_REQUIRED}"

  # BM25_DEPTH is intentionally NOT part of this condition — see the step-4
  # header comment above. Only the transform queue (and chunking, when
  # enabled) must drain; the BM25 rebuild queue is a debounced, idempotent,
  # self-collapsing backlog whose depth is not a meaningful readiness signal.
  if [ "$TRANSFORM_DEPTH" -eq 0 ] && [ "$CHUNKING_DEPTH" -eq 0 ]; then
    CONSECUTIVE_EMPTY=$((CONSECUTIVE_EMPTY + 1))
  else
    CONSECUTIVE_EMPTY=0
  fi

  if [ "$CONSECUTIVE_EMPTY" -ge "$CONSECUTIVE_EMPTY_REQUIRED" ]; then
    echo "Queues drained (${CONSECUTIVE_EMPTY} consecutive empty polls)."
    break
  fi

  sleep "$POLL_INTERVAL_SECONDS"
done

# ── 5. KB sync: poll ListIngestionJobs/GetIngestionJob for a job that STARTED
#       at/after START_TS and reaches COMPLETE. Any FAILED ⇒ fail. ───────────
echo "Waiting for KB ingestion job (data source ${DATA_SOURCE_ID})..."
while true; do
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ]; then
    echo "❌ Timeout after ${TIMEOUT_SECONDS}s waiting for KB ingestion." >&2
    exit 1
  fi

  _check_dlq_no_increase "$TRANSFORM_DLQ_ARN" "$TRANSFORM_DLQ_BASELINE" "transform" || exit 1
  _check_dlq_no_increase "$BM25_DLQ_ARN" "$BM25_DLQ_BASELINE" "bm25-rebuild" || exit 1
  if [ -n "$CHUNKING_DLQ_ARN" ]; then
    _check_dlq_no_increase "$CHUNKING_DLQ_ARN" "$CHUNKING_DLQ_BASELINE" "chunking" || exit 1
  fi

  # Jobs that started at/after START_TS. qa_retrieval_ingestion_job_status
  # normalizes both sides to epoch seconds internally (strptime/mktime, NOT
  # jq's fromdateiso8601 — that rejects the AWS CLI's actual rendering, which
  # includes fractional seconds and a "+00:00" offset, e.g.
  # "2026-07-14T07:44:43.123456+00:00", never a bare "Z"). Comparing raw
  # ISO8601 strings would sort incorrectly across differing suffix formats
  # within the same second.
  RELEVANT_JOB_STATUS=$(qa_retrieval_ingestion_job_status \
    "$KNOWLEDGE_BASE_ID" "$DATA_SOURCE_ID" "$START_TS_EPOCH")

  if [ "$RELEVANT_JOB_STATUS" = "FAILED" ]; then
    echo "❌ KB ingestion job FAILED (started at/after ${START_TS})." >&2
    exit 1
  fi

  if [ "$RELEVANT_JOB_STATUS" = "COMPLETE" ]; then
    echo "KB ingestion job COMPLETE."
    break
  fi

  echo "KB ingestion status: ${RELEVANT_JOB_STATUS:-<none yet>} — waiting..."
  sleep "$POLL_INTERVAL_SECONDS"
done

echo "✅ Readiness check passed."
echo "READINESS_RESULT=ready"
