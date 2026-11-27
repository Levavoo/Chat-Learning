#!/usr/bin/env bash
set -euo pipefail
# deploy-and-verify-etl-dev.sh
# Combines cdk-deploy-etl:dev + etl-readiness:dev into ONE atomic unit
# (#590 review fix, issues #3/#7/#4). Two separate CI jobs previously:
#   (a) released the `etl-dev` resource_group lock when the CDK deploy job
#       ended, leaving a gap before the readiness job re-acquired it — during
#       that gap another pipeline's build-data-artifacts could interleave
#       with the reprocess this deploy just triggered (#4).
#   (b) captured the readiness gate's START_TS/DLQ baselines INSIDE the
#       readiness job, i.e. AFTER cdk deploy had already returned — but
#       `cdk deploy` only returns once CloudFormation finishes, and the
#       SourceReprocessTrigger custom resource fires DURING that CFN update.
#       A fast reprocess could already be mid-flight or complete before the
#       readiness job's "start" was ever recorded, causing:
#         - a real ingestion job wrongly rejected as "stale" → false timeout
#           (#3/#7), and
#         - a DLQ message from the CURRENT run landing before the late
#           baseline capture → silently absorbed as "pre-existing", never
#           detected as an increase (#7).
#
# This script fixes both by doing everything in one script/job, capturing
# the baseline/timestamp BEFORE calling cdk deploy, and holding the
# resource_group lock (set at the CI job level, not here) continuously from
# before the deploy through the final readiness gate.
#
# Required CI variables: GITLAB_OIDC_TOKEN, CI_JOB_ID, CDK_DEPLOY_ROLE_ARN_DEV.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
OUTPUTS_FILE="${REPO_ROOT}/outputs-etl.json"
REGION="${AWS_DEFAULT_REGION:-eu-central-1}"
ENV_NAME="dev"
STACK_NAME="renate-etl-kb-${ENV_NAME}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"
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

ETL_READINESS_ROLE_ARN="arn:aws:iam::831926590742:role/ki-lab-digibro-dev-etl-readiness"
CDK_DEPLOY_ROLE_ARN="${CDK_DEPLOY_ROLE_ARN_DEV:?CDK_DEPLOY_ROLE_ARN_DEV is required but not set}"

_get_param() {
  aws ssm get-parameter --name "$1" --query Parameter.Value \
    --output text --region "$REGION" 2>/dev/null || echo ""
}

# Return a stable revision for an existing CloudFormation stack. Comparing the
# revision immediately before and after `cdk deploy` distinguishes an actual
# update from CDK's successful "no changes" path without parsing CLI prose.
# A not-yet-created stack returns empty. Access failures and malformed
# responses return non-zero so the caller can stop before deployment instead
# of mistaking an unobservable no-op for a real update and waiting forever for
# an ingestion job that was never started.
_stack_revision() {
  local revision
  if ! revision=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].[StackId,LastUpdatedTime,CreationTime]' \
    --output text --region "$REGION" 2>&1); then
    if [[ "$revision" == *"does not exist"* ]]; then
      return 0
    fi
    echo "Cannot read the CloudFormation revision for ${STACK_NAME}." >&2
    echo "The dev CDK deploy role requires cloudformation:DescribeStacks on ${STACK_NAME}." >&2
    printf '%s\n' "$revision" >&2
    return 1
  fi

  if [[ "$revision" == arn:aws:cloudformation:* ]]; then
    printf '%s\n' "$revision"
  elif [[ -n "$revision" && "$revision" != "[]" && "$revision" != "None" ]]; then
    echo "Malformed CloudFormation revision for ${STACK_NAME}: ${revision}" >&2
    return 1
  fi
}

# ── 1. Assume the readiness role to resolve coordinates + capture the
#       baseline/timestamp BEFORE anything that could trigger a reprocess ────
log_section "Pre-deploy: capture readiness baseline"
assume_deploy_role "$ETL_READINESS_ROLE_ARN"

