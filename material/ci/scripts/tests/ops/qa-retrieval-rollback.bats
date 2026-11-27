#!/usr/bin/env bats
# #493 tests for the standalone QA retrieval rollback script.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
ROLLBACK="$REPO_ROOT/.gitlab/ci/scripts/ops/rollback-retrieval.sh"
COMMON="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval.sh"
VALIDATION="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval-validation.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Build a minimal valid schema-v3 manifest JSON with the given release_id and
# tokenizer revision. KB/bucket/prefix fields are fixed so tests can assert on
# them.
make_manifest() {
  local release_id="$1" tokenizer="${2:-cistem-decompound-v1}" artifact_id="${3:-sha256-1111111111111111111111111111111111111111111111111111111111111111}"
  jq -cn \
    --arg release_id "$release_id" \
    --arg tokenizer "$tokenizer" \
    --arg artifact_id "$artifact_id" \
    '{
      schema_version: 3,
      release_id: $release_id,
      version: "1.0.0",
      data_artifact_version: "v1.0.0",
      etl_version: "v1.0.0",
      knowledge_base_id: "KBID12345",
      data_source_id: "DSID12345",
      raw_bucket: "qa-raw-bucket",
      raw_prefix: "releases/v1.0.0/",
      processed_bucket: "qa-processed-bucket",
      processed_prefix: ("processed/releases/" + $artifact_id + "/"),
      bm25_bucket: "qa-processed-bucket",
      bm25_key: ("bm25_index/releases/" + $artifact_id + "/index.json"),
      bm25_tokenizer_revision: $tokenizer,
      etl_image_digest: ("sha256:" + ("a" * 64)),
      retrieval_artifact_id: $artifact_id,
      retrieval_artifact_fingerprint: ("sha256:" + ("b" * 64)),
      chatbot_image_digest: ("sha256:" + ("c" * 64))
    }'
}

