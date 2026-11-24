#!/usr/bin/env bash
# CI wrapper for the #642 protected selector-activation job. Assumes the preprod
# retrieval-promotion role through the GitLab OIDC trust chain, then creates the
# baseline active-manifest selector. Kept as a script so the assume-role call
# stays out of the pipeline YAML (line-length lint) and mirrors how the #641
# foundation jobs shell out.
set -euo pipefail

: "${PREPROD_RETRIEVAL_PROMOTION_ROLE_ARN:?PREPROD_RETRIEVAL_PROMOTION_ROLE_ARN is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

creds="$(aws sts assume-role-with-web-identity \
  --role-arn "$PREPROD_RETRIEVAL_PROMOTION_ROLE_ARN" \
  --role-session-name "gitlab-${CI_JOB_ID}-blue-baseline-selector" \
  --web-identity-token "$GITLAB_OIDC_TOKEN" \
  --duration-seconds 3600 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)"
read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN <<<"$creds"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

exec "${REPO_ROOT}/scripts/activate-blue-baseline-selector.sh" \
  --env preprod \
  --version 1.83.3 \
  --data-artifact-version v1.83.3-preprod-blue-baseline \
  --etl-version v1.83.3-preprod-blue-baseline \
  --execute