TRANSFORM_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/etl-dlq-arn")
BM25_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/bm25-rebuild-dlq-arn")
CHUNKING_DLQ_ARN=$(_get_param "/${ENV_NAME}/renate/chunking-dlq-arn")

if [ -z "$TRANSFORM_DLQ_ARN" ] || [ -z "$BM25_DLQ_ARN" ]; then
  echo "⏭ ETL stack not yet deployed (no queue ARNs in SSM) — skipping" \
    "pre-deploy baseline capture; first deploy has nothing to compare against."
  START_TS=""
  TRANSFORM_DLQ_BASELINE="0"
  BM25_DLQ_BASELINE="0"
  CHUNKING_DLQ_BASELINE="0"
else
  START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  TRANSFORM_DLQ_BASELINE=$(qa_retrieval_dlq_depth "$TRANSFORM_DLQ_ARN")
  BM25_DLQ_BASELINE=$(qa_retrieval_dlq_depth "$BM25_DLQ_ARN")
  CHUNKING_DLQ_BASELINE="0"
  if [ -n "$CHUNKING_DLQ_ARN" ]; then
    CHUNKING_DLQ_BASELINE=$(qa_retrieval_dlq_depth "$CHUNKING_DLQ_ARN")
  fi
  echo "Captured pre-deploy start: ${START_TS}"
  echo "Captured pre-deploy DLQ baselines: transform=${TRANSFORM_DLQ_BASELINE}" \
    "bm25=${BM25_DLQ_BASELINE} chunking=${CHUNKING_DLQ_BASELINE}"
fi

# ── 2. Assume the CDK deploy role and deploy. The SourceReprocessTrigger
#       custom resource (if the etlCodeHash changed) fires DURING this call,
#       before it returns — this is exactly why step 1 must precede it. ─────
log_section "Deploy: ${STACK_NAME}"
assume_deploy_role "$CDK_DEPLOY_ROLE_ARN"

EXTRA_CONTEXT=()
if [[ -n "${ETL_IMAGE_TAG_OVERRIDE:-}" ]]; then
  log_kv "Image override:" "$ETL_IMAGE_TAG_OVERRIDE"
  EXTRA_CONTEXT+=("etlImageTag=${ETL_IMAGE_TAG_OVERRIDE}")
fi

if ! STACK_REVISION_BEFORE=$(_stack_revision); then
  echo "Refusing deployment before mutation: no-op detection is unavailable." >&2
  exit 1
fi
cdk_deploy_stack "$STACK_NAME" "$ENV_NAME" "$OUTPUTS_FILE" "${EXTRA_CONTEXT[@]}"
if ! STACK_REVISION_AFTER=$(_stack_revision); then
  echo "Post-deploy stack revision is unavailable — retaining fail-safe readiness." >&2
  STACK_REVISION_AFTER=""
fi

STACK_DEPLOYMENT_CHANGED="true"
if [[ -n "$STACK_REVISION_BEFORE" \
  && "$STACK_REVISION_BEFORE" = "$STACK_REVISION_AFTER" ]]; then
  STACK_DEPLOYMENT_CHANGED="false"
  echo "CDK stack revision unchanged — deployment was a no-op."
else
  echo "CDK stack revision changed or could not be compared — readiness required."
fi

# ── 3. Re-assume the readiness role and run the gate with the PRE-DEPLOY
#       baseline/timestamp — never re-captured after the deploy. ────────────
log_section "Post-deploy: readiness gate"
assume_deploy_role "$ETL_READINESS_ROLE_ARN"

