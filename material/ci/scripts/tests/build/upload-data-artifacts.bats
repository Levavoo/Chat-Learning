#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/build/upload-data-artifacts.sh
# Content-gate logic: hash match → skip; hash differs / missing / error → proceed.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/build/upload-data-artifacts.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk/seed-data/source"

  # Minimal seed files so find + sha256sum produce a stable hash.
  # KB inputs after #501 are *.xml + *.md; the *.pdf stays in the repo as the
  # Textract input for extract_merkblaetter.py but is no longer a KB artifact.
  echo "brochure" >"$TEST_DIR/cdk/seed-data/source/B01.xml"
  echo "merkblatt" >"$TEST_DIR/cdk/seed-data/source/V0090.md"
  echo "merkblatt-pdf" >"$TEST_DIR/cdk/seed-data/source/V0090.pdf"

  export PATH="$TEST_DIR/bin:$PATH"
  export NEW_TAG="1.4.0"
  export AWS_DEFAULT_REGION="eu-central-1"
  # Pre-export fake credentials so the script's aws calls don't fail on missing creds.
  export AWS_ACCESS_KEY_ID="FAKEID"
  export AWS_SECRET_ACCESS_KEY="FAKESECRET"
  export AWS_SESSION_TOKEN="FAKETOKEN"

  cat >"$TEST_DIR/bin/release-retention-stub" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >>"$TEST_DIR/retention_calls"
STUB
  chmod +x "$TEST_DIR/bin/release-retention-stub"
  export RELEASE_RETENTION_STUB="$TEST_DIR/bin/release-retention-stub"

  # Change to the TEST_DIR so relative path cdk/seed-data/source resolves.
  cd "$TEST_DIR" || exit
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Compute the same hash the script would compute, for use in stubs.
_corpus_hash() {
  find cdk/seed-data/source -type f \( -name '*.xml' -o -name '*.md' \) \
    -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1
}

# Build an aws stub.
# $1 = stored content hash returned by ssm get-parameter for data-artifact-content-hash
#      ("MISSING" to simulate ParameterNotFound / error exit)
# $2 = stored version returned for data-artifact-version
#      (default "v1.3.0")
_aws_stub() {
  local stored_hash="${1:-}"
  local stored_version="${2:-v1.3.0}"
  local bucket_name="renate-s3-etl-source-dev-abc123"

  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
# Minimal aws stub for upload-data-artifacts.sh tests.
CMD="\$*"

# ssm get-parameter routing
if [[ "\$CMD" == *"get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-source-bucket-name"* ]]; then
    echo "$bucket_name"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-content-hash"* ]]; then
    if [ "${stored_hash}" = "MISSING" ]; then exit 1; fi
    echo "${stored_hash}"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-version"* && "\$CMD" != *"previous"* ]]; then
    echo "${stored_version}"; exit 0
  fi
  # version-previous or any other param — empty OK
  echo ""; exit 0
fi

# ssm put-parameter — record which params were written
if [[ "\$CMD" == *"put-parameter"* ]]; then
  # Extract --name value
  name=""
  prev=""
  for arg in "\$@"; do
    if [ "\$prev" = "--name" ]; then name="\$arg"; break; fi
    prev="\$arg"
  done
  echo "PUT \$name" >> "$TEST_DIR/ssm_writes"
  exit 0
fi

# s3 cp — record calls
if [[ "\$CMD" == *"s3 cp"* ]]; then
  echo "S3CP \$CMD" >> "$TEST_DIR/s3_uploads"
  exit 0
fi

# sts get-caller-identity (called by CI job before script, but harmless here)
if [[ "\$CMD" == *"get-caller-identity"* ]]; then exit 0; fi

exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

# ---------------------------------------------------------------------------

@test "[upload-data-artifacts] equal hash → skips upload, no SSM writes, exit 0" {
  HASH="$(_corpus_hash)"
  _aws_stub "$HASH"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"seed corpus unchanged"* ]]
  # No S3 uploads
  [ ! -f "$TEST_DIR/s3_uploads" ]
  # No SSM writes
  [ ! -f "$TEST_DIR/ssm_writes" ]
  grep -q "reconcile.*--protected-prefix releases/v1.3.0/" "$TEST_DIR/retention_calls"
}

