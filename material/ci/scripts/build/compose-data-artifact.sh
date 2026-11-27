#!/usr/bin/env bash
# Compose one immutable promotion coordinate from the active brochure and FAQ
# artifacts. The operator-facing pin remains exactly chatbot/data/ETL; the data
# coordinate changes whenever either independently published component changes.
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-eu-central-1}"
ENV_NAME="${ENV_NAME:-dev}"
OUTPUT_FILE="${COMPOSITE_DATA_ARTIFACT_ENV_FILE:-composite-data-artifact.env}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

_required_parameter() {
  local name="$1" value
  value=$(aws ssm get-parameter --name "$name" --query Parameter.Value \
    --output text --region "$REGION") || {
    echo "ERROR: required SSM parameter ${name} is missing" >&2
    return 1
  }
  [ -n "$value" ] || {
    echo "ERROR: required SSM parameter ${name} is empty" >&2
    return 1
  }
  printf '%s\n' "$value"
}

_optional_parameter() {
  local name="$1" value error_file="$TMP_DIR/ssm-error"
  if value=$(aws ssm get-parameter --name "$name" --query Parameter.Value \
    --output text --region "$REGION" 2>"$error_file"); then
    printf '%s\n' "$value"
    return 0
  fi
  if grep -q 'ParameterNotFound' "$error_file"; then
    return 1
  fi
  echo "ERROR: cannot read SSM parameter ${name}" >&2
  cat "$error_file" >&2
  return 2
}

_sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

_object_exists() {
  local key="$1" error_file="$TMP_DIR/head-error"
  if aws s3api head-object --bucket "$BUCKET" --key "$key" \
    --region "$REGION" >/dev/null 2>"$error_file"; then
    return 0
  fi
  if grep -qE '404|Not Found|NoSuchKey' "$error_file"; then
    return 1
  fi
  echo "ERROR: cannot inspect s3://${BUCKET}/${key}" >&2
  cat "$error_file" >&2
  return 2
}

BROCHURE_ARTIFACT_VERSION="${BROCHURE_ARTIFACT_VERSION:?BROCHURE_ARTIFACT_VERSION is required}"
FAQ_ARTIFACT_VERSION="${FAQ_ARTIFACT_VERSION:-}"
if [ -z "$FAQ_ARTIFACT_VERSION" ]; then
  FAQ_ARTIFACT_VERSION=$(_required_parameter "/${ENV_NAME}/renate/faq-artifact-version")
fi
BUCKET="${BUCKET:-}"
if [ -z "$BUCKET" ]; then
  BUCKET=$(_required_parameter "/${ENV_NAME}/renate/etl-source-bucket-name")
fi

