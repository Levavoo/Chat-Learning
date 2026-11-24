#!/usr/bin/env bats
# Tests for .gitlab/ci/scripts/deploy/deploy-and-verify-etl-dev.sh
# Covers the #590 review fix (issues #3/#4/#7): the merged deploy+readiness
# job must capture its DLQ baseline/timestamp BEFORE calling cdk deploy (not
# after), and must never release/re-acquire the resource_group lock between
# the deploy and the readiness gate (enforced structurally — one script, one
# job, one lock — verified here by checking baseline capture happens before
# the "cdk deploy" stub is invoked and readiness uses the pre-deploy values).

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/deploy/deploy-and-verify-etl-dev.sh"
REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../.." && pwd)"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/cdk"
  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-token"
  export CI_JOB_ID="42"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::831926590742:role/ki-lab-digibro-dev-cdk-deploy"
  export AWS_DEFAULT_REGION="eu-central-1"
  export TEST_DIR_ENV="$TEST_DIR"
  # Keep the readiness gate's grace/poll/timeout phases near-instant — the
  # production defaults (30s grace, 15s poll, 900s timeout) would make every
  # test take minutes otherwise.
  export ETL_READINESS_GRACE_SECONDS=0
  export ETL_READINESS_POLL_INTERVAL_SECONDS=0
  export ETL_READINESS_CONSECUTIVE_EMPTY=1
  export ETL_READINESS_TIMEOUT_SECONDS=5

  # Pre-existing ETL stack queue/DLQ ARNs — present, so the "fresh env, no
  # baseline" skip path is NOT exercised by default.
  echo "arn:aws:sqs:eu-central-1:123456789012:transform-dlq" >"$TEST_DIR/transform_dlq_arn"
  echo "arn:aws:sqs:eu-central-1:123456789012:bm25-dlq" >"$TEST_DIR/bm25_dlq_arn"

  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "cdk-deploy-called" >> "$TEST_DIR/call_order"
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$REPO_ROOT/outputs-etl.json"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"

  _aws_stub
}

teardown() {
  rm -rf "$TEST_DIR"
  rm -f "$REPO_ROOT/outputs-etl.json"
}

# aws stub covering: assume-role, get-caller-identity, ssm get/put-parameter,
# sqs get-queue-attributes (DLQ baseline, fixed depth unless overridden),
# bedrock-agent list-ingestion-jobs (always reports a fresh COMPLETE job),
# lambda invoke (bm25-rebuild.sh).
_aws_stub() {
  local dlq_depth="${1:-0}"
  cat >"$TEST_DIR/bin/aws" <<STUB
#!/bin/bash
CMD="\$*"
echo "aws \$CMD" >> "$TEST_DIR/call_order"

if [[ "\$CMD" == *"assume-role-with-web-identity"* ]]; then
  printf 'AKID SECRET TOKEN\n'
  exit 0
fi
if [[ "\$CMD" == *"get-caller-identity"* ]]; then exit 0; fi

if [[ "\$CMD" == *"ssm get-parameter"* ]]; then
  if [[ "\$CMD" == *"etl-dlq-arn"* ]]; then
    cat "$TEST_DIR/transform_dlq_arn" 2>/dev/null || echo ""
    exit 0
  fi
  if [[ "\$CMD" == *"bm25-rebuild-dlq-arn"* ]]; then
    cat "$TEST_DIR/bm25_dlq_arn" 2>/dev/null || echo ""
    exit 0
  fi
  if [[ "\$CMD" == *"chunking-dlq-arn"* ]]; then
    echo ""
    exit 0
  fi
  if [[ "\$CMD" == *"bm25-builder-function-name"* ]]; then
    echo "my-bm25-fn"
    exit 0
  fi
  # Other etl-readiness-dev.sh lookups (queue arns, kb id, data source id,
  # data-artifact-version) — return a placeholder non-empty value so the
  # required-arg checks in etl-readiness-check.sh pass.
  echo "placeholder-value"
  exit 0
fi

if [[ "\$CMD" == *"ssm put-parameter"* ]]; then
  echo "fingerprint-write-called" >> "$TEST_DIR/call_order"
  # Capture the --value payload verbatim (may contain spaces/JSON) for the
  # composite-fingerprint-shape assertions.
  ARGS=("\$@")
  for i in "\${!ARGS[@]}"; do
    if [[ "\${ARGS[\$i]}" == "--value" ]]; then
      printf '%s' "\${ARGS[\$((i + 1))]}" > "$TEST_DIR/ssm_put_value"
      break
    fi
  done
  exit 0
fi

if [[ "\$CMD" == *"sqs get-queue-attributes"* ]]; then
  if [[ "\$CMD" == *"ApproximateNumberOfMessagesNotVisible"* ]]; then
    # Queue-depth call (visible + in-flight) — always empty, so the poll
    # loop's "queues drained" condition can be reached regardless of the
    # DLQ depth override under test.
    printf '{"Attributes":{"ApproximateNumberOfMessages":"0","ApproximateNumberOfMessagesNotVisible":"0"}}\n'
  else
    # DLQ-depth call — reflects the override (default 0).
    printf '{"Attributes":{"ApproximateNumberOfMessages":"%s"}}\n' "$dlq_depth"
  fi
  exit 0
fi

if [[ "\$CMD" == *"list-ingestion-jobs"* ]]; then
  NOW=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"ingestionJobSummaries":[{"startedAt":"%s","status":"COMPLETE"}]}\n' "\$NOW"
  exit 0
