#!/usr/bin/env bash
# QA retrieval authentication and image-origin helpers.

# shellcheck source=qa-retrieval-common.sh disable=SC1091
source "${BASH_SOURCE[0]%/*}/qa-retrieval-common.sh"

qa_retrieval_assume_oidc() {
  local role_arn="$1" session_suffix="$2" credentials
  : "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
  : "${CI_JOB_ID:?CI_JOB_ID is required}"
  credentials=$(aws sts assume-role-with-web-identity \
    --role-arn "$role_arn" \
    --role-session-name "gitlab-${CI_JOB_ID}-${session_suffix}" \
    --web-identity-token "$GITLAB_OIDC_TOKEN" \
    --duration-seconds 7200 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text)
  read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN <<<"$credentials"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  [[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" && -n "$AWS_SESSION_TOKEN" ]] || {
    qa_retrieval_fail "could not assume ${role_arn}"
    return 1
  }
  aws sts get-caller-identity --output json >/dev/null
}

# qa_retrieval_assert_image_recoverable <label> <repo> <digest>
# Assert an immutable image digest is still present in the image-origin registry.
#
# A promotion must never move into a state it cannot be rolled back out of. The
# INCOMING images must exist (or the transaction fails mid-deploy, after
# mutation), and the OUTGOING images must still exist (or a #493 selector-flip
# rollback would restore a manifest whose Lambda image has been reaped). All CDK
# promotion and automatic-rollback calls receive these digests directly. Merely
# checking a digest while deploying a mutable/reassignable tag would not prove
# the bytes actually deployed, so callers must not convert the digest back to a
# tag after this check.
#
# Requires the image-metadata reader role to be the active credential (dev ECR
# read). Fails closed on a malformed digest or an absent image.
qa_retrieval_assert_image_recoverable() {
  local label="$1" repo="$2" digest="$3" err_file rc=0
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    qa_retrieval_fail "${label} image digest is malformed: ${digest}"
    return 1
  }
  err_file=$(mktemp)
  aws ecr describe-images \
    --registry-id "$RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID" \
    --repository-name "$repo" \
    --image-ids imageDigest="$digest" \
    --region "${AWS_REGION:-eu-central-1}" >/dev/null 2>"$err_file" || rc=$?

  if [[ "$rc" -eq 0 ]]; then
    rm -f "$err_file"
    printf '  %-34s %s\n' "${label} recoverable:" "${repo}@${digest}" >&2
    return 0
  fi

  # "Absent" and "not allowed to look" are completely different facts and must
  # never be conflated: treating a missing IAM grant as a missing image blocks
  # every promotion, and treating a missing image as a permission problem would
  # promote into a state with no rollback. Classify explicitly.
  if grep -qiE 'ImageNotFound|RepositoryNotFound|InvalidParameter' "$err_file"; then
    sed 's/^/    /' "$err_file" >&2
    rm -f "$err_file"
    qa_retrieval_fail \
      "${label} image ${repo}@${digest} is not recoverable from registry" \
      "${RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID}; refusing to promote into a state" \
      "that could not be rolled back"
    return 1
  fi

  if grep -qiE 'AccessDenied|not authorized' "$err_file"; then
    # Degrade loudly rather than blocking: the caller's role cannot read the
    # origin registry, so recoverability is UNVERIFIED — the same position every
    # promotion was in before this check existed. Grant ecr:DescribeImages on
    # the chatbot/ETL repos to make this gate authoritative (preprod's promotion
    # role already has it via DevEcrPull; qa's does not).
    printf '  %-34s %s\n' "${label} UNVERIFIED:" \
      "${repo}@${digest} — caller may not call ecr:DescribeImages" >&2
    sed 's/^/    /' "$err_file" >&2
    rm -f "$err_file"
    return 0
  fi

  sed 's/^/    /' "$err_file" >&2
  rm -f "$err_file"
  qa_retrieval_fail \
    "could not determine whether ${label} image ${repo}@${digest} is" \
    "recoverable (unexpected ECR error above); failing closed"
  return 1
}

# qa_retrieval_resolve_stack_image_digest <stack>
# Resolve the exact digest currently running in every image-backed Lambda in a
# chatbot stack. All such Lambdas are deployed from one chatbot image; a mixed
# set is therefore drift and fails closed.
#
# This is also how a schema-v2 baseline (which predates
# chatbot_image_digest) acquires a truthful automatic-rollback coordinate:
# inspect the live Lambda, then preserve and deploy that exact digest. No ECR
# tag is used as a proxy for the running bytes.
qa_retrieval_resolve_stack_image_digest() {
  local stack_name="$1" function_names function_name details package_type
  local resolved_uri digest expected_digest=""
  local image_functions=0

  function_names=$(qa_retrieval_stack_lambda_functions "$stack_name") || return 1

  while IFS= read -r function_name; do
    [[ -n "$function_name" ]] || continue
    details=$(aws lambda get-function --function-name "$function_name" \
      --output json) || {
      qa_retrieval_fail "could not inspect Lambda ${function_name}"
      return 1
    }
    package_type=$(jq -r '.Configuration.PackageType // empty' <<<"$details")
    [[ "$package_type" == "Image" ]] || continue
    resolved_uri=$(jq -r '.Code.ResolvedImageUri // empty' <<<"$details")
    digest="${resolved_uri##*@}"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      qa_retrieval_fail \
        "Lambda ${function_name} has no immutable ResolvedImageUri digest"
      return 1
    }
    if [[ -n "$expected_digest" && "$digest" != "$expected_digest" ]]; then
      qa_retrieval_fail \
        "chatbot stack ${stack_name} runs mixed image digests:" \
        "${expected_digest} and ${digest}"
      return 1
    fi
    expected_digest="$digest"
    image_functions=$((image_functions + 1))
  done < <(printf '%s\n' "$function_names")

  [[ "$image_functions" -gt 0 ]] || {
    qa_retrieval_fail \
      "chatbot stack ${stack_name} has no image-backed Lambda to recover"
    return 1
  }
  printf '%s\n' "$expected_digest"
}


