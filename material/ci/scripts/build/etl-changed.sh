#!/usr/bin/env bash
# etl-changed.sh
# Script-side ETL-change fingerprint gate (PC-001 safe — no `rules: changes` on
# master; the post-merge master pipeline's `git diff HEAD~1` is unreliable and
# can silently drop a job). This gate is "present but self-skip": it always
# runs and decides ETL_IMAGE_CHANGED / ETL_STACK_CHANGED via two independent
# content fingerprints compared against SSM (#626).
#
# Two independent signals (#626 — previously a single conflated ETL_CHANGED):
#   ETL_IMAGE_CHANGED — inputs that affect the built backend/src/etl/Dockerfile
#                        output (Python ETL/BM25 source + its dependency
#                        manifests). Gates build-etl-image:dev.
#   ETL_STACK_CHANGED — ETL CDK constructs/custom-resources/config/dependency
#                        inputs. Gates deploy-etl:dev alongside the image signal.
# The union of the two input sets is IDENTICAL to the pre-#626 single
# fingerprint's input set — no coverage gained or lost, just split.
#
# Fail-open (per signal): a missing/unreadable/unparseable stored fingerprint
# is treated as "changed" for that signal — better to rebuild/redeploy
# unnecessarily than to silently skip a real ETL change.
#
# Persistence (#626 Decision D1 = Option B): both fingerprints are stored as
# one composite JSON value in the EXISTING /dev/renate/etl-code-fingerprint
# parameter (`{"image":"<sha256>","stack":"<sha256>"}`) rather than two new
# named parameters — this requires zero renate/bootstrap IAM change (the
# etl-changed/etl-readiness roles already have exact-name get/put on this one
# parameter) and preserves #590's single atomic "write last" put. A legacy
# bare-sha value (pre-#626) or unparseable JSON has neither field, so both
# signals correctly fail open on the first run after this ships.
#
# Portability: the CI image (node-aws) ships no python3. Pure shell + coreutils
# (find/sort/awk/sha256sum) + jq (present in node-aws), same approach as
# upload-data-artifacts.sh / compose-data-artifact.sh.
#
# The fingerprint is NOT written here — /dev/renate/etl-code-fingerprint is
# written last, only after deploy-etl:dev's CDK deploy AND its own final
# readiness gate succeed, so a failed/half-finished deploy re-runs next
# time instead of being skipped.
#
# Output: writes dotenv-style ETL_IMAGE_CHANGED=true|false,
# ETL_STACK_CHANGED=true|false, ETL_IMAGE_FINGERPRINT=<sha>,
# ETL_STACK_FINGERPRINT=<sha> to stdout (redirect to a file consumed via
# artifacts:reports:dotenv).
#
# Required env: none (works with default credentials already exported by the
#               calling CI job). AWS_DEFAULT_REGION defaults to eu-central-1.
# Required tools: aws, jq.
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-eu-central-1}"
SSM_PARAM="/dev/renate/etl-code-fingerprint"

# ── 1. ETL-relevant path lists, split into IMAGE and STACK sets (#626) ───────
# IMAGE set mirrors backend/src/etl/Dockerfile's COPY/uv-sync inputs exactly
# (also mirrors cdk/lib/etl-kb-stack.ts's etlCodeHash path inputs — see that
# file's comment on why the two intentionally diverge on version
# normalization).
# shellcheck disable=SC2034 # used indirectly via nameref in compute_fingerprint
IMAGE_DIRS=(
  "backend/src/etl"
  "backend/src/bm25_shared"
)
# shellcheck disable=SC2034 # used indirectly via nameref in compute_fingerprint
IMAGE_FILES=(
  "pyproject.toml"
  "uv.lock"
  "backend/pyproject.toml"
)

# STACK set: everything else the pre-#626 single fingerprint covered — ETL CDK
# constructs, custom resources, config, and CDK's own dependency inputs.
# shellcheck disable=SC2034 # used indirectly via nameref in compute_fingerprint
STACK_DIRS=(
  "cdk/lib/constructs/knowledge-base"
  "cdk/lib/custom-resources/source-reprocess"
  "cdk/lib/config/kb"
)
# shellcheck disable=SC2034 # used indirectly via nameref in compute_fingerprint
STACK_FILES=(
  "cdk/lib/etl-kb-stack.ts"
  "cdk/lib/utils/parameter-models.ts"
  "cdk/parameter.ts"
  "cdk/bin/infrastructure.ts"
  "cdk/package.json"
  "cdk/package-lock.json"
  "cdk/cdk.json"
  "cdk/tsconfig.json"
)

