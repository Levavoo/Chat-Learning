#!/usr/bin/env bash
# Publish immutable compatibility metadata for one dev ECR image coordinate.
set -euo pipefail

IMAGE_KIND="${1:-}"
IMAGE_TAG="${2:-}"
IMAGE_DIGEST="${3:-}"
TOKENIZER_REVISION="${4:-}"

case "$IMAGE_KIND" in
  chatbot) REPOSITORY="renate-chat-lambda" ;;
  etl) REPOSITORY="renate-etl-lambda" ;;
  *) echo "publish-image-metadata: kind must be chatbot or etl" >&2; exit 2 ;;
esac

[[ "$IMAGE_TAG" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
  echo "publish-image-metadata: immutable semantic image tag required" >&2
  exit 2
}
[[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "publish-image-metadata: immutable sha256 digest required" >&2
  exit 2
}
[[ "$TOKENIZER_REVISION" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || {
  echo "publish-image-metadata: invalid tokenizer revision" >&2
  exit 2
}

# The buildah-aws image intentionally contains only the image-build and AWS
# tooling, not jq. All interpolated values have already been restricted to
# JSON-safe character sets above, so Bash can produce this fixed schema without
# adding a runtime dependency to both image-publisher jobs.
printf -v VALUE \
  '{"schema_version":1,"image_kind":"%s","repository":"%s","image_tag":"%s","image_digest":"%s","bm25_tokenizer_revision":"%s","retrieval_manifest_schema_versions":[2,3],"bm25_index_schema_versions":[1,2]}' \
  "$IMAGE_KIND" "$REPOSITORY" "$IMAGE_TAG" "$IMAGE_DIGEST" "$TOKENIZER_REVISION"

aws ssm put-parameter \
  --name "/dev/renate/image-metadata/${IMAGE_KIND}/${IMAGE_TAG}" \
  --type String \
  --value "$VALUE" \
  --overwrite \
  --region "${AWS_DEFAULT_REGION:-eu-central-1}" >/dev/null

printf 'Published %s metadata for %s@%s\n' "$IMAGE_KIND" "$IMAGE_TAG" "$IMAGE_DIGEST"