fi

if [[ "\$CMD" == *"lambda invoke"* ]]; then
  RESPONSE_FILE="\${@: -1}"
  echo '{}' > "\${RESPONSE_FILE}.meta"
  echo '{"NumChunks":7}' > "\${RESPONSE_FILE}"
  exit 0
fi

if [[ "\$CMD" == *"cloudformation describe-stacks"* ]]; then
  if [[ "\$CMD" == *"LastUpdatedTime"* ]]; then
    if [[ -f "$TEST_DIR/deny_stack_revision" ]]; then
      echo "An error occurred (AccessDenied) when calling DescribeStacks" >&2
      exit 254
    fi
    cat "$TEST_DIR/stack_revision" 2>/dev/null || printf '[]\n'
  else
    printf '[]\n'
  fi
  exit 0
fi

exit 0
STUB
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[deploy-and-verify-etl-dev] role var unset → exit 1 with var name in message" {
  unset CDK_DEPLOY_ROLE_ARN_DEV
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"CDK_DEPLOY_ROLE_ARN_DEV"* ]]
}

@test "[deploy-and-verify-etl-dev] happy path: deploy, readiness, bm25-rebuild, fingerprint write all succeed in order" {
  export ETL_IMAGE_CHANGED="true"
  export ETL_IMAGE_FINGERPRINT="abc123imagefingerprint"
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "renate-etl-kb-dev" "$TEST_DIR/npx_args"
  [[ "$output" == *"READINESS_RESULT=ready"* ]]
  [[ "$output" == *"7 chunks indexed"* ]]

  # DLQ-baseline capture (an `aws sqs get-queue-attributes` call) must happen
  # BEFORE cdk deploy is invoked — this is the core #3/#7 fix.
  BASELINE_LINE=$(grep -n "sqs get-queue-attributes" "$TEST_DIR/call_order" | head -1 | cut -d: -f1)
  DEPLOY_LINE=$(grep -n "cdk-deploy-called" "$TEST_DIR/call_order" | head -1 | cut -d: -f1)
  [ -n "$BASELINE_LINE" ]
  [ -n "$DEPLOY_LINE" ]
  [ "$BASELINE_LINE" -lt "$DEPLOY_LINE" ]

  # Fingerprint write must happen last (after readiness, i.e. after deploy).
  FINGERPRINT_LINE=$(grep -n "fingerprint-write-called" "$TEST_DIR/call_order" | head -1 | cut -d: -f1)
  [ -n "$FINGERPRINT_LINE" ]
  [ "$FINGERPRINT_LINE" -gt "$DEPLOY_LINE" ]
}