# Fake `aws` that dispatches on the SSM/bedrock-agent/s3api/lambda/cloudformation
# calls the rollback script makes, backed by files in $TEST_DIR so callers can
# preset state (SSM values, pin state, KB reachability) per test.
install_fake_aws() {
  cat >"$TEST_DIR/bin/aws" <<'FAKE_AWS'
#!/usr/bin/env bash
set -euo pipefail
TEST_DIR="${TEST_DIR:?}"
log_call() { printf '%s\n' "$*" >>"$TEST_DIR/aws-calls.log"; }
log_call "$*"

if [[ "$1 $2" == "ssm get-parameter" ]]; then
  name=""
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--name" ]]; then
      j=$((i+1)); name="${!j}"
    fi
  done
  file="$TEST_DIR/ssm-$(basename "$name").json"
  if [[ -s "$file" ]]; then
    value=$(cat "$file")
    printf '%s' "$value"
  else
    echo "ParameterNotFound" >&2
    exit 254
  fi
  exit 0
fi

if [[ "$1 $2" == "ssm put-parameter" ]]; then
  name="" value_arg=""
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--name" ]]; then j=$((i+1)); name="${!j}"; fi
    if [[ "${!i}" == "--value" ]]; then j=$((i+1)); value_arg="${!j}"; fi
  done
  file="$TEST_DIR/ssm-$(basename "$name").json"
  if [[ "$value_arg" == file://* ]]; then
    cp "${value_arg#file://}" "$file"
  else
    printf '%s' "$value_arg" >"$file"
  fi
  exit 0
fi

if [[ "$1 $2" == "sts get-caller-identity" ]]; then
  echo '{"Account":"000000000000"}'
  exit 0
fi

if [[ "$1 $2" == "sts assume-role-with-web-identity" ]]; then
  printf 'FAKEKEY\tFAKESECRET\tFAKETOKEN\n'
  exit 0
fi

if [[ "$1 $2" == "bedrock-agent get-knowledge-base" ]]; then
  if [[ -f "$TEST_DIR/kb-access-denied" ]]; then
    echo "An error occurred (AccessDeniedException) when calling the GetKnowledgeBase operation: User is not authorized to perform: bedrock-agent:GetKnowledgeBase" >&2
    exit 254
  fi
  if [[ -f "$TEST_DIR/kb-unreachable" ]]; then
    echo "An error occurred (ResourceNotFoundException) when calling the GetKnowledgeBase operation" >&2
    exit 254
  fi
  echo '{"knowledgeBase":{}}'
  exit 0
fi

if [[ "$1 $2" == "s3api get-object-tagging" ]]; then
  key=""
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--key" ]]; then j=$((i+1)); key="${!j}"; fi
  done
  safe_key=$(printf '%s' "$key" | tr '/' '_')
  if [[ -f "$TEST_DIR/unpinned-${safe_key}" ]]; then
    echo '{"TagSet":[{"Key":"renate:retention","Value":"unpinned"}]}'
  else
    echo '{"TagSet":[{"Key":"renate:retention","Value":"pinned"}]}'
  fi
  exit 0
fi

if [[ "$1 $2" == "cloudformation list-stack-resources" ]]; then
  printf '{"StackResourceSummaries":[{"ResourceType":"AWS::S3::Bucket","PhysicalResourceId":"some-bucket"},{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-chat-fn"}]}\n'
  exit 0
fi

if [[ "$1 $2" == "lambda get-function-configuration" ]]; then
  printf '%s' "${FAKE_ACTIVE_SELECTOR:-/qa/renate/retrieval/active-manifest}"
  exit 0
fi

if [[ "$1 $2" == "lambda invoke" ]]; then
  # Positional response-file arg is the one right before --output.
  out=""
  prev=""
  for arg in "$@"; do
    if [[ "$prev" != --* && "$arg" == "--output" ]]; then
      out="$prev"
    fi
    prev="$arg"
  done
  release_id=$(cat "$TEST_DIR/expected-release-id" 2>/dev/null || echo "")
  jq -n --arg r "$release_id" '{ok:true, mode:"semantic", release_id:$r, observed_release_ids:[$r]}' >"$out"
  echo '{}'
  exit 0
fi

echo "unexpected aws call: $*" >&2
exit 98
FAKE_AWS
  chmod +x "$TEST_DIR/bin/aws"
}

install_fake_node() {
  # retrieval-release.mjs validate: accept unless $TEST_DIR/node-validate-fail
  # exists. retrieval-orchestration.mjs subcommands are pure decision logic
  # with no AWS/network access, so delegate to the real module via the real
  # node binary found earlier on PATH -- only retrieval-release.mjs's
  # `validate` entrypoint is stubbed here (it has no bearing on rollback's
  # coherence/confirmation/swap decisions under test).
  local real_node
  real_node=$(command -v node)
  cat >"$TEST_DIR/bin/node" <<FAKE_NODE
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1" == */retrieval-orchestration.mjs || "\$1" == */retrieval-environment.mjs ]]; then
  exec "$real_node" "\$@"
fi
if [[ -f "$TEST_DIR/node-validate-fail" ]]; then
  echo "retrieval-release: manifest invalid" >&2
  exit 1
fi
exit 0
FAKE_NODE
  chmod +x "$TEST_DIR/bin/node"
}

set_ssm() {
  local name="$1" manifest_json="$2"
  printf '%s' "$manifest_json" >"$TEST_DIR/ssm-$(basename "$name").json"
}

@test "[#493 preflight] aborts when previous-manifest SSM parameter is missing" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"no previous retrieval manifest is configured"* ]]
}

@test "[#493 preflight] aborts when the BM25 index object is not pinned" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-aaaa000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-bbbb000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  bm25_key=$(printf '%s' "$previous" | jq -r .bm25_key)
  touch "$TEST_DIR/unpinned-$(printf '%s' "$bm25_key" | tr '/' '_')"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"retention is unpinned, expected pinned"* ]]
}

@test "[#493 preflight] aborts when the KB does not exist (ResourceNotFoundException)" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-cccc000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-dddd000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  touch "$TEST_DIR/kb-unreachable"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"does not exist (ResourceNotFoundException)"* ]]
  [[ "$output" != *"access denied"* ]]
}

