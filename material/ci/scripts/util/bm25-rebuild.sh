#!/usr/bin/env bash
# Rebuild the BM25 index by directly invoking the builder Lambda.
#
# Usage: bm25-rebuild.sh <env> [aws-profile]
#
# Arguments:
#   env          Environment name (dev, qa, preprod, demo). Default: dev.
#   aws-profile  AWS CLI profile name. Optional; uses default credentials if omitted.
#
# Required tools: aws, jq
#
# Transient Lambda concurrency throttling (TooManyRequestsException /
# ReservedFunctionConcurrentInvocationLimitExceeded) is retried with backoff —
# see the invoke loop below. Tunable via BM25_INVOKE_MAX_ATTEMPTS /
# BM25_INVOKE_RETRY_DELAY (defaults 20 attempts × 30s ≈ 10 min).
#
# The invoke is synchronous and the rebuild runs for minutes, so the AWS CLI
# read timeout is extended (BM25_INVOKE_READ_TIMEOUT, default 600s) past the
# builder's 5-min Lambda timeout — the 60s CLI default would otherwise abort
# client-side mid-rebuild ("Read timeout on endpoint URL").
#
# Exit codes:
#   0  Rebuild succeeded; prints chunk count.
#   1  SSM lookup failed, Lambda invocation failed (non-throttle, or throttled
#      past the retry budget), FunctionError, or missing/zero/invalid NumChunks.

set -euo pipefail

ENV_NAME="${1:-dev}"
AWS_PROF="${2:-}"
REGION="eu-central-1"
SSM_PARAM="/${ENV_NAME}/renate/bm25-builder-function-name"

_aws() {
  if [ -n "$AWS_PROF" ]; then
    aws --region "$REGION" --profile "$AWS_PROF" "$@"
  else
    aws --region "$REGION" "$@"
  fi
}

echo "🔍 Resolving BM25 builder function name from SSM ${SSM_PARAM}"
FUNCTION_NAME=$(_aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --query "Parameter.Value" \
  --output text) || {
  echo "❌ Failed to read SSM parameter ${SSM_PARAM}"
  exit 1
}

if [ -z "$FUNCTION_NAME" ] || [ "$FUNCTION_NAME" = "None" ]; then
  echo "❌ SSM parameter ${SSM_PARAM} returned empty function name"
  exit 1
fi

echo "🔨 Invoking BM25 builder Lambda: ${FUNCTION_NAME}"

PAYLOAD_FILE=$(mktemp)
RESPONSE_FILE=$(mktemp)
# shellcheck disable=SC2064
trap "rm -f '${PAYLOAD_FILE}' '${RESPONSE_FILE}' '${RESPONSE_FILE}.meta'" EXIT

echo '{"source":"operator"}' >"${PAYLOAD_FILE}"

# Retry-with-backoff on concurrency throttling. The builder reserves only a few
# concurrent slots, and during a full-corpus reprocess the SQS event source is
# busy draining thousands of docs/*.md rebuild triggers — a direct invoke fired
# in that window can hit ReservedFunctionConcurrentInvocationLimitExceeded /
# TooManyRequestsException (observed on pipeline #2714). The flood is transient
# (it drains within minutes), so we wait it out. Only throttle errors are
# retried; any other invoke failure fails immediately.
# Tunable via env for tests: BM25_INVOKE_MAX_ATTEMPTS, BM25_INVOKE_RETRY_DELAY.
INVOKE_MAX_ATTEMPTS="${BM25_INVOKE_MAX_ATTEMPTS:-20}"
INVOKE_RETRY_DELAY="${BM25_INVOKE_RETRY_DELAY:-30}"

# This is a SYNCHRONOUS (RequestResponse) invoke — the CLI holds the connection
# open until the builder returns NumChunks. A full-corpus rebuild reads
# thousands of chunks from S3 and runs for minutes, far exceeding the AWS CLI's
# 60s default read timeout, which otherwise aborts client-side while the Lambda
# is still working (observed as "Read timeout on endpoint URL" on the post-#848
# run). Wait longer than the builder's 5-min Lambda timeout so the CLI reads the
# real result (success OR the Lambda's own timeout/FunctionError) rather than
# giving up early. Tunable for tests via BM25_INVOKE_READ_TIMEOUT.
INVOKE_READ_TIMEOUT="${BM25_INVOKE_READ_TIMEOUT:-600}"

attempt=1
while true; do
  if _aws lambda invoke \
      --function-name "${FUNCTION_NAME}" \
      --payload "file://${PAYLOAD_FILE}" \
      --cli-binary-format raw-in-base64-out \
      --cli-read-timeout "${INVOKE_READ_TIMEOUT}" \
      "${RESPONSE_FILE}" >"${RESPONSE_FILE}.meta" 2>&1; then
    break
  fi

  # Retry only transient throttle / concurrency-limit errors.
  if grep -qE 'TooManyRequestsException|ReservedFunctionConcurrentInvocationLimitExceeded|Rate Exceeded|ThrottlingException' \
      "${RESPONSE_FILE}.meta"; then
    if [ "$attempt" -ge "$INVOKE_MAX_ATTEMPTS" ]; then
      echo "❌ BM25 builder invoke still throttled after ${attempt} attempts:"
      cat "${RESPONSE_FILE}.meta"
      exit 1
    fi
    echo "⏳ BM25 builder throttled (attempt ${attempt}/${INVOKE_MAX_ATTEMPTS}) —" \
      "reprocess flood likely still draining; retrying in ${INVOKE_RETRY_DELAY}s..."
    attempt=$((attempt + 1))
    sleep "$INVOKE_RETRY_DELAY"
    continue
  fi

  # Any non-throttle error is a hard failure.
  echo "❌ AWS CLI lambda invoke failed:"
  cat "${RESPONSE_FILE}.meta"
  exit 1
done

if grep -q '"FunctionError"' "${RESPONSE_FILE}.meta"; then
  echo "❌ Lambda FunctionError:"
  cat "${RESPONSE_FILE}"
  exit 1
fi

NUM_CHUNKS=$(jq -e -r '.NumChunks // empty' "${RESPONSE_FILE}" 2>/dev/null) || {
  echo "❌ Unexpected response payload (NumChunks missing):"
  cat "${RESPONSE_FILE}"
  exit 1
}
if [ -z "${NUM_CHUNKS}" ]; then
  echo "❌ Unexpected response payload (NumChunks missing):"
  cat "${RESPONSE_FILE}"
  exit 1
fi

# NumChunks must be a positive integer. A rebuild that reports 0 (or a
# negative/non-numeric value) indicates an empty or malformed index and must
# fail the pipeline — issue #590 requires failure on "zero/unexpected chunk
# count", not just a missing field.
case "${NUM_CHUNKS}" in
  '' | *[!0-9]*)
    echo "❌ Unexpected NumChunks value (not a positive integer): ${NUM_CHUNKS}"
    cat "${RESPONSE_FILE}"
    exit 1
    ;;
esac
if [ "${NUM_CHUNKS}" -eq 0 ]; then
  echo "❌ BM25 rebuild reported 0 chunks indexed — treating as failure:"
  cat "${RESPONSE_FILE}"
  exit 1
fi

echo "✅ BM25 index rebuilt — ${NUM_CHUNKS} chunks indexed"
