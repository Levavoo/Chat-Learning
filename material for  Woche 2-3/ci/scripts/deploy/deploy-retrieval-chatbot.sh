#!/usr/bin/env bash
# Deploy the exact chatbot image after candidate readiness, without switching
# selectors. Environment-parameterized (#643): the same code serves qa and
# preprod; stack, CDK env context, promotion role, and artifact basenames come
# from retrieval-environment.mjs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:?Usage: deploy-retrieval-chatbot.sh <qa|preprod|prod>}"

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
qa_retrieval_init_env "$ENV"

CANDIDATE_ENV="${CANDIDATE_ENV:-${REPO_ROOT}/${ENV}-candidate.env}"
ACTIVE_BEFORE_FILE="${ACTIVE_BEFORE_FILE:-${REPO_ROOT}/${ENV}-active-before.json}"
PREVIOUS_BEFORE_FILE="${PREVIOUS_BEFORE_FILE:-${REPO_ROOT}/${ENV}-previous-before.json}"
OUTPUTS_FILE="${OUTPUTS_FILE:-${REPO_ROOT}/${ENV}-chatbot-outputs.json}"
CHATBOT_STACK="$RETRIEVAL_CHATBOT_STACK"

[[ -f "$CANDIDATE_ENV" ]] || { echo "Missing ${CANDIDATE_ENV}" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CANDIDATE_ENV"

qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"
qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"

(
  cd "$REPO_ROOT/cdk"
  npx cdk deploy "$CHATBOT_STACK" \
    --app "npx ts-node --prefer-ts-exts bin/infrastructure.ts" \
    --context "env=${ENV}" \
    --context "etlImageTag=${ETL_IMAGE_DIGEST}" \
    --context "retrievalCandidateSlot=${CANDIDATE_SLOT}" \
    --context "blueEtlImageTag=${BLUE_ETL_IMAGE_DIGEST}" \
    --context "greenEtlImageTag=${GREEN_ETL_IMAGE_DIGEST}" \
    --context "chatbotImageTag=${CHATBOT_IMAGE_DIGEST}" \
    --require-approval never \
    --outputs-file "$OUTPUTS_FILE"
)

IMAGE_FUNCTIONS=0
# Captured before the loop so a listing failure aborts instead of silently
# yielding zero functions (see qa_retrieval_stack_lambda_functions for why the
# complete paginated listing is mandatory: #671).
CHATBOT_FUNCTIONS=$(qa_retrieval_stack_lambda_functions "$CHATBOT_STACK")
while IFS= read -r function_name; do
  [[ -n "$function_name" ]] || continue
  package_type=$(aws lambda get-function --function-name "$function_name" \
    --query Configuration.PackageType --output text)
  [[ "$package_type" == Image ]] || continue
  resolved=$(aws lambda get-function --function-name "$function_name" \
    --query Code.ResolvedImageUri --output text)
  [[ "$resolved" == *@"$CHATBOT_IMAGE_DIGEST" ]] || qa_retrieval_fail \
    "${function_name} does not run promoted chatbot digest ${CHATBOT_IMAGE_DIGEST}"
  IMAGE_FUNCTIONS=$((IMAGE_FUNCTIONS + 1))
done < <(printf '%s\n' "$CHATBOT_FUNCTIONS")
[[ "$IMAGE_FUNCTIONS" -ge 2 ]] || qa_retrieval_fail \
  "expected at least two image-backed chatbot Lambdas, found ${IMAGE_FUNCTIONS}"

qa_retrieval_assert_selectors_unchanged "$ACTIVE_BEFORE_FILE" "$PREVIOUS_BEFORE_FILE"
echo "${ENV} chatbot ${CHATBOT_VERSION} deployed; retrieval selector remains unchanged."