@test "[#493 preflight] distinguishes an IAM AccessDenied from a missing KB" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-abab000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-cdcd000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  touch "$TEST_DIR/kb-access-denied"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"access denied"* ]]
  [[ "$output" == *"bedrock-agent:GetKnowledgeBase"* ]]
  [[ "$output" == *"IAM problem, not evidence the KB is gone"* ]]
  [[ "$output" != *"does not exist"* ]]
}

@test "[#493 coherence] aborts on tokenizer mismatch and does not write SSM" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-eeee000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-v0 sha256-ffff000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  cp "$TEST_DIR/ssm-active-manifest.json" "$TEST_DIR/active-manifest-before-run.json"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"Coherence FAILED"* ]]
  [[ "$output" == *"a full"*"application rollback"* ]]
  cmp -s "$TEST_DIR/active-manifest-before-run.json" "$TEST_DIR/ssm-active-manifest.json"
}

@test "[#493 dry-run] never calls aws ssm put-parameter or aws lambda invoke" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-1010000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-2020000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  export TEST_DIR REPO_ROOT
  DRY_RUN=true PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"Rollback is armed. No parameters written."* ]]
  ! grep -q "ssm put-parameter" "$TEST_DIR/aws-calls.log"
  ! grep -q "lambda invoke" "$TEST_DIR/aws-calls.log"
}

@test "[#493 swap] writes the active selector before the previous selector" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-3030000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-4040000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  echo "sha256-good" >"$TEST_DIR/expected-release-id"
  export TEST_DIR REPO_ROOT EXPECTED_TARGET_RELEASE_ID=sha256-good GITLAB_OIDC_TOKEN=fake-token CI_JOB_ID=1 \
    QA_RETRIEVAL_PROMOTION_ROLE_ARN=arn:aws:iam::000000000000:role/fake
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -eq 0 ]
  active_line=$(grep -n "ssm put-parameter --name /qa/renate/retrieval/active-manifest" "$TEST_DIR/aws-calls.log" | head -1 | cut -d: -f1)
  previous_line=$(grep -n "ssm put-parameter --name /qa/renate/retrieval/previous-manifest" "$TEST_DIR/aws-calls.log" | head -1 | cut -d: -f1)
  [ -n "$active_line" ]
  [ -n "$previous_line" ]
  [ "$active_line" -lt "$previous_line" ]
}

@test "[#493 verify] diagnostic poll respects the RTO timeout and fails closed on mismatch" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-5050000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-6060000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  # Diagnostic will always report sha256-wrong, never matching the expected
  # rollback target sha256-good -> must fail closed once RTO elapses.
  echo "sha256-wrong" >"$TEST_DIR/expected-release-id"
  export TEST_DIR REPO_ROOT EXPECTED_TARGET_RELEASE_ID=sha256-good GITLAB_OIDC_TOKEN=fake-token CI_JOB_ID=1 \
    QA_RETRIEVAL_PROMOTION_ROLE_ARN=arn:aws:iam::000000000000:role/fake QA_RETRIEVAL_RTO_SECONDS=1
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"did not observe sha256-good"* ]]
}

@test "[#493 double-rollback] CI run aborts when EXPECTED_TARGET_RELEASE_ID does not match" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-7070000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-8080000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  export TEST_DIR REPO_ROOT EXPECTED_TARGET_RELEASE_ID=sha256-not-the-target GITLAB_OIDC_TOKEN=fake-token CI_JOB_ID=1 \
    QA_RETRIEVAL_PROMOTION_ROLE_ARN=arn:aws:iam::000000000000:role/fake
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"does not match rollback target sha256-good"* ]]
  ! grep -q "ssm put-parameter" "$TEST_DIR/aws-calls.log"
}

@test "[#493 no-op] aborts when active and previous already name the same release" {
  install_fake_aws
  install_fake_node
  same=$(make_manifest sha256-same cistem-decompound-v1 sha256-9090000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$same"
  set_ssm /qa/renate/retrieval/previous-manifest "$same"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"nothing to roll back"* ]]
}

