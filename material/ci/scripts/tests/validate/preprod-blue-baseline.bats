#!/usr/bin/env bats
# #642 — preprod legacy blue baseline. Covers the offline-verifiable behaviour of
# the generalized capture/copy/activate operator scripts and the CI validation:
# three-line pin + schema-v2 manifest gate, env parameterization/guards,
# fixture-based QA release_id compatibility (no live re-run), and the #631
# composite/component raw-manifest round-trip against the real validator.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../../../.." && pwd)"
  VALIDATE="${REPO_ROOT}/.gitlab/ci/scripts/validate/validate-preprod-blue-baseline.sh"
  CAPTURE="${REPO_ROOT}/scripts/capture-blue-baseline.sh"
  COPY="${REPO_ROOT}/scripts/copy-blue-etl-image.sh"
  ACTIVATE="${REPO_ROOT}/scripts/activate-blue-baseline-selector.sh"
  TOKENIZER_RESOLVER="${REPO_ROOT}/.gitlab/ci/scripts/deploy/resolve-blue-baseline-tokenizer-revision.sh"
  RELEASE="${REPO_ROOT}/.gitlab/ci/scripts/lib/node/retrieval-release.mjs"
  LIB="${REPO_ROOT}/.gitlab/ci/scripts/lib/qa-retrieval.sh"
  QA_RELEASE_ID="sha256-4a68e8e7f1bfa474a9d2c955a0c208e5229fbfa8c723a554d9266e165958325a"
  PREPROD_RELEASE_ID="sha256-d1d9d308991646cd81c3106a94fd89365bb8876ac736ab9e1bcb922038fe534b"
  TEST_TMP="$(mktemp -d)"
}
teardown() { rm -rf "$TEST_TMP"; }

_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

_first_line_number() {
  grep -nF -- "$2" "$1" | head -1 | cut -d: -f1
}

_last_exact_line_number() {
  grep -nE -- "$2" "$1" | tail -1 | cut -d: -f1
}

# ── Group A: CI validation gate (three-line pin + schema-v2 manifest) ──────────

@test "[642] a three-line preprod pin passes validation with the derived release_id" {
  # Fixture, not the committed pin: MR1 defers the three-line pin to a follow-up
  # (merged during the migration window), so the committed file is still one line.
  printf 'version: 1.83.3\ndata_artifact_version: v1.83.3-preprod-blue-baseline\netl_version: v1.83.3-preprod-blue-baseline\n' >"$TEST_TMP/pin.yaml"
  PREPROD_VERSION_PIN="$TEST_TMP/pin.yaml" run "$VALIDATE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"$PREPROD_RELEASE_ID"* ]]
  [[ "$output" == *"schema-v2 baseline manifest shape validated"* ]]
}

@test "[642] validation rejects a wrong chatbot version" {
  printf 'version: 1.84.0\ndata_artifact_version: v1.83.3-preprod-blue-baseline\netl_version: v1.83.3-preprod-blue-baseline\n' >"$TEST_TMP/pin.yaml"
  PREPROD_VERSION_PIN="$TEST_TMP/pin.yaml" run "$VALIDATE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"version must be 1.83.3"* ]]
}

@test "[642] validation rejects a non-synthetic data coordinate" {
  printf 'version: 1.83.3\ndata_artifact_version: v1.83.3\netl_version: v1.83.3-preprod-blue-baseline\n' >"$TEST_TMP/pin.yaml"
  PREPROD_VERSION_PIN="$TEST_TMP/pin.yaml" run "$VALIDATE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"data_artifact_version must be"* ]]
}

@test "[642] validation rejects a pin that is not exactly three lines" {
  printf 'version: 1.83.3\ndata_artifact_version: v1.83.3-preprod-blue-baseline\netl_version: v1.83.3-preprod-blue-baseline\nextra: nope\n' >"$TEST_TMP/pin.yaml"
  PREPROD_VERSION_PIN="$TEST_TMP/pin.yaml" run "$VALIDATE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"exactly three lines"* ]]
}