@test "[deploy-and-verify-etl-dev] fingerprint write composes {image,stack} JSON from both env vars" {
  export ETL_IMAGE_CHANGED="true"
  export ETL_IMAGE_FINGERPRINT="abc123imagefingerprint"
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  PUT_VALUE=$(grep "ssm put-parameter" "$TEST_DIR/call_order" | grep -o -- '--value [^ ]*' | tail -1 | cut -d' ' -f2)
  # The stub logs the raw invocation, not the --value payload verbatim
  # (spaces would break the grep) — assert via the aws stub's captured args
  # file instead for exact JSON shape.
  [ -f "$TEST_DIR/ssm_put_value" ]
  IMAGE_VAL=$(jq -r '.image' "$TEST_DIR/ssm_put_value")
  STACK_VAL=$(jq -r '.stack' "$TEST_DIR/ssm_put_value")
  [ "$IMAGE_VAL" = "abc123imagefingerprint" ]
  [ "$STACK_VAL" = "def456stackfingerprint" ]
}

@test "[deploy-and-verify-etl-dev] neither fingerprint env var set → fingerprint write is skipped" {
  unset ETL_IMAGE_FINGERPRINT
  unset ETL_STACK_FINGERPRINT
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  ! grep -q "fingerprint-write-called" "$TEST_DIR/call_order"
}

@test "[deploy-and-verify-etl-dev] only ETL_STACK_FINGERPRINT set (stack-only change) → fingerprint write still happens" {
  unset ETL_IMAGE_FINGERPRINT
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  export ETL_IMAGE_CHANGED="false"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "fingerprint-write-called" "$TEST_DIR/call_order"
  IMAGE_VAL=$(jq -r '.image' "$TEST_DIR/ssm_put_value")
  STACK_VAL=$(jq -r '.stack' "$TEST_DIR/ssm_put_value")
  [ "$IMAGE_VAL" = "" ]
  [ "$STACK_VAL" = "def456stackfingerprint" ]
}

@test "[deploy-and-verify-etl-dev] no-op CDK deploy skips ingestion wait and records fingerprint" {
  printf '%s\t%s\t%s\n' \
    "arn:aws:cloudformation:eu-central-1:123456789012:stack/renate-etl-kb-dev/id" \
    "2026-08-11T10:00:00+00:00" \
    "2026-07-01T10:00:00+00:00" \
    >"$TEST_DIR/stack_revision"
  export ETL_IMAGE_CHANGED="false"
  export ETL_IMAGE_FINGERPRINT="abc123imagefingerprint"
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"

  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"

  [ "$status" -eq 0 ]
  [[ "$output" == *"deployment was a no-op"* ]]
  [[ "$output" == *"READINESS_RESULT=no-stack-change"* ]]
  ! grep -q "list-ingestion-jobs" "$TEST_DIR/call_order"
  ! grep -q "lambda invoke" "$TEST_DIR/call_order"
  grep -q "fingerprint-write-called" "$TEST_DIR/call_order"
}

@test "[deploy-and-verify-etl-dev] missing stack-read permission fails before deploy or readiness" {
  touch "$TEST_DIR/deny_stack_revision"

  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"

  [ "$status" -eq 1 ]
  [[ "$output" == *"requires cloudformation:DescribeStacks"* ]]
  [[ "$output" == *"Refusing deployment before mutation"* ]]
  ! grep -q "cdk-deploy-called" "$TEST_DIR/call_order"
  ! grep -q "list-ingestion-jobs" "$TEST_DIR/call_order"
}

