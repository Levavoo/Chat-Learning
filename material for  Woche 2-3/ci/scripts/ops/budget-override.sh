#!/usr/bin/env bash
set -euo pipefail
# budget-override.sh <env> [aws-profile]
#
# Emergency operator override of budget-triggered maintenance (#579).
#
# Budget pacing takes the service offline when cumulative spend exceeds the
# prorated monthly curve, and maintenance-switch.sh deliberately refuses to
# clear that state. This script is the documented escape hatch: it clears the
# reason to `none` and brings the service back online in one step.
#
# Using it means accepting that spend continues above the pacing curve until
# the next scheduled check re-evaluates — which, if still over, will take the
# service offline again. Prefer waiting for the next check unless there is a
# reason the outage costs more than the overspend.
#
# Every use publishes an SNS notification: this is an audit trail, not a
# silent lever.

ENV="${1:-}"
AWS_PROFILE_ARG="${2:-}"

case "$ENV" in
  dev|qa|preprod|prod) ;;
  *)
    echo "budget-override: unknown env '${ENV}' (allowed: dev qa preprod prod)" >&2
    echo "usage: budget-override.sh <env> [aws-profile]" >&2
    exit 1
    ;;
esac

AWS_ARGS=()
if [[ -n "$AWS_PROFILE_ARG" ]]; then
  AWS_ARGS+=(--profile "$AWS_PROFILE_ARG")
fi
REGION="${AWS_REGION:-eu-central-1}"
AWS_ARGS+=(--region "$REGION")

STACK="renate-chatbot-${ENV}"
REASON_PARAM="/${ENV}/renate/maintenance-reason"

_stack_output() { # <jmespath query>
  aws cloudformation describe-stacks "${AWS_ARGS[@]}" \
    --stack-name "$STACK" --query "$1" --output text
}

CURRENT_REASON="$(aws ssm get-parameter "${AWS_ARGS[@]}" \
  --name "$REASON_PARAM" --query 'Parameter.Value' --output text 2>/dev/null || echo "none")"
[[ "$CURRENT_REASON" == "None" || -z "$CURRENT_REASON" ]] && CURRENT_REASON="none"

echo "Environment:      ${ENV}"
echo "Current reason:   ${CURRENT_REASON}"

if [[ "$CURRENT_REASON" != "budget" ]]; then
  echo
  echo "Nothing to override — maintenance reason is '${CURRENT_REASON}', not 'budget'."
  if [[ "$CURRENT_REASON" == "manual" ]]; then
    echo "This is a manual maintenance window. Clear it the normal way:"
    echo "  set maintenance: false in deployments/${ENV}/maintenance.yaml and merge."
  fi
  exit 0
fi

cat <<WARN

⚠️  This overrides budget pacing protection for ${ENV}.

The service was taken offline because cumulative spend exceeded the prorated
monthly budget. Bringing it back online now means spend continues above that
curve. The next scheduled budget check will take it offline again if the
overspend persists.

WARN

printf "Type 'override' to confirm: "
read -r ack
if [[ "$ack" != "override" ]]; then
  echo "Aborted — no changes made."
  exit 1
fi

KVS_ARN="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendMaintenanceModeStoreArn')].OutputValue | [0]")"
CHAT_FN="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'LambdaBackendChatHandlerName')].OutputValue | [0]")"
DIST_ID="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendCloudFrontDistributionId')].OutputValue | [0]")"
TOPIC_ARN="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'AlertingAlertTopicArn')].OutputValue | [0]")"

for pair in "KVS_ARN:${KVS_ARN}" "CHAT_FN:${CHAT_FN}" "DIST_ID:${DIST_ID}"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  if [[ -z "$value" || "$value" == "None" ]]; then
    echo "budget-override: could not resolve ${name} from ${STACK} outputs" >&2
    exit 1
  fi
done

# Edge first, same ordering as maintenance-switch.sh: users see a working page
# before the API starts accepting traffic again.
ETAG="$(aws cloudfront-keyvaluestore describe-key-value-store "${AWS_ARGS[@]}" \
  --kvs-arn "$KVS_ARN" --query ETag --output text)"
aws cloudfront-keyvaluestore update-keys "${AWS_ARGS[@]}" \
  --kvs-arn "$KVS_ARN" --if-match "$ETAG" \
  --puts "Key=maintenance,Value=off" > /dev/null
echo "KVS flag:         maintenance=off"

# Invalidate CloudFront edge cache — cached maintenance page responses won't
# re-invoke the viewer-request function until they expire or are invalidated.
# CACHING_OPTIMIZED has a 24h default TTL, so without this the stale page
# persists long after the KVS flag flips.
aws cloudfront create-invalidation "${AWS_ARGS[@]}" \
  --distribution-id "$DIST_ID" --paths "/*" > /dev/null
echo "CloudFront:       invalidation submitted (/*)"

aws lambda delete-function-concurrency "${AWS_ARGS[@]}" --function-name "$CHAT_FN"
echo "ChatHandler:      concurrency restored"

aws ssm put-parameter "${AWS_ARGS[@]}" \
  --name "$REASON_PARAM" --value none --type String --overwrite > /dev/null
echo "Reason:           none"

if [[ -n "$TOPIC_ARN" && "$TOPIC_ARN" != "None" ]]; then
  OPERATOR="$(aws sts get-caller-identity "${AWS_ARGS[@]}" --query Arn --output text 2>/dev/null || echo "unknown")"
  aws sns publish "${AWS_ARGS[@]}" \
    --topic-arn "$TOPIC_ARN" \
    --subject "[${ENV}] Budget pacing OVERRIDDEN by operator" \
    --message "Budget-triggered maintenance was manually cleared.

Environment: ${ENV}
Operator:    ${OPERATOR}
Time:        $(date -u '+%Y-%m-%dT%H:%M:%SZ')

Spend remains above the prorated budget curve. The next scheduled budget
check will re-evaluate and may take the service offline again." > /dev/null
  echo "SNS:              override notification sent"
fi

echo
echo "✅ Service restored. Budget pacing will re-evaluate at the next scheduled check."
