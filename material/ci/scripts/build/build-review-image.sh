#!/usr/bin/env bash
set -euo pipefail

# Required environment variables (provided by CI job or caller)
: "${ECR_REGISTRY:?ECR_REGISTRY is required}"
: "${ECR_REPO:?ECR_REPO is required}"
: "${CI_COMMIT_REF_SLUG:?CI_COMMIT_REF_SLUG is required}"
: "${CI_COMMIT_SHORT_SHA:?CI_COMMIT_SHORT_SHA is required}"
: "${ROLE_ARN:?ROLE_ARN is required}"
: "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
: "${CI_JOB_ID:?CI_JOB_ID is required}"
: "${DOCKERFILE:?DOCKERFILE is required}"
: "${REGISTRY_AUTH_FILE:?REGISTRY_AUTH_FILE is required}"

IMAGE_TAG="review-${CI_COMMIT_REF_SLUG}-${CI_COMMIT_SHORT_SHA}"
FULL_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
# Images with this tag are retained for 14 days (ecr_chatbot.tf lifecycle rule priority 3).

echo "Image tag: ${IMAGE_TAG}"
echo "Full image: ${FULL_IMAGE}"

# --- OIDC: assume role ---
echo "Assuming role: ${ROLE_ARN}"
# Capture stdout only — let AWS CLI errors flow to the job log unmodified.
# (Mixing stderr into STS_OUTPUT could be mis-parsed as credentials.)
STS_OUTPUT=$(aws sts assume-role-with-web-identity \
  --role-arn "${ROLE_ARN}" \
  --role-session-name "gitlab-ci-${CI_JOB_ID}" \
  --web-identity-token "${GITLAB_OIDC_TOKEN}" \
  --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
  --output text) || { echo "STS assume-role failed (see error above)"; exit 1; }

read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  <<< "${STS_OUTPUT}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

[[ -n "${AWS_ACCESS_KEY_ID}" && -n "${AWS_SECRET_ACCESS_KEY}" \
  && -n "${AWS_SESSION_TOKEN}" ]] \
  || { echo "STS assume-role failed: empty credentials"; exit 1; }

aws sts get-caller-identity

# --- Preflight: skip if tag already exists (IMMUTABLE repo — push would fail) ---
# Re-runs on the same commit (job retry, detached MR pipeline re-run) are safe to skip.
if aws ecr describe-images \
  --region "${AWS_DEFAULT_REGION:-eu-central-1}" \
  --repository-name "${ECR_REPO}" \
  --image-ids imageTag="${IMAGE_TAG}" \
  --output text >/dev/null 2>&1; then
  echo "Tag ${IMAGE_TAG} already exists in ECR — skipping build+push (idempotent re-run)."
  exit 0
fi

# --- ECR login ---
mkdir -p "$(dirname "${REGISTRY_AUTH_FILE}")"
ECR_PASS=$(aws ecr get-login-password --region "${AWS_DEFAULT_REGION:-eu-central-1}")
printf '{"auths":{"%s":{"auth":"%s"}}}' \
  "${ECR_REGISTRY}" \
  "$(printf 'AWS:%s' "${ECR_PASS}" | base64 -w0)" \
  > "${REGISTRY_AUTH_FILE}"

# --- Build ---
buildah build \
  --isolation chroot \
  --storage-driver vfs \
  --format docker \
  --ulimit nofile=65535:65536 \
  -f "${DOCKERFILE}" \
  -t "${FULL_IMAGE}" \
  .

# --- Push ---
buildah push \
  --storage-driver vfs \
  "${FULL_IMAGE}"

echo "Pushed: ${FULL_IMAGE}"