@test "[deploy-and-verify-etl-dev] ETL_IMAGE_CHANGED=true → explicit bm25-rebuild runs" {
  export ETL_IMAGE_CHANGED="true"
  export ETL_IMAGE_FINGERPRINT="abc123imagefingerprint"
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "lambda invoke" "$TEST_DIR/call_order"
  [[ "$output" == *"7 chunks indexed"* ]]
}

@test "[deploy-and-verify-etl-dev] ETL_IMAGE_CHANGED=false (stack-only) → explicit bm25-rebuild is skipped" {
  export ETL_IMAGE_CHANGED="false"
  unset ETL_IMAGE_FINGERPRINT
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  ! grep -q "lambda invoke" "$TEST_DIR/call_order"
  [[ "$output" == *"skipping redundant explicit BM25 rebuild"* ]]
}

@test "[deploy-and-verify-etl-dev] ETL_IMAGE_CHANGED unset → fail-open default true, bm25-rebuild runs" {
  unset ETL_IMAGE_CHANGED
  export ETL_IMAGE_FINGERPRINT="abc123imagefingerprint"
  export ETL_STACK_FINGERPRINT="def456stackfingerprint"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q "lambda invoke" "$TEST_DIR/call_order"
}

@test "[deploy-and-verify-etl-dev] fresh environment (no queue ARNs in SSM yet at pre-deploy capture time) skips baseline capture, still deploys and runs readiness post-deploy" {
  # Simulates a first-ever deploy: at PRE-deploy capture time the DLQ ARNs
  # don't exist yet (stack never deployed). After `cdk deploy` succeeds they
  # DO exist (the stack now publishes them) — etl-readiness-dev.sh's own
  # (post-deploy) SSM resolution must see them and self-capture a fresh
  # baseline, since no --start-ts/baseline override was passed through.
  rm -f "$TEST_DIR/transform_dlq_arn" "$TEST_DIR/bm25_dlq_arn"
  touch "$TEST_DIR/transform_dlq_arn" "$TEST_DIR/bm25_dlq_arn"

  cat >"$TEST_DIR/bin/npx" <<EOF
#!/bin/bash
echo "cdk-deploy-called" >> "$TEST_DIR/call_order"
echo "\$*" > "$TEST_DIR/npx_args"
echo '{}' > "$REPO_ROOT/outputs-etl.json"
# Simulate the stack now existing post-deploy — DLQ ARNs become resolvable.
echo "arn:aws:sqs:eu-central-1:123456789012:transform-dlq" >"$TEST_DIR/transform_dlq_arn"
echo "arn:aws:sqs:eu-central-1:123456789012:bm25-dlq" >"$TEST_DIR/bm25_dlq_arn"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/npx"

  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ETL stack not yet deployed"* ]]
  grep -q "renate-etl-kb-dev" "$TEST_DIR/npx_args"
  [[ "$output" == *"READINESS_RESULT=ready"* ]]
}

@test "[deploy-and-verify-etl-dev] passes the pre-deploy start-ts and DLQ baselines through to the readiness script" {
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT' 2>&1"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Captured pre-deploy start:"* ]]
  [[ "$output" == *"Captured pre-deploy DLQ baselines"* ]]
  [[ "$output" == *"Using caller-supplied DLQ baselines"* ]]
}

@test "[deploy-and-verify-etl-dev] ETL_IMAGE_TAG_OVERRIDE set → passes --context etlImageTag=<value> to cdk deploy" {
  export ETL_IMAGE_TAG_OVERRIDE="v1.23.0"
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
  grep -q -- "--context etlImageTag=v1.23.0" "$TEST_DIR/npx_args"
}

@test "[deploy-and-verify-etl-dev] a DLQ message present at the pre-deploy baseline is not falsely reported as an increase" {
  _aws_stub 3
  run bash -c "REPO_ROOT='$TEST_DIR' bash '$SCRIPT'"
  [ "$status" -eq 0 ]
}
