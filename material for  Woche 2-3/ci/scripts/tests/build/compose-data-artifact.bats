#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/build/compose-data-artifact.sh"
FAQ_A="sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FAQ_B="sha256-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  export BUCKET="test-source-bucket"
  export BROCHURE_ARTIFACT_VERSION="v1.92.0"
  export FAQ_ARTIFACT_VERSION="$FAQ_A"
  export DATA_ARTIFACT_CHANGED="false"
  export COMPOSITE_DATA_ARTIFACT_ENV_FILE="$TEST_DIR/composite.env"
  export COMPOSITE_STATE_PARAMETER="/dev/renate/composite-data-artifact-state"

  cat >"$TEST_DIR/brochure.json" <<'JSON'
{"version":"v1.92.0","files":{"xml":["xml/a.xml"],"pdf":[]}}
JSON
  cat >"$TEST_DIR/faq.json" <<JSON
{"schema_version":1,"coordinate":"$FAQ_A","files":["html/faq.html"]}
JSON

  cat >"$TEST_DIR/bin/aws" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [ "$1 $2" = "s3 cp" ]; then
  source_path="$3"
  destination="$4"
  case "$source_path" in
    */releases/faq/*/manifest.json)
      cp "$TEST_DIR/faq.json" "$destination"
      ;;
    */releases/*-data.*/manifest.json)
      cp "${EXISTING_COMPOSITE:?}" "$destination"
      ;;
    */releases/v*/manifest.json)
      cp "$TEST_DIR/brochure.json" "$destination"
      ;;
    *)
      echo "unexpected s3 cp source: $source_path" >&2
      exit 1
      ;;
  esac
  exit 0
fi
if [ "$1 $2" = "s3api head-object" ]; then
  if [ -n "${EXISTING_COMPOSITE:-}" ]; then
    exit 0
  fi
  echo "404 Not Found" >&2
  exit 255
fi
if [ "$1 $2" = "s3api put-object" ]; then
  shift 2
  body=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--body" ]; then
      body="$2"
      shift 2
    else
      shift
    fi
  done
  cp "$body" "$TEST_DIR/put-manifest.json"
  touch "$TEST_DIR/put-called"
  exit 0
fi
if [ "$1 $2" = "ssm get-parameter" ]; then
  if [ -f "$TEST_DIR/state.json" ]; then
    cat "$TEST_DIR/state.json"
    exit 0
  fi
  echo "ParameterNotFound" >&2
  exit 254
fi
if [ "$1 $2" = "ssm put-parameter" ]; then
  shift 2
  value=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--value" ]; then
      value="$2"
      shift 2
    else
      shift
    fi
  done
  printf '%s\n' "$value" >"$TEST_DIR/state.json"
  touch "$TEST_DIR/state-put-called"
  exit 0
fi
echo "unexpected aws call: $*" >&2
exit 1
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[compose-data-artifact] publishes a readable initial composite coordinate" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$TEST_DIR/put-called" ]
  grep -qx "DATA_ARTIFACT_VERSION=v1.92.0-data.1" "$TEST_DIR/composite.env"
  grep -qx "BROCHURE_ARTIFACT_VERSION=v1.92.0" "$TEST_DIR/composite.env"
  grep -qx "FAQ_ARTIFACT_VERSION=$FAQ_A" "$TEST_DIR/composite.env"
  jq -e --arg faq "$FAQ_A" '
    .schema_version == 1
    and .coordinate == "v1.92.0-data.1"
    and (.component_fingerprint | test("^sha256-[0-9a-f]{64}$"))
    and .components.brochure.artifact_version == "v1.92.0"
    and .components.faq.artifact_version == $faq
    and (.components.brochure.manifest_sha256 | test("^[0-9a-f]{64}$"))
    and (.components.faq.manifest_sha256 | test("^[0-9a-f]{64}$"))
  ' "$TEST_DIR/put-manifest.json"
  jq -e '
    .coordinate == "v1.92.0-data.1"
    and .brochure_artifact_version == "v1.92.0"
    and .faq_artifact_version == "sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    and .revision == 1
  ' "$TEST_DIR/state.json"
}