if [[ ! "$BROCHURE_ARTIFACT_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]; then
  echo "ERROR: invalid brochure artifact version: ${BROCHURE_ARTIFACT_VERSION}" >&2
  exit 1
fi
if [[ ! "$FAQ_ARTIFACT_VERSION" =~ ^sha256-[0-9a-f]{64}$ ]]; then
  echo "ERROR: invalid FAQ artifact version: ${FAQ_ARTIFACT_VERSION}" >&2
  exit 1
fi
if [[ ! "$BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "ERROR: invalid source bucket: ${BUCKET}" >&2
  exit 1
fi

STATE_PARAMETER="${COMPOSITE_STATE_PARAMETER:-/${ENV_NAME}/renate/composite-data-artifact-state}"
BROCHURE_PREFIX="releases/${BROCHURE_ARTIFACT_VERSION}/"
FAQ_PREFIX="releases/faq/${FAQ_ARTIFACT_VERSION}/"
BROCHURE_MANIFEST_KEY="${BROCHURE_PREFIX}manifest.json"
FAQ_MANIFEST_KEY="${FAQ_PREFIX}manifest.json"

BROCHURE_MANIFEST="$TMP_DIR/brochure-manifest.json"
FAQ_MANIFEST="$TMP_DIR/faq-manifest.json"
COMPOSITE_MANIFEST="$TMP_DIR/composite-manifest.json"
EXISTING_MANIFEST="$TMP_DIR/existing-composite-manifest.json"
FINGERPRINT_INPUT="$TMP_DIR/fingerprint-input.json"
ACTIVE_STATE="$TMP_DIR/active-state.json"
NEXT_STATE="$TMP_DIR/next-state.json"

aws s3 cp "s3://${BUCKET}/${BROCHURE_MANIFEST_KEY}" "$BROCHURE_MANIFEST" \
  --region "$REGION" >/dev/null
aws s3 cp "s3://${BUCKET}/${FAQ_MANIFEST_KEY}" "$FAQ_MANIFEST" \
  --region "$REGION" >/dev/null

jq -e --arg version "$BROCHURE_ARTIFACT_VERSION" \
  '.version == $version and (.files | type == "object")' \
  "$BROCHURE_MANIFEST" >/dev/null || {
  echo "ERROR: brochure component manifest is invalid" >&2
  exit 1
}
jq -e --arg coordinate "$FAQ_ARTIFACT_VERSION" \
  '.schema_version == 1 and .coordinate == $coordinate and (.files | type == "array")' \
  "$FAQ_MANIFEST" >/dev/null || {
  echo "ERROR: FAQ component manifest is invalid" >&2
  exit 1
}

BROCHURE_MANIFEST_SHA256=$(_sha256_file "$BROCHURE_MANIFEST")
FAQ_MANIFEST_SHA256=$(_sha256_file "$FAQ_MANIFEST")

# The component fingerprint preserves exact identity without exposing the FAQ
# hash in the operator-facing promotion pin.
jq -nS \
  --arg brochureVersion "$BROCHURE_ARTIFACT_VERSION" \
  --arg brochureManifestSha256 "$BROCHURE_MANIFEST_SHA256" \
  --arg faqVersion "$FAQ_ARTIFACT_VERSION" \
  --arg faqManifestSha256 "$FAQ_MANIFEST_SHA256" \
  '{
    brochure_artifact_version: $brochureVersion,
    brochure_manifest_sha256: $brochureManifestSha256,
    faq_artifact_version: $faqVersion,
    faq_manifest_sha256: $faqManifestSha256
  }' >"$FINGERPRINT_INPUT"
COMPONENT_FINGERPRINT="sha256-$(_sha256_file "$FINGERPRINT_INPUT")"

STATE_PRESENT="false"
STATE_VALUE=""
if STATE_VALUE=$(_optional_parameter "$STATE_PARAMETER"); then
  STATE_PRESENT="true"
  printf '%s\n' "$STATE_VALUE" >"$ACTIVE_STATE"
  jq -e '
    .schema_version == 1
    and (.coordinate | type == "string")
    and (.fingerprint | test("^sha256-[0-9a-f]{64}$"))
    and (.brochure_artifact_version | test("^v[0-9]+\\.[0-9]+\\.[0-9]+([-.][0-9A-Za-z.-]+)?$"))
    and (.faq_artifact_version | test("^sha256-[0-9a-f]{64}$"))
    and (.revision | type == "number" and . >= 1 and floor == .)
  ' "$ACTIVE_STATE" >/dev/null || {
    echo "ERROR: composite data artifact state is invalid" >&2
    exit 1
  }
else
  status=$?
  [ "$status" -eq 1 ] || exit "$status"
fi

REVISION=1
STATE_NEEDS_UPDATE="true"
if [ "$STATE_PRESENT" = "true" ]; then
  ACTIVE_COORDINATE=$(jq -r '.coordinate' "$ACTIVE_STATE")
  ACTIVE_FINGERPRINT=$(jq -r '.fingerprint' "$ACTIVE_STATE")
  ACTIVE_BROCHURE_VERSION=$(jq -r '.brochure_artifact_version' "$ACTIVE_STATE")
  ACTIVE_FAQ_VERSION=$(jq -r '.faq_artifact_version' "$ACTIVE_STATE")
  ACTIVE_REVISION=$(jq -r '.revision' "$ACTIVE_STATE")

  if [ "$ACTIVE_COORDINATE" != "${ACTIVE_BROCHURE_VERSION}-data.${ACTIVE_REVISION}" ]; then
    echo "ERROR: composite data artifact state coordinate is inconsistent" >&2
    exit 1
  fi

  if [ "$ACTIVE_FINGERPRINT" = "$COMPONENT_FINGERPRINT" ]; then
    if [ "$ACTIVE_BROCHURE_VERSION" != "$BROCHURE_ARTIFACT_VERSION" ] \
      || [ "$ACTIVE_FAQ_VERSION" != "$FAQ_ARTIFACT_VERSION" ]; then
      echo "ERROR: composite data artifact state fingerprint is inconsistent" >&2
      exit 1
    fi
    REVISION="$ACTIVE_REVISION"
    STATE_NEEDS_UPDATE="false"
  elif [ "$ACTIVE_BROCHURE_VERSION" = "$BROCHURE_ARTIFACT_VERSION" ]; then
    REVISION=$((ACTIVE_REVISION + 1))
  fi
fi

COMPOSITE_VERSION="${BROCHURE_ARTIFACT_VERSION}-data.${REVISION}"
COMPOSITE_PREFIX="releases/${COMPOSITE_VERSION}/"
COMPOSITE_MANIFEST_KEY="${COMPOSITE_PREFIX}manifest.json"

jq -n \
  --arg coordinate "$COMPOSITE_VERSION" \
  --arg fingerprint "$COMPONENT_FINGERPRINT" \
  --arg bucket "$BUCKET" \
  --arg brochureVersion "$BROCHURE_ARTIFACT_VERSION" \
  --arg brochurePrefix "$BROCHURE_PREFIX" \
  --arg brochureManifestKey "$BROCHURE_MANIFEST_KEY" \
  --arg brochureManifestSha256 "$BROCHURE_MANIFEST_SHA256" \
  --arg faqVersion "$FAQ_ARTIFACT_VERSION" \
  --arg faqPrefix "$FAQ_PREFIX" \
  --arg faqManifestKey "$FAQ_MANIFEST_KEY" \
  --arg faqManifestSha256 "$FAQ_MANIFEST_SHA256" \
  '{
    schema_version: 1,
    coordinate: $coordinate,
    component_fingerprint: $fingerprint,
    components: {
      brochure: {
        artifact_version: $brochureVersion,
        bucket: $bucket,
        prefix: $brochurePrefix,
        manifest_key: $brochureManifestKey,
        manifest_sha256: $brochureManifestSha256
      },
      faq: {
        artifact_version: $faqVersion,
        bucket: $bucket,
        prefix: $faqPrefix,
        manifest_key: $faqManifestKey,
        manifest_sha256: $faqManifestSha256
      }
    }
  }' >"$COMPOSITE_MANIFEST"

if _object_exists "$COMPOSITE_MANIFEST_KEY"; then
  aws s3 cp "s3://${BUCKET}/${COMPOSITE_MANIFEST_KEY}" "$EXISTING_MANIFEST" \
    --region "$REGION" >/dev/null
  if ! cmp -s "$COMPOSITE_MANIFEST" "$EXISTING_MANIFEST"; then
    echo "ERROR: immutable composite coordinate already contains divergent content" >&2
    exit 1
  fi
  echo "Composite data artifact already exists: ${COMPOSITE_VERSION}"
else
  status=$?
  [ "$status" -eq 1 ] || exit "$status"
  aws s3api put-object \
    --bucket "$BUCKET" \
    --key "$COMPOSITE_MANIFEST_KEY" \
    --body "$COMPOSITE_MANIFEST" \
    --content-type application/json \
    --if-none-match '*' \
    --checksum-algorithm SHA256 \
    --tagging 'renate%3Aretention=unpinned' \
    --region "$REGION" >/dev/null
  echo "Composite data artifact published: ${COMPOSITE_VERSION}"
fi

if [ "$STATE_NEEDS_UPDATE" = "true" ]; then
  jq -n \
    --arg coordinate "$COMPOSITE_VERSION" \
    --arg fingerprint "$COMPONENT_FINGERPRINT" \
    --arg brochureVersion "$BROCHURE_ARTIFACT_VERSION" \
    --arg faqVersion "$FAQ_ARTIFACT_VERSION" \
    --argjson revision "$REVISION" \
    '{
      schema_version: 1,
      coordinate: $coordinate,
      fingerprint: $fingerprint,
      brochure_artifact_version: $brochureVersion,
      faq_artifact_version: $faqVersion,
      revision: $revision
    }' >"$NEXT_STATE"
  STATE_VALUE=$(jq -c . "$NEXT_STATE")
  aws ssm put-parameter \
    --name "$STATE_PARAMETER" \
    --value "$STATE_VALUE" \
    --type String \
    --overwrite \
    --region "$REGION" >/dev/null
  echo "Composite data artifact state updated: ${COMPOSITE_VERSION}"
fi

{
  echo "DATA_ARTIFACT_CHANGED=${DATA_ARTIFACT_CHANGED:-false}"
  echo "DATA_ARTIFACT_VERSION=${COMPOSITE_VERSION}"
  echo "BROCHURE_ARTIFACT_VERSION=${BROCHURE_ARTIFACT_VERSION}"
  echo "FAQ_ARTIFACT_VERSION=${FAQ_ARTIFACT_VERSION}"
  # Passthrough of the pre-upload readiness baseline captured by
  # upload-data-artifacts.sh (empty when the ETL stack wasn't deployed yet,
  # or the corpus was unchanged and no upload/reprocess happened) — consumed
  # by etl-readiness-data:dev to avoid the start-ts race documented there.
  echo "DATA_ARTIFACT_READINESS_START_TS=${DATA_ARTIFACT_READINESS_START_TS:-}"
  echo "DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE=${DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE:-}"
  echo "DATA_ARTIFACT_BM25_DLQ_BASELINE=${DATA_ARTIFACT_BM25_DLQ_BASELINE:-}"
} >"$OUTPUT_FILE"

echo "Promotion data coordinate: ${COMPOSITE_VERSION}"