# ── 2. Compute fingerprints (null-delimited; hashes file CONTENTS, not just
#       the path list — an in-place edit of an existing file must change the
#       hash) ─────────────────────────────────────────────────────────────────
# Release automation updates the digibro-backend package version in both
# backend/pyproject.toml and its editable uv.lock entry on every release. Those
# metadata-only changes do not affect the ETL image, so normalize only those
# fields (on the IMAGE set only) while retaining all dependency declarations
# and resolved versions.
collect_paths() {
  local -n dirs_ref=$1
  local -n files_ref=$2
  for d in "${dirs_ref[@]}"; do
    [ -d "$d" ] && find "$d" -type f -print0
  done
  for f in "${files_ref[@]}"; do
    [ -f "$f" ] && printf '%s\0' "$f"
  done
}

normalized_contents() {
  local path="$1"

  case "$path" in
    backend/pyproject.toml)
      awk '
        /^\[/ { in_project = ($0 == "[project]") }
        in_project && /^[[:space:]]*version[[:space:]]*=/ {
          print "version = \"<release-version>\""
          next
        }
        { print }
      ' "$path"
      ;;
    uv.lock)
      awk '
        /^\[\[package\]\]$/ { in_backend_package = 0 }
        /^name = "digibro-backend"$/ { in_backend_package = 1 }
        in_backend_package && /^version = / {
          print "version = \"<release-version>\""
          next
        }
        { print }
      ' "$path"
      ;;
    *)
      command cat "$path"
      ;;
  esac
}

fingerprint_entry() {
  local path="$1"
  local digest

  digest=$(normalized_contents "$path" | sha256sum | cut -d' ' -f1)
  printf '%s  %s\n' "$digest" "$path"
}

compute_fingerprint() {
  local -n dirs_ref=$1
  local -n files_ref=$2
  local entries

  entries=$(
    while IFS= read -r -d '' path; do
      fingerprint_entry "$path"
    done < <(collect_paths "$1" "$2" | sort -z)
  )
  printf '%s\n' "$entries" | sha256sum | cut -d' ' -f1
}

IMAGE_FINGERPRINT=$(compute_fingerprint IMAGE_DIRS IMAGE_FILES)
STACK_FINGERPRINT=$(compute_fingerprint STACK_DIRS STACK_FILES)

echo "ETL image fingerprint: ${IMAGE_FINGERPRINT}" >&2
echo "ETL stack fingerprint: ${STACK_FINGERPRINT}" >&2

# ── 3. Compare against the stored composite (fail toward "changed") ─────────
STORED_VALUE=$(aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --query Parameter.Value --output text \
  --region "$REGION" 2>/dev/null || echo "")

STORED_IMAGE_FINGERPRINT=""
STORED_STACK_FINGERPRINT=""
if [ -n "$STORED_VALUE" ]; then
  # jq -e fails (empty output) on unparseable JSON or a missing field —
  # `|| true` keeps set -e from aborting; the empty-string result below then
  # correctly fails that signal open. Covers: legacy bare-sha value (not JSON
  # at all), truncated/corrupt JSON, and a JSON value missing a field.
  STORED_IMAGE_FINGERPRINT=$(printf '%s' "$STORED_VALUE" \
    | jq -e -r '.image // empty' 2>/dev/null || true)
  STORED_STACK_FINGERPRINT=$(printf '%s' "$STORED_VALUE" \
    | jq -e -r '.stack // empty' 2>/dev/null || true)
fi

if [ -n "$STORED_IMAGE_FINGERPRINT" ] \
  && [ "$STORED_IMAGE_FINGERPRINT" = "$IMAGE_FINGERPRINT" ]; then
  echo "ETL image code unchanged (${IMAGE_FINGERPRINT})" >&2
  ETL_IMAGE_CHANGED="false"
else
  if [ -z "$STORED_IMAGE_FINGERPRINT" ]; then
    echo "No stored ETL image fingerprint (fail-open) — treating as changed" >&2
  else
    echo "ETL image fingerprint changed: ${STORED_IMAGE_FINGERPRINT} -> ${IMAGE_FINGERPRINT}" >&2
  fi
  ETL_IMAGE_CHANGED="true"
fi

if [ -n "$STORED_STACK_FINGERPRINT" ] \
  && [ "$STORED_STACK_FINGERPRINT" = "$STACK_FINGERPRINT" ]; then
  echo "ETL stack code unchanged (${STACK_FINGERPRINT})" >&2
  ETL_STACK_CHANGED="false"
else
  if [ -z "$STORED_STACK_FINGERPRINT" ]; then
    echo "No stored ETL stack fingerprint (fail-open) — treating as changed" >&2
  else
    echo "ETL stack fingerprint changed: ${STORED_STACK_FINGERPRINT} -> ${STACK_FINGERPRINT}" >&2
  fi
  ETL_STACK_CHANGED="true"
fi

# ── 4. Emit dotenv ────────────────────────────────────────────────────────────
echo "ETL_IMAGE_CHANGED=${ETL_IMAGE_CHANGED}"
echo "ETL_STACK_CHANGED=${ETL_STACK_CHANGED}"
echo "ETL_IMAGE_FINGERPRINT=${IMAGE_FINGERPRINT}"
echo "ETL_STACK_FINGERPRINT=${STACK_FINGERPRINT}"