@test "[upload-data-artifacts] different stored hash → uploads XML and MD, writes SSM" {
  _aws_stub "000000000000000000000000000000000000000000000000000000000000dead"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Upload complete"* ]]
  # Both XML and MD uploads happened
  grep -q "releases/v1.4.0/xml/" "$TEST_DIR/s3_uploads"
  grep -q "releases/v1.4.0/md/" "$TEST_DIR/s3_uploads"
  # SSM pointers written: version-previous, version, content-hash
  grep -q "/dev/renate/data-artifact-version-previous" "$TEST_DIR/ssm_writes"
  grep -q "/dev/renate/data-artifact-version"          "$TEST_DIR/ssm_writes"
  grep -q "/dev/renate/data-artifact-content-hash"     "$TEST_DIR/ssm_writes"
  grep -q "unpin.*--prefix releases/v1.4.0/" "$TEST_DIR/retention_calls"
  [ "$(grep -c '^reconcile ' "$TEST_DIR/retention_calls")" -eq 2 ]
}

@test "[upload-data-artifacts] missing stored hash (ParameterNotFound) → proceeds, uploads" {
  # D2: fail toward reprocess — missing hash is treated as changed
  _aws_stub "MISSING"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Upload complete"* ]]
  grep -q "releases/v1.4.0/xml/" "$TEST_DIR/s3_uploads"
  grep -q "releases/v1.4.0/md/" "$TEST_DIR/s3_uploads"
}

@test "[upload-data-artifacts] empty stored hash → proceeds, uploads" {
  # D2: empty string (e.g. SSM returned empty value) is treated as changed
  _aws_stub ""

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Upload complete"* ]]
  grep -q "releases/v1.4.0/xml/" "$TEST_DIR/s3_uploads"
}

@test "[upload-data-artifacts] SSM writes are ordered: version-previous before version before hash" {
  _aws_stub "000000000000000000000000000000000000000000000000000000000000dead"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  # Extract write order from the log file
  PREV_LINE=$(grep -n "version-previous" "$TEST_DIR/ssm_writes" | cut -d: -f1)
  VER_LINE=$(grep -n "data-artifact-version$" "$TEST_DIR/ssm_writes" | cut -d: -f1)
  HASH_LINE=$(grep -n "data-artifact-content-hash" "$TEST_DIR/ssm_writes" | cut -d: -f1)

  [ "$PREV_LINE" -lt "$VER_LINE" ]
  [ "$VER_LINE"  -lt "$HASH_LINE" ]
}

@test "[upload-data-artifacts] retry after active pointer write preserves rollback version" {
  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"

if [[ "\$CMD" == *"get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-source-bucket-name"* ]]; then
    echo "renate-s3-etl-source-dev-abc123"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-content-hash"* ]]; then
    echo "stale-hash"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-version-previous"* ]]; then
    echo "v1.3.0"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-version"* ]]; then
    echo "v1.4.0"; exit 0
  fi
fi

if [[ "\$CMD" == *"put-parameter"* ]]; then
  name=""
  prev=""
  for arg in "\$@"; do
    if [ "\$prev" = "--name" ]; then name="\$arg"; break; fi
    prev="\$arg"
  done
  echo "PUT \$name" >> "$TEST_DIR/ssm_writes"
  exit 0
fi

if [[ "\$CMD" == *"s3 cp"* ]]; then
  echo "S3CP \$CMD" >> "$TEST_DIR/s3_uploads"
  exit 0
fi
exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "version-previous" "$TEST_DIR/ssm_writes"
  grep -q "reconcile.*--protected-prefix releases/v1.4.0/.*--protected-prefix releases/v1.3.0/" \
    "$TEST_DIR/retention_calls"
}

@test "[upload-data-artifacts] version prefix is v + NEW_TAG" {
  _aws_stub "MISSING"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "releases/v1.4.0/" "$TEST_DIR/s3_uploads"
}

