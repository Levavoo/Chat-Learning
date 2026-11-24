#!/usr/bin/env bash
set -euo pipefail
# deploy-etl-dev.sh
# Deploys renate-etl-kb-dev. The ETL Lambda image tag is resolved by CDK from
# SSM /dev/renate/etl-image-tag (valueForTypedStringParameterV2) — this script
# does NOT call ensure_ecr_image / promote_image_tag_ssm: that ECR/SSM handling
# belongs to build-etl-image:dev, and the dev CDK-deploy role deliberately
# lacks ecr:DescribeImages / ssm:PutParameter (mirrors deploy-env.sh dev path).
#
# ETL_IMAGE_TAG_OVERRIDE (optional): manual rollback to a prior v<semver> image
# (e.g. /dev/renate/etl-image-tag-previous). Unset in normal CI — SSM drives
# the tag. When set, passes --context etlImageTag=<value> so CDK uses it
# instead of the SSM lookup (synth stays valid either way — D4).
#
# Required CI variables: GITLAB_OIDC_TOKEN, CI_JOB_ID, CDK_DEPLOY_ROLE_ARN_DEV.
# Uses --outputs-file so cdk_deploy_stack's CloudFormation describe-stacks
# fallback is not exercised — the dev deploy role need not have
# cloudformation:DescribeStacks on renate-etl-kb-dev.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
OUTPUTS_FILE="${REPO_ROOT}/outputs-etl.json"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

ENV="dev"
STACK="renate-etl-kb-${ENV}"
ROLE_ARN="${CDK_DEPLOY_ROLE_ARN_DEV:?CDK_DEPLOY_ROLE_ARN_DEV is required but not set}"

log_section "deploy-etl: ${ENV}"
log_kv "Stack:" "$STACK"

assume_deploy_role "$ROLE_ARN"

EXTRA_CONTEXT=()
if [[ -n "${ETL_IMAGE_TAG_OVERRIDE:-}" ]]; then
  log_kv "Image override:" "$ETL_IMAGE_TAG_OVERRIDE"
  EXTRA_CONTEXT+=("etlImageTag=${ETL_IMAGE_TAG_OVERRIDE}")
fi

cdk_deploy_stack "$STACK" "$ENV" "$OUTPUTS_FILE" "${EXTRA_CONTEXT[@]}"