@test "[642] legacy ^version: parser still yields the chatbot version from the three-line pin" {
  # Must not hardcode a version: the preprod pin moves with every promotion (it
  # left the 1.83.3 blue baseline the moment #643's first promotion MR merged).
  # The property under test is that the legacy single-line `^version:` parser
  # still extracts exactly the chatbot version from a three-line pin.
  PIN="${REPO_ROOT}/deployments/preprod/version.yaml"
  run bash -c "grep '^version:' '$PIN' | sed 's/version: //'"
  [ "$status" -eq 0 ]
  # exactly one match, shaped like a semver, and equal to the pin's own value
  [ "$(grep -c '^version:' "$PIN")" -eq 1 ]
  [[ "$output" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
  [ "$output" = "$(awk -F': *' '$1 == "version" {print $2; exit}' "$PIN")" ]
  # and the pin really is the three-line form this parser has to survive
  [ "$(grep -cE '^(version|data_artifact_version|etl_version):' "$PIN")" -eq 3 ]
}

# ── Group B: env parameterization guards (fail fast before any AWS call) ───────

@test "[642] capture rejects an unknown --env" {
  run "$CAPTURE" --env bogus
  [ "$status" -eq 2 ]
  [[ "$output" == *"--env must be qa or preprod"* ]]
}

@test "[642] copy rejects an unknown --env" {
  run "$COPY" --env bogus
  [ "$status" -eq 2 ]
  [[ "$output" == *"--env must be qa or preprod"* ]]
}

@test "[642] activate rejects a missing --env" {
  run "$ACTIVATE"
  [ "$status" -eq 2 ]
  [[ "$output" == *"--env must be qa, preprod, or prod"* ]]
}

# ── Group C: fail-closed operator-script safety contracts ─────────────────────

@test "[642] operator scripts are syntactically valid" {
  run bash -n "$CAPTURE" "$COPY" "$ACTIVATE" "$VALIDATE" "$TOKENIZER_RESOLVER"
  [ "$status" -eq 0 ]
}

@test "[642] image-declared tokenizer revision is accepted" {
  run "$TOKENIZER_RESOLVER" "declared:cistem-decompound-v1"
  [ "$status" -eq 0 ]
  [ "$output" = "cistem-decompound-v1" ]
}

@test "[642] exact legacy 1.83.3 tokenizer sources attest cistem-decompound-v1" {
  run "$TOKENIZER_RESOLVER" \
    "legacy-source-sha256:7086817778eb7edc2cef7aea7961ccaccb5762054d44fd9b8ee842f4a96d625c:92fee32ec0ea36ade49eb01c0d281129a6a6025dc7ec0a2bf60d0d73a5e68604:827aa79c4dc95af582d7b5db8be31374a6e76e667212b8d1d9e5ab07001964cb"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Legacy tokenizer source fingerprint attested as cistem-decompound-v1."* ]]
  [[ "$output" == *"cistem-decompound-v1"* ]]
}

@test "[642] unknown legacy tokenizer sources fail closed" {
  run "$TOKENIZER_RESOLVER" \
    "legacy-source-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown legacy tokenizer source fingerprint"* ]]
}

@test "[642] execute drains, disables, and brackets the authoritative snapshot in order" {
  pre_drain=$(_first_line_number "$CAPTURE" 'qa_retrieval_wait_queue_empty "$arn" "pre-capture queue')
  disable=$(_first_line_number "$CAPTURE" 'update-event-source-mapping --uuid "$uuid" --no-enabled')
  post_disable=$(_first_line_number "$CAPTURE" 'qa_retrieval_wait_queue_empty "$arn" "disabled pre-capture queue')
  fingerprint_before=$(_first_line_number "$CAPTURE" 'live_state_fingerprint "$PROCESSED_BUCKET" "$SNAPSHOT_STATE_BEFORE"')
  snapshot=$(_last_exact_line_number "$CAPTURE" '^snapshot_and_validate$')
  fingerprint_after=$(_first_line_number "$CAPTURE" 'live_state_fingerprint "$PROCESSED_BUCKET" "$BEFORE_STATE"')

  [ "$pre_drain" -lt "$disable" ]
  [ "$disable" -lt "$post_disable" ]
  [ "$post_disable" -lt "$fingerprint_before" ]
  [ "$fingerprint_before" -lt "$snapshot" ]
  [ "$snapshot" -lt "$fingerprint_after" ]
  grep -F 'cmp -s "$SNAPSHOT_STATE_BEFORE" "$BEFORE_STATE"' "$CAPTURE"
}

@test "[642] abort after raw writes never blindly restores dirty event queues" {
  cleanup_body=$(sed -n '/^cleanup() {/,/^}/p' "$CAPTURE")
  [[ "$cleanup_body" == *'[ "$RAW_COPY_STARTED" = true ] && [ "$COPY_EVENT_QUEUES_CLEAN" != true ]'* ]]
  [[ "$cleanup_body" == *'Purge/drain the listed queues before re-enabling'* ]]
  [[ "$cleanup_body" == *$'else\n    restore_pipeline'* ]]
  grep -x 'RAW_COPY_STARTED=true' "$CAPTURE"
  grep -x 'COPY_EVENT_QUEUES_CLEAN=true' "$CAPTURE"
}

@test "[642] activation binds the immutable ETL tag to the manifest digest" {
  grep -F -- '--image-ids imageTag="$ETL_VERSION_MANIFEST"' "$ACTIVATE"
  grep -F '[ "$ETL_TAG_DIGEST" = "$ETL_IMAGE_DIGEST" ]' "$ACTIVATE"
  ! grep -F -- '--image-ids imageDigest="$ETL_IMAGE_DIGEST"' "$ACTIVATE"
}