@test "[upload-data-artifacts] first run (no prior version in SSM) → succeeds, no version-previous write" {
  # On the very first run neither data-artifact-content-hash nor
  # data-artifact-version exist in SSM.  The script must not call
  # put-parameter with an empty --value (AWS rejects min-length=1).
  # The version-previous param must be skipped entirely.
  #
  # Both hash and version GetParameter calls return exit 1 (ParameterNotFound).
  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"

if [[ "\$CMD" == *"get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-source-bucket-name"* ]]; then
    echo "renate-s3-etl-source-dev-abc123"; exit 0
  fi
  # All other params absent on first run — simulate ParameterNotFound.
  echo "An error occurred (ParameterNotFound) when calling the GetParameter operation: Parameter not found." >&2
  exit 255
fi

if [[ "\$CMD" == *"put-parameter"* ]]; then
  name=""
  prev=""
  for arg in "\$@"; do
    if [ "\$prev" = "--name" ]; then name="\$arg"; break; fi
    prev="\$arg"
  done
  value=""
  capture_next=0
  for arg in "\$@"; do
    if [ "\$capture_next" -eq 1 ]; then value="\$arg"; capture_next=0; fi
    if [ "\$arg" = "--value" ]; then capture_next=1; fi
  done
  if [ -z "\$value" ]; then
    echo "EMPTY_VALUE_WRITE \$name" >> "$TEST_DIR/ssm_empty_writes"
  fi
  echo "PUT \$name" >> "$TEST_DIR/ssm_writes"
  exit 0
fi

if [[ "\$CMD" == *"s3 cp"* ]]; then
  echo "S3CP \$CMD" >> "$TEST_DIR/s3_uploads"
  exit 0
fi
exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Upload complete"* ]]

  # version-previous must NOT have been written with an empty value.
  if [ -f "$TEST_DIR/ssm_empty_writes" ]; then
    grep -q "version-previous" "$TEST_DIR/ssm_empty_writes" && {
      echo "FAIL: put-parameter called with empty value for version-previous"
      return 1
    }
  fi

  # version and content-hash must still be written.
  grep -q "/dev/renate/data-artifact-version" "$TEST_DIR/ssm_writes"
  grep -q "/dev/renate/data-artifact-content-hash"  "$TEST_DIR/ssm_writes"
}

# ---------------------------------------------------------------------------
# Tombstone / manifest-diff tests
# ---------------------------------------------------------------------------

# Extended aws stub that also handles s3 cp downloads (manifest reads).
# $1 = stored hash  $2 = stored version  $3 = prev manifest JSON (or "NONE")
_aws_stub_with_manifest() {
  local stored_hash="${1:-}"
  local stored_version="${2:-v1.3.0}"
  local prev_manifest="${3:-NONE}"
  local bucket_name="renate-s3-etl-source-dev-abc123"

  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"

if [[ "\$CMD" == *"get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-source-bucket-name"* ]]; then
    echo "$bucket_name"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-content-hash"* ]]; then
    if [ "${stored_hash}" = "MISSING" ]; then exit 1; fi
    echo "${stored_hash}"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-version"* && "\$CMD" != *"previous"* ]]; then
    echo "${stored_version}"; exit 0
  fi
  echo ""; exit 0
fi

if [[ "\$CMD" == *"put-parameter"* ]]; then
  name=""
  prev=""
  for arg in "\$@"; do
    if [ "\$prev" = "--name" ]; then name="\$arg"; break; fi
    prev="\$arg"
  done
  echo "PUT \$name" >> "$TEST_DIR/ssm_writes"
  exit 0
fi

if [[ "\$CMD" == *"s3 cp"* ]]; then
  src="\$3"
  dest="\$4"

  # Previous-release manifest download (drives the tombstone diff). No python3.
  if [[ "\$src" == *"/releases/${stored_version}/manifest.json" ]]; then
    if [ "${prev_manifest}" = "NONE" ]; then exit 1; fi
    echo '${prev_manifest}' > "\$dest"
    exit 0
  fi

  # Corpus upload, manifest upload, or tombstone upload — record the call.
  echo "S3CP \$CMD" >> "$TEST_DIR/s3_uploads"
  exit 0
fi

if [[ "\$CMD" == *"get-caller-identity"* ]]; then exit 0; fi
exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[upload-data-artifacts] removed stem → tombstone uploaded" {
  # Previous release had B01 + B02; new release has only B01 → B02 tombstone expected
  PREV_JSON='{"version":"v1.3.0","stems":["B01","B02"],"files":{"xml":["xml/B01.xml","xml/B02.xml"],"md":[]}}'
  _aws_stub_with_manifest "deadbeef" "v1.3.0" "$PREV_JSON"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # Tombstone for B02 (present in old, absent from new)
  grep -q "releases/v1.4.0/deletes/B02" "$TEST_DIR/s3_uploads"
}

