#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:?Usage: notify-rocketchat.sh <env> [deployment|rollback]}"
EVENT_KIND="${2:-deployment}"
case "$EVENT_KIND" in
  deployment | rollback) ;;
  *) echo "ERROR: notification event must be deployment or rollback" >&2; exit 2 ;;
esac

# Escape backslash and double-quote so user-controlled values don't break the JSON body.
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# QA: CHATBOT_VERSION comes from the qa-retrieval.env dotenv artifact.
# Preprod: DEPLOY_VERSION comes from the deploy-version.env dotenv artifact.
if [[ "$EVENT_KIND" == rollback ]]; then
  VERSION=$(json_escape "${EXPECTED_TARGET_RELEASE_ID:-unknown}")
else
  VERSION=$(json_escape "${CHATBOT_VERSION:-${DEPLOY_VERSION:-unknown}}")
fi
ACTOR=$(json_escape "${GITLAB_USER_NAME:-GitLab CI}")

# \n is intentional: bash does not expand it in double-quoted strings, but the
# JSON parser on the receiving end interprets \n as a newline character.
if [[ "$EVENT_KIND" == rollback ]]; then
  MSG="# [${ENV_NAME}] Retrieval rollback → \`${VERSION}\`"
else
  MSG="# [${ENV_NAME}] Deployment \`${VERSION}\`"
fi
if [[ -n "${DATA_ARTIFACT_VERSION:-}" ]]; then
  MSG="${MSG}\nData: \`${DATA_ARTIFACT_VERSION}\`"
fi
if [[ -n "${ETL_VERSION:-}" ]]; then
  MSG="${MSG}\nETL: \`${ETL_VERSION}\`"
fi
MSG="${MSG}\nBy: ${ACTOR}"
MSG="${MSG}\nPipeline: ${CI_PIPELINE_URL}"

curl -sf --max-time 15 \
  -H "X-Auth-Token: $ROCKETCHAT_AUTH_TOKEN" \
  -H "X-User-Id: $ROCKETCHAT_USER_ID" \
  -H "Content-Type: application/json" \
  -d "{\"channel\": \"$ROCKETCHAT_DEPLOYMENTS_CHANNEL\", \"text\": \"${MSG}\"}" \
  "$ROCKETCHAT_URL/api/v1/chat.postMessage"
