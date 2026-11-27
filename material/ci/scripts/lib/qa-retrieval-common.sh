#!/usr/bin/env bash
# Shared primitives for QA retrieval promotion helpers.

# The QA corpus has roughly 3,400 objects. Eight AWS CLI workers cannot finish
# the mandatory read/write/read-back retention passes inside the candidate job
# timeout on the CI runner.
QA_RETENTION_CONCURRENCY="${QA_RETENTION_CONCURRENCY:-24}"

qa_retrieval_fail() {
  echo "qa-retrieval: $*" >&2
  return 1
}

# CloudFormation's describe-stack-resources response is limited to 100
# resources. The AWS CLI auto-paginates list-stack-resources, so filter its
# complete response locally before inspecting chatbot Lambdas.
qa_retrieval_stack_lambda_functions() {
  local stack_name="${1:?qa_retrieval_stack_lambda_functions: <stack> is required}"
  local resources
  resources=$(aws cloudformation list-stack-resources \
    --stack-name "$stack_name" --output json) || {
    qa_retrieval_fail "could not list Lambda functions for stack ${stack_name}"
    return 1
  }
  jq -r '
    .StackResourceSummaries[]
    | select(.ResourceType == "AWS::Lambda::Function")
    | .PhysicalResourceId
  ' <<<"$resources" || {
    qa_retrieval_fail "could not parse stack resource listing for ${stack_name}"
    return 1
  }
}

# Resolve the per-environment retrieval config once and populate the
# RETRIEVAL_* variables the shared helpers and entry scripts consume, so one
# generalized code path serves every manifest-managed environment (qa,
# preprod) instead of a forked preprod copy (#643/#619). All values come from
# retrieval-environment.mjs — the single source of per-env truth. Fail-closed:
# an unknown environment or a missing field aborts before any AWS call.
qa_retrieval_init_env() {
  local env="${1:?qa_retrieval_init_env: <env> is required}" config field
  config=$(node "${REPO_ROOT}/.gitlab/ci/scripts/lib/node/retrieval-environment.mjs" json "$env") || {
    qa_retrieval_fail "could not resolve retrieval environment config for ${env}"
    return 1
  }
  for field in environment accountId sourceAccountId sourceReaderRoleArn \
    imageMetadataReaderRoleArn imageMetadataAccountId rawSourceMode \
    promotionRoleArn etlStackName chatbotStackName retrievalBasePath \
    activeSelector previousSelector healthStateParameter \
    rollbackDegradedParameter artifactPrefix metricNamespace resourceGroup; do
    jq -e --arg f "$field" 'has($f) and (.[$f] != null) and (.[$f] != "")' \
      <<<"$config" >/dev/null || {
      qa_retrieval_fail "retrieval environment config for ${env} is missing field ${field}"
      return 1
    }
  done
  RETRIEVAL_ENVIRONMENT=$(jq -r .environment <<<"$config")
  RETRIEVAL_ACCOUNT_ID=$(jq -r .accountId <<<"$config")
  RETRIEVAL_SOURCE_ACCOUNT_ID=$(jq -r .sourceAccountId <<<"$config")
  RETRIEVAL_SOURCE_READER_ROLE_ARN=$(jq -r .sourceReaderRoleArn <<<"$config")
  RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN=$(jq -r .imageMetadataReaderRoleArn <<<"$config")
  RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID=$(jq -r .imageMetadataAccountId <<<"$config")
  RETRIEVAL_RAW_SOURCE_MODE=$(jq -r .rawSourceMode <<<"$config")
  # Upstream discovery applies to downstream mode only, and is mandatory there:
  # a downstream promotion that cannot resolve its upstream must not fall back
  # to guessing a bucket. Origin mode carries nulls, normalized to empty here.
  RETRIEVAL_UPSTREAM_ENVIRONMENT=$(jq -r '.upstreamEnvironment // ""' <<<"$config")
  RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER=$(jq -r '.upstreamSourceBucketParameter // ""' <<<"$config")
  if [[ "$RETRIEVAL_RAW_SOURCE_MODE" == downstream ]]; then
    for field in upstreamEnvironment upstreamSourceBucketParameter; do
      jq -e --arg f "$field" '(.[$f] // "") != ""' <<<"$config" >/dev/null || {
        qa_retrieval_fail \
          "retrieval environment config for ${env} is downstream but declares no ${field}"
        return 1
      }
    done
  fi
  RETRIEVAL_PROMOTION_ROLE_ARN=$(jq -r .promotionRoleArn <<<"$config")
  RETRIEVAL_ETL_STACK=$(jq -r .etlStackName <<<"$config")
  RETRIEVAL_CHATBOT_STACK=$(jq -r .chatbotStackName <<<"$config")
  RETRIEVAL_BASE_PATH=$(jq -r .retrievalBasePath <<<"$config")
  RETRIEVAL_ACTIVE_SELECTOR=$(jq -r .activeSelector <<<"$config")
  RETRIEVAL_PREVIOUS_SELECTOR=$(jq -r .previousSelector <<<"$config")
  RETRIEVAL_HEALTH_STATE_PARAMETER=$(jq -r .healthStateParameter <<<"$config")
  RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER=$(jq -r .rollbackDegradedParameter <<<"$config")
  RETRIEVAL_ARTIFACT_PREFIX=$(jq -r .artifactPrefix <<<"$config")
  RETRIEVAL_METRIC_NAMESPACE=$(jq -r .metricNamespace <<<"$config")
  RETRIEVAL_RESOURCE_GROUP=$(jq -r .resourceGroup <<<"$config")
  export RETRIEVAL_ENVIRONMENT RETRIEVAL_ACCOUNT_ID RETRIEVAL_SOURCE_ACCOUNT_ID \
    RETRIEVAL_SOURCE_READER_ROLE_ARN RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN \
    RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID RETRIEVAL_RAW_SOURCE_MODE \
    RETRIEVAL_UPSTREAM_ENVIRONMENT RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER \
    RETRIEVAL_PROMOTION_ROLE_ARN RETRIEVAL_ETL_STACK RETRIEVAL_CHATBOT_STACK \
    RETRIEVAL_BASE_PATH RETRIEVAL_ACTIVE_SELECTOR RETRIEVAL_PREVIOUS_SELECTOR \
    RETRIEVAL_HEALTH_STATE_PARAMETER RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER \
    RETRIEVAL_ARTIFACT_PREFIX RETRIEVAL_METRIC_NAMESPACE RETRIEVAL_RESOURCE_GROUP
}

qa_retrieval_required_ssm() {
  local name="$1" value
  value=$(aws ssm get-parameter --name "$name" --query Parameter.Value --output text) || {
    qa_retrieval_fail "required SSM parameter ${name} is missing"
    return 1
  }
  [[ -n "$value" && "$value" != "None" ]] || {
    qa_retrieval_fail "required SSM parameter ${name} is empty"
    return 1
  }
  printf '%s\n' "$value"
}


