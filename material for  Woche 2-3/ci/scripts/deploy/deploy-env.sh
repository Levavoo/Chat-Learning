#!/usr/bin/env bash
set -euo pipefail
# deploy-env.sh <env>
# Generic CDK deploy: derives all parameters from the env name by convention.
#
# Convention table:
#   env      role var                  stack                    SSM prefix      pin file
#   dev      CDK_DEPLOY_ROLE_ARN_DEV   renate-chatbot-dev       /dev/renate     deployments/dev/version.yaml
#   qa       CDK_DEPLOY_ROLE_ARN_QA    renate-chatbot-qa        /qa/renate      deployments/qa/version.yaml
#   preprod  CDK_DEPLOY_ROLE_ARN_PREPROD renate-chatbot-preprod /preprod/renate deployments/preprod/version.yaml
#   prod     CDK_DEPLOY_ROLE_ARN_PROD  renate-chatbot-prod      /prod/renate    deployments/prod/version.yaml
#
# Required CI variables: GITLAB_OIDC_TOKEN, CI_JOB_ID, CDK_DEPLOY_ROLE_ARN_<ENV>
# For all envs: deployments/<env>/version.yaml must exist with version/data_artifact_version/etl_version.
# dev skips the ECR-existence check and SSM image-tag write — build-lambda
# already pushed the image and wrote /dev/renate/image-tag, and the dev
# CDK-deploy role intentionally lacks ecr:DescribeImages / ssm:PutParameter.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
OUTPUTS_FILE="${REPO_ROOT}/outputs.json"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

ENV="${1:-}"
_deploy_validate_env "$ENV" || exit 1

if [[ "$ENV" == "qa" ]]; then
  echo "Direct QA deployment is disabled by #492. Merge an exact three-line QA promotion pin and let the qa-retrieval-promotion child pipeline deploy code, build the inactive slot, and switch the manifest coherently." >&2
  exit 1
fi
if [[ "$ENV" == "preprod" ]]; then
  echo "Direct preprod deployment is disabled (#641/#643)." >&2
  echo "Use the reviewed preprod-retrieval-promotion transaction (explicit" >&2
  echo "development approval for now; server-enforced four-eyes before final" >&2
  echo "rollout) so the mirrored deploy-preprod bridge deploys code, builds the" >&2
  echo "inactive slot, and switches the manifest coherently. Foundation/config-" >&2
  echo "only changes use their own protected web-task paths." >&2
  exit 1
fi
if [[ "$ENV" == "prod" ]]; then
  echo "Direct prod deployment is disabled (#726)." >&2
  echo "Use the reviewed prod-retrieval-promotion transaction so the mirrored" >&2
  echo "deploy-prod bridge deploys code, builds the inactive slot, and switches" >&2
  echo "the manifest coherently. Foundation/config-only changes use their own" >&2
  echo "protected web-task paths." >&2
  exit 1
fi

# Derive parameters from env name by convention
ENV_UPPER="${ENV^^}"
ROLE_VAR="CDK_DEPLOY_ROLE_ARN_${ENV_UPPER}"
STACK="renate-chatbot-${ENV}"
PIN_FILE="${REPO_ROOT}/deployments/${ENV}.yaml"
# all envs use a subdirectory layout: deployments/<env>/version.yaml
case "$ENV" in
  dev | qa | preprod | prod) PIN_FILE="${REPO_ROOT}/deployments/${ENV}/version.yaml" ;;
esac

# Resolve role ARN — fail fast if CI variable not set
ROLE_ARN="${!ROLE_VAR:?${ROLE_VAR} is required but not set}"

# Resolve version from pin file for all envs.
[[ -f "$PIN_FILE" ]] || { echo "Pin file not found: $PIN_FILE" >&2; exit 1; }
validate_promotion_pin "$PIN_FILE" || exit 1
VERSION=$(read_pin_version "$PIN_FILE")
[[ -n "$VERSION" ]] || { echo "Could not parse version from $PIN_FILE" >&2; exit 1; }

CDK_CONTEXT=()

# Expose the resolved version to the caller's shell (this script runs as a
# separate process, so plain exports here would not survive past `exec`).
# The deployment-page render step sources this to set RENDER_VERSION,
# guaranteeing the wiki always reflects what was actually deployed — the same
# value used below for the ECR check and SSM tag — rather than re-deriving it
# from a different source (e.g. cocogitto's NEW_TAG, which is empty on
# promotion-only pipelines).
echo "DEPLOY_VERSION=${VERSION}" > "${REPO_ROOT}/deploy-version.env"

log_section "deploy-env: ${ENV}"
log_kv "Version:" "$VERSION"
log_kv "Stack:" "$STACK"
log_kv "Role var:" "$ROLE_VAR"

# Downstream envs may only deploy a version that was promoted through qa.
case "$ENV" in
  preprod | prod)
    assert_pin_on_qa "$PIN_FILE" "${REPO_ROOT}/deployments/qa/version.yaml"
    ;;
esac

assume_deploy_role "$ROLE_ARN"

# dev receives its image and /dev/renate/image-tag from build-lambda, which
# runs in the cocogitto pipeline before bump-dev-pin writes the version pin.
# The dev CDK-deploy role intentionally lacks ecr:DescribeImages /
# ssm:PutParameter — build-lambda owns those writes via the ecr-push role.
if [[ "$ENV" != "dev" ]]; then
  ensure_ecr_image "831926590742" "renate-chat-lambda" "$VERSION"
  promote_image_tag_ssm "$ENV" "$VERSION"
fi

cdk_deploy_stack "$STACK" "$ENV" "$OUTPUTS_FILE" "${CDK_CONTEXT[@]}"