@test "[compose-data-artifact] changing only FAQ increments the readable revision" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  export FAQ_ARTIFACT_VERSION="$FAQ_B"
  cat >"$TEST_DIR/faq.json" <<JSON
{"schema_version":1,"coordinate":"$FAQ_B","files":["html/faq.html"]}
JSON
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -qx "DATA_ARTIFACT_VERSION=v1.92.0-data.2" "$TEST_DIR/composite.env"
  jq -e --arg faq "$FAQ_B" '.revision == 2 and .faq_artifact_version == $faq' \
    "$TEST_DIR/state.json"
}

@test "[compose-data-artifact] a new brochure version starts at data revision one" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  export BROCHURE_ARTIFACT_VERSION="v1.93.0"
  cat >"$TEST_DIR/brochure.json" <<'JSON'
{"version":"v1.93.0","files":{"xml":["xml/b.xml"],"pdf":[]}}
JSON
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -qx "DATA_ARTIFACT_VERSION=v1.93.0-data.1" "$TEST_DIR/composite.env"
  jq -e '.coordinate == "v1.93.0-data.1" and .revision == 1' "$TEST_DIR/state.json"
}

@test "[compose-data-artifact] identical existing manifest is idempotent" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  export EXISTING_COMPOSITE="$TEST_DIR/put-manifest.json"
  rm "$TEST_DIR/put-called"
  rm "$TEST_DIR/state-put-called"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"already exists"* ]]
  [ ! -f "$TEST_DIR/put-called" ]
  [ ! -f "$TEST_DIR/state-put-called" ]
}

@test "[compose-data-artifact] malformed revision state fails closed" {
  printf '{"schema_version":1,"coordinate":"wrong"}\n' >"$TEST_DIR/state.json"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"state is invalid"* ]]
  [ ! -f "$TEST_DIR/put-called" ]
}

@test "[compose-data-artifact] divergent existing manifest fails closed" {
  printf '{"schema_version":1,"coordinate":"wrong"}\n' >"$TEST_DIR/divergent.json"
  export EXISTING_COMPOSITE="$TEST_DIR/divergent.json"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"divergent content"* ]]
}

@test "[compose-data-artifact] malformed FAQ component fails before publication" {
  printf '{"schema_version":1,"coordinate":"wrong","files":[]}\n' >"$TEST_DIR/faq.json"

  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"FAQ component manifest is invalid"* ]]
  [ ! -f "$TEST_DIR/put-called" ]
}

@test "[compose-data-artifact] readiness baseline vars from upload-data-artifacts.sh are forwarded" {
  export DATA_ARTIFACT_READINESS_START_TS="2026-07-23T11:55:00Z"
  export DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE="0"
  export DATA_ARTIFACT_BM25_DLQ_BASELINE="0"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -qx "DATA_ARTIFACT_READINESS_START_TS=2026-07-23T11:55:00Z" "$TEST_DIR/composite.env"
  grep -qx "DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE=0" "$TEST_DIR/composite.env"
  grep -qx "DATA_ARTIFACT_BM25_DLQ_BASELINE=0" "$TEST_DIR/composite.env"
}

@test "[compose-data-artifact] readiness baseline vars absent (unchanged/fresh-env path) → empty in dotenv" {
  unset DATA_ARTIFACT_READINESS_START_TS DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE DATA_ARTIFACT_BM25_DLQ_BASELINE

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -qx "DATA_ARTIFACT_READINESS_START_TS=" "$TEST_DIR/composite.env"
  grep -qx "DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE=" "$TEST_DIR/composite.env"
  grep -qx "DATA_ARTIFACT_BM25_DLQ_BASELINE=" "$TEST_DIR/composite.env"
}