@test "[upload-data-artifacts] no removed stems → no tombstones" {
  # Previous release had B01 + V0090; new release also has B01 + V0090 → no tombstones
  PREV_JSON='{"version":"v1.3.0","stems":["B01","V0090"],"files":{"xml":["xml/B01.xml"],"md":["md/V0090.md"]}}'
  _aws_stub_with_manifest "deadbeef" "v1.3.0" "$PREV_JSON"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # No deletes/ upload
  ! grep -q "/deletes/" "$TEST_DIR/s3_uploads" 2>/dev/null || true
  [[ "$output" == *"No removed stems"* ]]
}

@test "[upload-data-artifacts] missing previous manifest → no tombstones, job succeeds" {
  # NONE = aws s3 cp fails for the manifest download (first run or missing)
  _aws_stub_with_manifest "deadbeef" "v1.3.0" "NONE"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q "/deletes/" "$TEST_DIR/s3_uploads" 2>/dev/null || true
}

@test "[upload-data-artifacts] missing hash + previous version + removed stem → tombstone emitted" {
  # Regression guard for the PREV_HASH outer-guard bug:
  # if data-artifact-content-hash is absent (first content run after a manual
  # SSM reset, or a failed prior write), the script treats corpus as changed
  # (D2) and proceeds.  If a previous version and manifest exist with a stem
  # that's absent from the new release, a tombstone MUST still be emitted.
  # The old code wrapped the entire tombstone diff in `if [ -n "${PREV_HASH}" ]`,
  # which silently skipped it on this path — stale docs/ entries persisted and
  # subsequent runs would skip the diff because the hash was now current.
  PREV_JSON='{"version":"v1.3.0","stems":["B01","B02"],"files":{"xml":["xml/B01.xml","xml/B02.xml"],"md":[]}}'
  # "MISSING" = hash GetParameter exits 1 (ParameterNotFound) → proceeds via D2
  _aws_stub_with_manifest "MISSING" "v1.3.0" "$PREV_JSON"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Upload complete"* ]]
  # Tombstone for B02 must be present even though PREV_HASH was missing
  grep -q "releases/v1.4.0/deletes/B02" "$TEST_DIR/s3_uploads"
}

# ---------------------------------------------------------------------------
# DATA_ARTIFACT_CHANGED dotenv tests (#590)
# ---------------------------------------------------------------------------

@test "[upload-data-artifacts] unchanged path → DATA_ARTIFACT_CHANGED=false + current version in dotenv" {
  HASH="$(_corpus_hash)"
  _aws_stub "$HASH" "v1.3.0"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [ -f "$DOTENV" ]
  grep -qx "DATA_ARTIFACT_CHANGED=false" "$DOTENV"
  grep -qx "DATA_ARTIFACT_VERSION=v1.3.0" "$DOTENV"
}

@test "[upload-data-artifacts] changed path → DATA_ARTIFACT_CHANGED=true + new version in dotenv" {
  _aws_stub "000000000000000000000000000000000000000000000000000000000000dead" "v1.3.0"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [ -f "$DOTENV" ]
  grep -qx "DATA_ARTIFACT_CHANGED=true" "$DOTENV"
  grep -qx "DATA_ARTIFACT_VERSION=v1.4.0" "$DOTENV"
}

