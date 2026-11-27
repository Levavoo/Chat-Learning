#!/usr/bin/env bash
# QA retrieval queue, ingestion, diagnostic, and wait-loop helpers.

# shellcheck source=qa-retrieval-common.sh disable=SC1091
source "${BASH_SOURCE[0]%/*}/qa-retrieval-common.sh"

qa_retrieval_queue_url() {
  local arn="$1"
  printf 'https://sqs.%s.amazonaws.com/%s/%s\n' \
    "$(printf '%s' "$arn" | cut -d: -f4)" \
    "$(printf '%s' "$arn" | cut -d: -f5)" \
    "$(printf '%s' "$arn" | cut -d: -f6)"
}

qa_retrieval_queue_depth() {
  local arn="$1" attrs
  attrs=$(aws sqs get-queue-attributes \
    --queue-url "$(qa_retrieval_queue_url "$arn")" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --output json)
  jq -r '(.Attributes.ApproximateNumberOfMessages // "0" | tonumber) +
    (.Attributes.ApproximateNumberOfMessagesNotVisible // "0" | tonumber)' <<<"$attrs"
}

# DLQ depth — visible messages only (unlike qa_retrieval_queue_depth, which
# adds in-flight/not-visible too). A DLQ message becomes visible once its
# consumer's visibility timeout expires without acknowledgement, so
# not-visible is not a meaningful DLQ signal the way it is for a working
# queue. Extracted from etl-readiness-check.sh's private _dlq_depth (#494)
# so the #494 scheduled health check can reuse the same baseline/current-depth
# logic instead of reimplementing it.
qa_retrieval_dlq_depth() {
  local arn="$1"
  aws sqs get-queue-attributes \
    --queue-url "$(qa_retrieval_queue_url "$arn")" \
    --attribute-names ApproximateNumberOfMessages \
    --output json \
    | jq -r '.Attributes.ApproximateNumberOfMessages // "0"'
}

# Return the status of the most recent Bedrock KB ingestion job for
# data-source-id that started at/after start_ts_epoch (epoch seconds), or
# empty if none. Extracted from etl-readiness-check.sh's inline jq filter
# (#494) so the scheduled health check reuses the exact same "ignore stale
# jobs from before this check" logic as the promotion-time readiness gate —
# both sides normalize AWS's fractional-seconds-plus-offset timestamp via
# jq's strptime/mktime, not fromdateiso8601 (which rejects that format).
qa_retrieval_ingestion_job_status() {
  local knowledge_base_id="$1" data_source_id="$2" start_ts_epoch="$3" jobs_json
  jobs_json=$(aws bedrock-agent list-ingestion-jobs \
    --knowledge-base-id "$knowledge_base_id" \
    --data-source-id "$data_source_id" \
    --output json 2>/dev/null || echo '{"ingestionJobSummaries":[]}')
  jq -r --argjson start "$start_ts_epoch" '
    def to_epoch:
      sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z")
      | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime;
    [.ingestionJobSummaries[]? | select((.startedAt | to_epoch) >= $start)]
    | sort_by(.startedAt | to_epoch) | last | .status // ""' <<<"$jobs_json"
}

# Normalize an ISO8601 timestamp (with or without fractional seconds / a
# "+00:00" offset) to epoch seconds — the same normalization
# qa_retrieval_ingestion_job_status applies internally, exposed so callers
# can compute --start-ts-equivalent comparisons consistently (#494).
qa_retrieval_epoch_seconds() {
  local ts="$1"
  jq -rn --arg ts "$ts" '
    $ts | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z")
    | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime'
}

qa_retrieval_assert_queue_empty() {
  local arn="$1" label="$2" depth
  depth=$(qa_retrieval_queue_depth "$arn")
  [[ "$depth" -eq 0 ]] || {
    qa_retrieval_fail "${label} is not empty (depth=${depth})"
    return 1
  }
}

qa_retrieval_wait_queue_empty() {
  local arn="$1" label="$2"
  local timeout_seconds="${3:-${QA_RETRIEVAL_TIMEOUT_SECONDS:-3600}}"
  local poll_seconds="${QA_RETRIEVAL_QUEUE_POLL_SECONDS:-10}"
  local consecutive_required="${QA_RETRIEVAL_QUEUE_EMPTY_POLLS:-3}"
  local deadline=$((SECONDS + timeout_seconds)) consecutive_empty=0 depth

  while ((SECONDS <= deadline)); do
    depth=$(qa_retrieval_queue_depth "$arn") || return 1
    if [[ "$depth" -eq 0 ]]; then
      consecutive_empty=$((consecutive_empty + 1))
      if [[ "$consecutive_empty" -ge "$consecutive_required" ]]; then
        printf '%s is quiescent.\n' "$label" >&2
        return 0
      fi
    else
      consecutive_empty=0
      printf 'Waiting for %s to drain (depth=%s)...\n' "$label" "$depth" >&2
    fi
    sleep "$poll_seconds"
  done

  qa_retrieval_fail "timed out waiting for ${label} to drain"
  return 1
}

# Invoke a slot's sync Lambda after a bulk restore. S3 notifications may have
# started an ingestion while objects were still being copied; retrying until a
# fresh invocation succeeds guarantees one final scan of the complete corpus.
qa_retrieval_start_kb_sync() {
  local function_name="$1" bucket="$2" response invoke_meta payload attempt
  response=$(mktemp)
  invoke_meta=$(mktemp)
  payload=$(mktemp)
  jq -cn --arg bucket "$bucket" '{
    Records:[{
      eventName:"ObjectCreated:Copy",
      s3:{bucket:{name:$bucket},object:{key:"docs/qa-recovery-trigger.json"}}
    }]
  }' >"$payload"

  for attempt in $(seq 1 90); do
    if aws lambda invoke --function-name "$function_name" \
        --cli-binary-format raw-in-base64-out \
        --payload "fileb://${payload}" "$response" \
        --output json >"$invoke_meta" &&
      [[ "$(jq -r '.FunctionError // empty' "$invoke_meta")" == "" ]]; then
      rm -f "$response" "$invoke_meta" "$payload"
      return 0
    fi
    echo "KB sync is busy; retrying explicit recovery scan (${attempt}/90)..." >&2
    sleep 10
  done
  cat "$response" >&2 2>/dev/null || true
  rm -f "$response" "$invoke_meta" "$payload"
  qa_retrieval_fail "could not start a final KB sync through ${function_name}"
}

qa_retrieval_pin_prefixes() {
  local bucket="$1"
  shift
  local args=()
  local prefix
  for prefix in "$@"; do
    args+=(--prefix "$prefix")
  done
  node "${REPO_ROOT}/.gitlab/ci/scripts/lib/node/release-retention.mjs" pin \
    --bucket "$bucket" "${args[@]}" \
    --concurrency "$QA_RETENTION_CONCURRENCY"
}

qa_retrieval_unpin_prefixes() {
  local bucket="$1"
  shift
  local args=()
  local prefix
  for prefix in "$@"; do
    args+=(--prefix "$prefix")
  done
  node "${REPO_ROOT}/.gitlab/ci/scripts/lib/node/release-retention.mjs" unpin \
    --bucket "$bucket" "${args[@]}" \
    --concurrency "$QA_RETENTION_CONCURRENCY"
}