if [ "$STACK_DEPLOYMENT_CHANGED" = "true" ]; then
  READINESS_ARGS=()
  if [ -n "$START_TS" ]; then
    READINESS_ARGS+=(
      --start-ts "$START_TS"
      --transform-dlq-baseline "$TRANSFORM_DLQ_BASELINE"
      --bm25-dlq-baseline "$BM25_DLQ_BASELINE"
    )
    if [ -n "$CHUNKING_DLQ_ARN" ]; then
      READINESS_ARGS+=(--chunking-dlq-baseline "$CHUNKING_DLQ_BASELINE")
    fi
  fi
  # Optional timing overrides — unset in normal CI (etl-readiness-check.sh's
  # own defaults apply). Tests use these to shorten the polling phases.
  [ -n "${ETL_READINESS_GRACE_SECONDS:-}" ] && READINESS_ARGS+=(--grace-seconds "$ETL_READINESS_GRACE_SECONDS")
  [ -n "${ETL_READINESS_POLL_INTERVAL_SECONDS:-}" ] && READINESS_ARGS+=(--poll-interval-seconds "$ETL_READINESS_POLL_INTERVAL_SECONDS")
  [ -n "${ETL_READINESS_CONSECUTIVE_EMPTY:-}" ] && READINESS_ARGS+=(--consecutive-empty "$ETL_READINESS_CONSECUTIVE_EMPTY")
  [ -n "${ETL_READINESS_TIMEOUT_SECONDS:-}" ] && READINESS_ARGS+=(--timeout-seconds "$ETL_READINESS_TIMEOUT_SECONDS")

  "${SCRIPT_DIR}/../verify/etl-readiness-dev.sh" "${READINESS_ARGS[@]}"
else
  echo "⏭ no CloudFormation update — no ingestion expected; skipping readiness"
  echo "READINESS_RESULT=no-stack-change"
fi

# ── 4. Explicit BM25 rebuild — gated on ETL_IMAGE_CHANGED (#626). The
#       tokenizer/builder code lives in backend/src/bm25_shared, an IMAGE
#       input; a stack-only deploy cannot change it, so this redundant direct
#       invoke (with its own NumChunks>0 assertion) is skipped. This does NOT
#       suppress BM25 rebuilding outright: the corpus reprocess triggered by
#       cdk_deploy_stack above (unchanged, pre-existing #590 behavior — see
#       etl-kb-stack.ts's etlCodeHash) still re-emits docs/*.md, which still
#       drives the existing S3-event → SQS → Lambda BM25 rebuild path; that
#       path's failures are still caught by the readiness gate's BM25 DLQ
#       check above. #626 only removes the extra, redundant explicit call. ──
if [ "$STACK_DEPLOYMENT_CHANGED" = "false" ]; then
  echo "⏭ no CloudFormation update — skipping explicit BM25 rebuild"
elif [ "${ETL_IMAGE_CHANGED:-true}" = "true" ]; then
  bash "${SCRIPT_DIR}/../util/bm25-rebuild.sh" "$ENV_NAME"
else
  echo "⏭ no ETL image change — skipping redundant explicit BM25 rebuild" \
    "(event-driven rebuild from the reprocess, if any, still applies)"
fi

# ── 5. Write the fingerprint LAST — only after deploy + readiness (+ bm25
#       when it ran) succeed, so a failed/partial run re-triggers next time
#       instead of being skipped. #626 Decision D1 (Option B): both
#       fingerprints are stored as ONE composite JSON value in the EXISTING
#       /dev/renate/etl-code-fingerprint parameter — a single atomic put,
#       matching #590's original write-last guarantee (no torn state between
#       two separate parameter writes) and requiring no renate/bootstrap IAM
#       change (same exact-name grant as before). Skipped entirely if BOTH
#       fingerprint env vars are absent (etl-changed:dev never ran) —
#       preserves the existing re-trigger-on-skip semantics.
if [ -n "${ETL_IMAGE_FINGERPRINT:-}" ] || [ -n "${ETL_STACK_FINGERPRINT:-}" ]; then
  FINGERPRINT_JSON=$(jq -n \
    --arg image "${ETL_IMAGE_FINGERPRINT:-}" \
    --arg stack "${ETL_STACK_FINGERPRINT:-}" \
    '{image: $image, stack: $stack}')
  aws ssm put-parameter --name "/${ENV_NAME}/renate/etl-code-fingerprint" \
    --value "$FINGERPRINT_JSON" --type String --overwrite
fi

log_done