@test "[upload-data-artifacts] missing hash (first run) → DATA_ARTIFACT_CHANGED=true in dotenv" {
  _aws_stub "MISSING"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -qx "DATA_ARTIFACT_CHANGED=true" "$DOTENV"
  grep -qx "DATA_ARTIFACT_VERSION=v1.4.0" "$DOTENV"
}

# ---------------------------------------------------------------------------
# Readiness baseline capture (start-ts/DLQ-baseline race fix)
#
# etl-readiness-check.sh filters ListIngestionJobs for a job that started
# AT/AFTER --start-ts. This baseline must be captured BEFORE the S3 upload
# below that fires the reprocess, not by the caller after this script
# returns — see etl-readiness-dev.sh's header comment / etl.yml's
# etl-readiness-data:dev job comment for the full race description.
# ---------------------------------------------------------------------------

# Extends _aws_stub with etl-dlq-arn / bm25-rebuild-dlq-arn SSM lookups and an
# sqs get-queue-attributes stub. $1/$2 = ARNs to return (empty = "not deployed
# yet"). $3/$4 = DLQ depths to report (default 0).
_aws_stub_with_dlq() {
  local stored_hash="${1:-}"
  local stored_version="${2:-v1.3.0}"
  local transform_dlq_arn="${3:-}"
  local bm25_dlq_arn="${4:-}"
  local transform_depth="${5:-0}"
  local bm25_depth="${6:-0}"
  local dlq_error_mode="${7:-notfound}"
  local bucket_name="renate-s3-etl-source-dev-abc123"

  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"

if [[ "\$CMD" == *"get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-source-bucket-name"* ]]; then
    echo "$bucket_name"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-content-hash"* ]]; then
    if [ "${stored_hash}" = "MISSING" ]; then exit 1; fi
    echo "${stored_hash}"; exit 0
  fi
  if [[ "\$CMD" == *"etl-dlq-arn"* ]]; then
    if [ "${dlq_error_mode}" = "denied" ]; then
      echo "An error occurred (AccessDeniedException) when calling the GetParameter operation: User: arn:aws:sts::831926590742:assumed-role/ki-lab-digibro-dev-data-artifacts/gitlab-ci is not authorized to perform: ssm:GetParameter on resource: arn:aws:ssm:eu-central-1:831926590742:parameter/dev/renate/etl-dlq-arn" >&2
      exit 255
    fi
    if [ -z "${transform_dlq_arn}" ]; then
      echo "An error occurred (ParameterNotFound) when calling the GetParameter operation: Parameter /dev/renate/etl-dlq-arn not found." >&2
      exit 255
    fi
    echo "${transform_dlq_arn}"; exit 0
  fi
  if [[ "\$CMD" == *"bm25-rebuild-dlq-arn"* ]]; then
    if [ "${dlq_error_mode}" = "denied" ]; then
      echo "An error occurred (AccessDeniedException) when calling the GetParameter operation: User: arn:aws:sts::831926590742:assumed-role/ki-lab-digibro-dev-data-artifacts/gitlab-ci is not authorized to perform: ssm:GetParameter on resource: arn:aws:ssm:eu-central-1:831926590742:parameter/dev/renate/bm25-rebuild-dlq-arn" >&2
      exit 255
    fi
    if [ -z "${bm25_dlq_arn}" ]; then
      echo "An error occurred (ParameterNotFound) when calling the GetParameter operation: Parameter /dev/renate/bm25-rebuild-dlq-arn not found." >&2
      exit 255
    fi
    echo "${bm25_dlq_arn}"; exit 0
  fi
  if [[ "\$CMD" == *"data-artifact-version"* && "\$CMD" != *"previous"* ]]; then
    echo "${stored_version}"; exit 0
  fi
  echo ""; exit 0
fi

if [[ "\$CMD" == *"get-queue-attributes"* ]]; then
  if [[ "\$CMD" == *"transform"* ]]; then
    echo '{"Attributes":{"ApproximateNumberOfMessages":"${transform_depth}"}}'; exit 0
  fi
  echo '{"Attributes":{"ApproximateNumberOfMessages":"${bm25_depth}"}}'; exit 0
fi

if [[ "\$CMD" == *"put-parameter"* ]]; then
  name=""
  prev=""
  for arg in "\$@"; do
    if [ "\$prev" = "--name" ]; then name="\$arg"; break; fi
    prev="\$arg"
  done
  echo "PUT \$name" >> "$TEST_DIR/ssm_writes"
  exit 0
fi

if [[ "\$CMD" == *"s3 cp"* ]]; then
  echo "S3CP \$CMD" >> "$TEST_DIR/s3_uploads"
  exit 0
fi

if [[ "\$CMD" == *"get-caller-identity"* ]]; then exit 0; fi
exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[upload-data-artifacts] changed path, queue ARNs present → baseline captured before upload" {
  _aws_stub_with_dlq "deadbeef" "v1.3.0" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-transform-dlq-dev" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-bm25-rebuild-dlq-dev" \
    "0" "0"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Captured readiness baseline (pre-upload)"* ]]
  grep -q "^DATA_ARTIFACT_READINESS_START_TS=" "$DOTENV"
  grep -qx "DATA_ARTIFACT_TRANSFORM_DLQ_BASELINE=0" "$DOTENV"
  grep -qx "DATA_ARTIFACT_BM25_DLQ_BASELINE=0" "$DOTENV"
  # Baseline must be captured strictly before the S3 upload it protects.
  START_TS=$(grep "^DATA_ARTIFACT_READINESS_START_TS=" "$DOTENV" | cut -d= -f2)
  [ -n "$START_TS" ]
}

