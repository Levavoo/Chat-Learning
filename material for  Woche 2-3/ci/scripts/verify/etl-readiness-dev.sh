#!/usr/bin/env bash
set -euo pipefail
# etl-readiness-dev.sh
# Dev SSM wrapper around etl-readiness-check.sh — resolves the queue/DLQ ARNs,
# KB id, data-source id, and active data-artifact version from
# /dev/renate/... SSM parameters (published by etl-kb-stack.ts, spec §6),
# then delegates to the reusable core script.
#
# Usage: etl-readiness-dev.sh [--skip-fingerprint-write] [extra args passed
#        through to etl-readiness-check.sh, e.g. --timeout-seconds N]
#
# --skip-fingerprint-write: used by etl-readiness-data:dev (the FIRST-pass
# readiness gate that runs after build-data-artifacts, before the ETL image
# has necessarily been redeployed). Only deploy-etl:dev's final readiness
# step (after its own CDK deploy) writes /dev/renate/etl-code-fingerprint —
# see deploy-and-verify-etl-dev.sh, which does the SSM put-parameter itself
# using $ETL_FINGERPRINT from etl-changed:dev's dotenv. This wrapper never
# writes the fingerprint; the flag exists so callers can express intent
# explicitly and so a future caller of this wrapper cannot accidentally
# write it either.
#
# Required env: AWS credentials already exported by the calling CI job
# (role assumption happens in the job's script:, not here).

REGION="${AWS_DEFAULT_REGION:-eu-central-1}"
ENV_NAME="dev"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_FINGERPRINT_WRITE="false"
EXTRA_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-fingerprint-write) SKIP_FINGERPRINT_WRITE="true"; shift ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done
# Referenced for documentation/clarity only — this wrapper performs no SSM
# writes regardless of the flag's value (see header comment).
: "$SKIP_FINGERPRINT_WRITE"

_get_param() {
  aws ssm get-parameter --name "$1" --query Parameter.Value \
    --output text --region "$REGION" 2>/dev/null || echo ""
}

TRANSFORM_QUEUE_ARN=$(_get_param "/${ENV_NAME}/renate/etl-queue-arn")
TRANSFORM_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/etl-dlq-arn")
BM25_QUEUE_ARN=$(_get_param "/${ENV_NAME}/renate/bm25-rebuild-queue-arn")
BM25_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/bm25-rebuild-dlq-arn")
CHUNKING_QUEUE_ARN=$(_get_param "/${ENV_NAME}/renate/chunking-queue-arn")
CHUNKING_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/chunking-dlq-arn")
KNOWLEDGE_BASE_ID=$(_get_param "/${ENV_NAME}/renate/knowledge-base-id")
DATA_SOURCE_ID=$(_get_param "/${ENV_NAME}/renate/data-source-id")
ACTIVE_VERSION=$(_get_param "/${ENV_NAME}/renate/data-artifact-version")

: "${TRANSFORM_QUEUE_ARN:?/${ENV_NAME}/renate/etl-queue-arn not found in SSM}"
: "${TRANSFORM_DLQ_ARN:?/${ENV_NAME}/renate/etl-dlq-arn not found in SSM}"
: "${BM25_QUEUE_ARN:?/${ENV_NAME}/renate/bm25-rebuild-queue-arn not found in SSM}"
: "${BM25_DLQ_ARN:?/${ENV_NAME}/renate/bm25-rebuild-dlq-arn not found in SSM}"
: "${KNOWLEDGE_BASE_ID:?/${ENV_NAME}/renate/knowledge-base-id not found in SSM}"
: "${DATA_SOURCE_ID:?/${ENV_NAME}/renate/data-source-id not found in SSM}"

ARGS=(
  --transform-queue-arn "$TRANSFORM_QUEUE_ARN"
  --transform-dlq-arn "$TRANSFORM_DLQ_ARN"
  --bm25-queue-arn "$BM25_QUEUE_ARN"
  --bm25-dlq-arn "$BM25_DLQ_ARN"
  --knowledge-base-id "$KNOWLEDGE_BASE_ID"
  --data-source-id "$DATA_SOURCE_ID"
  --active-version "$ACTIVE_VERSION"
)

# Chunking disabled in dev by default (parameter.ts sets no `chunking`) — the
# SSM parameters simply won't exist, and _get_param returns "". Pass the flags
# only when both ARNs are present so the core script treats chunking as
# optional/absent rather than polling an empty queue URL.
if [ -n "$CHUNKING_QUEUE_ARN" ] && [ -n "$CHUNKING_DLQ_ARN" ]; then
  ARGS+=(--chunking-queue-arn "$CHUNKING_QUEUE_ARN" --chunking-dlq-arn "$CHUNKING_DLQ_ARN")
fi

ARGS+=("${EXTRA_ARGS[@]}")

exec "${SCRIPT_DIR}/etl-readiness-check.sh" "${ARGS[@]}"