@test "[642] evidence inventory is exact and fails closed on queue or DLQ reads" {
  grep -F 'BM25_QUEUE_ARN="$(ssm_value "${SLOT_BASE}/bm25-rebuild-queue-arn")"' "$CAPTURE"
  grep -F 'queue_depth=$(qa_retrieval_queue_depth "$arn")' "$CAPTURE"
  grep -F 'TRANSFORM_DLQ_DEPTH=$(qa_retrieval_dlq_depth "$TRANSFORM_DLQ_ARN")' "$CAPTURE"
  grep -F 'event_source_queues:$event_source_queues[0]' "$CAPTURE"
  grep -F 'dlqs:({transform:{arn:$transform_dlq,depth:$transform_dlq_depth}' "$CAPTURE"
  ! grep -F '|| echo "NA"' "$CAPTURE"
}

# ── Group D: fixture-based QA compatibility (no live re-run) ───────────────────

@test "[642] QA release_id derivation matches the historical constant" {
  run node "$RELEASE" derive-release 1.83.3 v1.83.3-qa-blue-baseline v1.83.3-qa-blue-baseline
  [ "$status" -eq 0 ]
  [ "$output" = "$QA_RELEASE_ID" ]
}

@test "[642] preprod release_id derivation is deterministic" {
  run node "$RELEASE" derive-release 1.83.3 v1.83.3-preprod-blue-baseline v1.83.3-preprod-blue-baseline
  [ "$status" -eq 0 ]
  [ "$output" = "$PREPROD_RELEASE_ID" ]
}

# ── Group E: #631 composite/component raw-manifest round-trip ──────────────────

_build_raw_layout() {
  # Build the same composite + component + object layout the capture script
  # uploads, into a local "bucket" dir. Echoes the coordinate + raw prefix.
  local bucket_dir="$1" coord="v1.83.3-preprod-blue-baseline" prefix
  prefix="releases/${coord}/"
  mkdir -p "${bucket_dir}/${prefix}xml" "${bucket_dir}/${prefix}pdf" "${bucket_dir}/${prefix}html"
  printf '<x/>' >"${bucket_dir}/${prefix}xml/a.xml"
  printf '%%PDF' >"${bucket_dir}/${prefix}pdf/b.pdf"
  printf '<html></html>' >"${bucket_dir}/${prefix}html/faq.html"
  jq -n --arg c "$coord" '{version:$c,files:{xml:["xml/a.xml"],pdf:["pdf/b.pdf"]}}' \
    >"${bucket_dir}/${prefix}brochure-manifest.json"
  jq -n --arg c "$coord" '{schema_version:1,coordinate:$c,files:["html/faq.html"]}' \
    >"${bucket_dir}/${prefix}faq-manifest.json"
  local bsha fsha
  bsha=$(_sha256 "${bucket_dir}/${prefix}brochure-manifest.json")
  fsha=$(_sha256 "${bucket_dir}/${prefix}faq-manifest.json")
  jq -n --arg c "$coord" --arg p "$prefix" --arg bk "${prefix}brochure-manifest.json" \
    --arg bs "$bsha" --arg fk "${prefix}faq-manifest.json" --arg fs "$fsha" \
    '{schema_version:1,coordinate:$c,components:{
       brochure:{artifact_version:$c,bucket:"b",prefix:$p,manifest_key:$bk,manifest_sha256:$bs},
       faq:{artifact_version:$c,bucket:"b",prefix:$p,manifest_key:$fk,manifest_sha256:$fs}}}' \
    >"${bucket_dir}/${prefix}manifest.json"
  echo "$prefix"
}

# Local `aws` stub mapping s3api head-object / s3 cp to $BUCKET_DIR.
_aws_stub() {
  aws() {
    local key="" i
    if [ "$1" = "s3api" ] && [ "$2" = "head-object" ]; then
      shift 2
      while [ "$#" -gt 0 ]; do case "$1" in --key) key="$2"; shift 2;; *) shift;; esac; done
      [ -f "${BUCKET_DIR}/${key}" ] && return 0
      echo "Not Found" >&2; return 254
    elif [ "$1" = "s3" ] && [ "$2" = "cp" ]; then
      local src="$3" dest="$4"; key="${src#s3://*/}"
      cp "${BUCKET_DIR}/${key}" "$dest"; return $?
    fi
    return 0
  }
}

@test "[642] a complete captured raw layout passes qa_retrieval_composite_manifest_complete" {
  BUCKET_DIR="$TEST_TMP/bucket"
  prefix="$(_build_raw_layout "$BUCKET_DIR")"
  # shellcheck disable=SC1090
  source "$LIB"
  _aws_stub
  run qa_retrieval_composite_manifest_complete "b" "$prefix" "$TEST_TMP/out.json"
  [ "$status" -eq 0 ]
}

@test "[642] a truncated raw layout (missing declared object) fails validation" {
  BUCKET_DIR="$TEST_TMP/bucket"
  prefix="$(_build_raw_layout "$BUCKET_DIR")"
  rm -f "${BUCKET_DIR}/${prefix}pdf/b.pdf"   # declared in brochure manifest but now absent
  # shellcheck disable=SC1090
  source "$LIB"
  _aws_stub
  run qa_retrieval_composite_manifest_complete "b" "$prefix" "$TEST_TMP/out.json"
  [ "$status" -ne 0 ]
}