@test "[upload-data-artifacts] changed path, no queue ARNs (fresh env) → skips baseline capture" {
  _aws_stub_with_dlq "deadbeef" "v1.3.0" "" ""

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL stack not yet deployed"* ]]
  ! grep -q "DATA_ARTIFACT_READINESS_START_TS" "$DOTENV"
}

@test "[upload-data-artifacts] unchanged path → no baseline captured (no reprocess triggered)" {
  HASH="$(_corpus_hash)"
  _aws_stub_with_dlq "$HASH" "v1.3.0" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-transform-dlq-dev" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-bm25-rebuild-dlq-dev"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"seed corpus unchanged"* ]]
  ! grep -q "DATA_ARTIFACT_READINESS_START_TS" "$DOTENV"
}

@test "[upload-data-artifacts] changed path, SSM read denied (not ParameterNotFound) → fails loud before upload" {
  # Regression guard for the MR !972 escape-hatch hole (pipeline #3770): the
  # data-artifacts role could read the data-artifact params but was denied
  # ssm:GetParameter on the ETL DLQ ARNs. The old `2>/dev/null || echo ""`
  # swallowed that AccessDenied as "" and silently skipped the baseline,
  # reproducing the start-ts race. _readiness_baseline must now fail loud
  # rather than skip, so the misconfiguration surfaces before any side effect.
  _aws_stub_with_dlq "deadbeef" "v1.3.0" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-transform-dlq-dev" \
    "arn:aws:sqs:eu-central-1:831926590742:renate-bm25-rebuild-dlq-dev" \
    "0" "0" "denied"

  DOTENV="$TEST_DIR/data-artifact.env"
  run bash -c "DATA_ARTIFACT_ENV_FILE='$DOTENV' bash '$SCRIPT'"

  # Fails loud (non-zero) with an actionable message.
  [ "$status" -ne 0 ]
  [[ "$output" == *"Could not read the ETL readiness SSM parameters"* ]]
  # Aborted at 3b — before the upload, before SSM pointer writes, and without
  # emitting the (now-missing) start-ts handoff.
  [ ! -f "$TEST_DIR/s3_uploads" ]
  [ ! -f "$TEST_DIR/ssm_writes" ]
  ! grep -q "DATA_ARTIFACT_READINESS_START_TS" "$DOTENV"
}