@test "[#493 shared helper] activation and rollback consume the same convergence poll" {
  activation="$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"
  grep -q 'qa_retrieval_wait_for_release_convergence' "$activation"
  grep -q 'qa_retrieval_wait_for_release_convergence' "$ROLLBACK"
  grep -q 'qa_retrieval_wait_for_release_convergence()' "$VALIDATION"
  grep -q 'qa_retrieval_resolve_chat_function()' "$VALIDATION"
  grep -q 'qa_retrieval_resolve_chat_function' "$activation"
  grep -q 'qa_retrieval_resolve_chat_function' "$ROLLBACK"
}

@test "[#493 scope] rollback script never triggers a CDK deploy" {
  ! grep -q 'cdk deploy' "$ROLLBACK"
  ! grep -q 'npx cdk' "$ROLLBACK"
}

# ── #628: degraded-rollback marker guard ─────────────────────────────────────

@test "[#628 guard] aborts before preflight when the degraded marker is present" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-1111000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-2222000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  set_ssm /qa/renate/retrieval/rollback-degraded '{"schema_version":1,"release_id":"sha256-candidate"}'
  # Make a real preflight failure detectable if the guard did NOT short-circuit.
  touch "$TEST_DIR/kb-unreachable"
  export TEST_DIR REPO_ROOT
  PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"fast rollback is degraded"* ]]
  [[ "$output" == *"493 runbook"* ]]
  # The abort happened before preflight's KB check ran.
  [[ "$output" != *"does not exist (ResourceNotFoundException)"* ]]
  ! grep -q "bedrock-agent get-knowledge-base" "$TEST_DIR/aws-calls.log"
  ! grep -q "ssm put-parameter" "$TEST_DIR/aws-calls.log"
}

@test "[#628 guard] a dry run also reports the degraded marker" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-3333000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-4444000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  set_ssm /qa/renate/retrieval/rollback-degraded '{"schema_version":1,"release_id":"sha256-candidate"}'
  export TEST_DIR REPO_ROOT
  DRY_RUN=true PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -ne 0 ]
  [[ "$output" == *"fast rollback is degraded"* ]]
  [[ "$output" != *"Rollback is armed. No parameters written."* ]]
}

@test "[#628 guard] FORCE=true proceeds past the marker and warns" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-5555000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-6666000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  set_ssm /qa/renate/retrieval/rollback-degraded '{"schema_version":1,"release_id":"sha256-candidate"}'
  export TEST_DIR REPO_ROOT
  FORCE=true DRY_RUN=true PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"proceeding with FORCE=true while the degraded-rollback marker is set"* ]]
  [[ "$output" == *"Rollback is armed. No parameters written."* ]]
}

@test "[#628 guard] absent marker is a no-op (ParameterNotFound tolerated)" {
  install_fake_aws
  install_fake_node
  active=$(make_manifest sha256-bad cistem-decompound-v1 sha256-7777000000000000000000000000000000000000000000000000000000000000)
  previous=$(make_manifest sha256-good cistem-decompound-v1 sha256-8888000000000000000000000000000000000000000000000000000000000000)
  set_ssm /qa/renate/retrieval/active-manifest "$active"
  set_ssm /qa/renate/retrieval/previous-manifest "$previous"
  # No rollback-degraded SSM value set at all.
  export TEST_DIR REPO_ROOT
  DRY_RUN=true PATH="$TEST_DIR/bin:$PATH" run bash "$ROLLBACK" qa
  [ "$status" -eq 0 ]
  [[ "$output" != *"fast rollback is degraded"* ]]
  [[ "$output" == *"Rollback is armed. No parameters written."* ]]
}

@test "[#628 guard] deploy-retrieval-chatbot.sh performs no docs/ mutation" {
  chatbot="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
  ! grep -q 's3 rm .*docs/' "$chatbot"
  ! grep -q 'CANDIDATE_LIVE_MUTATED' "$chatbot"
}
