#!/usr/bin/env bats

# Tests for maintenance-switch.sh (TKT-MM-02): maintenance: key parsing,
# --dry-run, stale-flag idempotency, edge-first ordering, KVS read-back,
# and the maintenance smoke checks.
#
# The aws stub is stateful: put-key writes the flag to $TEST_DIR/kvs-state,
# get-key reads it back, put/delete-function-concurrency toggle
# $TEST_DIR/lambda-throttled. The curl stub answers from that state, so the
# smoke assertions are exercised against a simulated environment end to end.

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/ops/maintenance-switch.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/deployments/qa" "$TEST_DIR/deployments/preprod" "$TEST_DIR/deployments/dev"
  export PATH="$TEST_DIR/bin:$PATH"
  export REPO_ROOT="$TEST_DIR"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="99"
  export CDK_DEPLOY_ROLE_ARN_DEV="arn:aws:iam::831926590742:role/test-dev"
  export CDK_DEPLOY_ROLE_ARN_QA="arn:aws:iam::571600837515:role/test-qa"
  export CDK_DEPLOY_ROLE_ARN_PREPROD="arn:aws:iam::271033482134:role/test-preprod"
  # Speed up the smoke retry loop.
  export SMOKE_MAX_ATTEMPTS=2 SMOKE_BASE_DELAY_S=0 SMOKE_MAX_DELAY_S=1
  # Keep KVS read-back retry tests fast while still exercising retry behavior.
  export KVS_READBACK_MAX_ATTEMPTS=3 KVS_READBACK_BASE_DELAY_S=0 KVS_READBACK_MAX_DELAY_S=1
  echo "version: 1.90.0" >"$TEST_DIR/deployments/qa/version.yaml"
  echo "version: 1.90.0" >"$TEST_DIR/deployments/preprod/version.yaml"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  # Required by push-maintenance-rehearsed-tag.sh (TKT-MM-04), invoked by
  # maintenance-switch.sh after a real qa disable.
  export CI_SERVER_HOST="gitlab.example.com"
  export CI_PROJECT_PATH="renate/digibro-monorepo"
  export CI_JOB_TOKEN="test-token"
  export CI_PIPELINE_ID="4242"
  _stub_aws
  _stub_curl
  _stub_git
}

teardown() {
  rm -rf "$TEST_DIR"
}

# Stateful aws stub. Initial KVS flag: echo on|off > $TEST_DIR/kvs-state
# (absent file = key never written = reads as off via get-key failure).
# STUB_PUTKEY_STALE=1 makes put-key succeed without updating the state,
# simulating a write that never becomes visible (read-back must catch it).
# STUB_GETKEY_STALE_ONCE=1 makes the first read after a successful update-keys
# return ResourceNotFoundException once, simulating transient KVS visibility lag.
# STUB_NO_MAINTENANCE_OUTPUT=1 makes describe-stacks return no
# FrontendMaintenanceModeStoreArn* output, simulating a live stack deployed
# before the maintenance construct existed (TKT-MM-07, preprod on 1.83.3).
# STUB_GETKEY_DENIED=1 makes every get-key fail with AccessDeniedException,
# simulating the missing cloudfront-keyvaluestore:GetKey grant that caused the
# 2026-07-21 dev incident (describe/update-keys are granted, get-key is not).
_stub_aws() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
echo "\$@" >> "$TEST_DIR/aws-calls"
case "\$*" in
  *assume-role-with-web-identity*) printf 'AKID SECRET TOKEN\n'; exit 0 ;;
  *get-caller-identity*) exit 0 ;;
  *describe-stacks*)
    case "\$*" in
      *MaintenanceModeStoreArn*)
        if [[ "\${STUB_NO_MAINTENANCE_OUTPUT:-}" == "1" ]]; then echo "None"
        else echo "arn:aws:cloudfront::123:key-value-store/kvs-test"; fi ;;
      *ChatHandlerName*) echo "renate-chat-test" ;;
      *CloudFrontDistributionUrl*) echo "https://dtest.cloudfront.net" ;;
      *ApiUrl*) echo "https://api.example.com/prod/" ;;
      *) echo "None" ;;
    esac
    exit 0 ;;
  *describe-key-value-store*) echo "ETAG123"; exit 0 ;;
esac
# maintenance-reason parameter (#579). STUB_REASON seeds the initial value;
# absent means the parameter does not exist yet (pre-#579 environments).
if [[ "\$*" == *"get-parameter"* ]]; then
  if [[ -f "$TEST_DIR/reason-state" ]]; then
    cat "$TEST_DIR/reason-state"
    exit 0
  fi
  if [[ -n "\${STUB_REASON:-}" ]]; then
    echo "\${STUB_REASON}"
    exit 0
  fi
  echo "An error occurred (ParameterNotFound) when calling the GetParameter operation" >&2
  exit 254
fi
if [[ "\$*" == *"put-parameter"* ]]; then
  while [[ \$# -gt 0 ]]; do
    if [[ "\$1" == "--value" ]]; then echo "\$2" > "$TEST_DIR/reason-state"; fi
    shift
  done
  exit 0
fi
if [[ "\$*" == *" get-key"* ]]; then
  if [[ "\${STUB_GETKEY_DENIED:-}" == "1" ]]; then
    echo "An error occurred (AccessDeniedException) when calling the GetKey operation: User is not authorized to perform: cloudfront-keyvaluestore:GetKey" >&2
    exit 254
  fi
  if [[ "\${STUB_GETKEY_STALE_ONCE:-}" == "1" && -f "$TEST_DIR/kvs-state" \
    && ! -f "$TEST_DIR/getkey-stale-once-used" ]]; then
    touch "$TEST_DIR/getkey-stale-once-used"
    echo "ResourceNotFoundException" >&2
    exit 254
  fi
  [[ -f "$TEST_DIR/kvs-state" ]] || { echo "ResourceNotFoundException" >&2; exit 254; }
  cat "$TEST_DIR/kvs-state"
  exit 0
fi
if [[ "\$*" == *" update-keys"* ]]; then
  if [[ "\${STUB_PUTKEY_STALE:-}" != "1" ]]; then
    while [[ \$# -gt 0 ]]; do
      if [[ "\$1" == "--puts" ]]; then echo "\${2#*Value=}" > "$TEST_DIR/kvs-state"; fi
      shift
    done
  fi
  exit 0
fi
if [[ "\$*" == *"put-function-concurrency"* ]]; then
  touch "$TEST_DIR/lambda-throttled"
  exit 0
fi
if [[ "\$*" == *"delete-function-concurrency"* ]]; then
  rm -f "$TEST_DIR/lambda-throttled"
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

# curl stub answering from the aws stub's state files. Overrides:
#   STUB_CF_STATUS / STUB_CF_XCACHE  — force the CloudFront response
#   STUB_CONSENT_STATUS              — force the consent endpoint status
_stub_curl() {
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
echo "\$@" >> "$TEST_DIR/curl-calls"
url=""; body_out=""; hdr_out=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    -o) body_out="\$2"; shift 2 ;;
    -D) hdr_out="\$2"; shift 2 ;;
    -w|-X|-H|-d|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="\$1"; shift ;;
  esac
done
_respond() { # <status> <body> <extra-header>
  [[ -n "\$body_out" ]] && printf '%s\n' "\$2" > "\$body_out"
  [[ -n "\$hdr_out" ]] && printf 'HTTP/2 %s\r\n%s\r\n\r\n' "\$1" "\$3" > "\$hdr_out"
  printf '%s' "\$1"
}
case "\$url" in
  *cloudfront.net*)
    if [[ -n "\${STUB_CF_STATUS:-}\${STUB_CF_BODY:-}" ]]; then
      _respond "\${STUB_CF_STATUS:-200}" "\${STUB_CF_BODY:-error page}" "x-cache: \${STUB_CF_XCACHE:-Miss from cloudfront}"
    elif [[ "\$(cat "$TEST_DIR/kvs-state" 2>/dev/null)" == "on" ]]; then
      _respond 200 '<link rel="stylesheet" href="maintenance.css" />' "x-cache: Miss from cloudfront"
    else
      _respond 200 '<app-root></app-root>' "x-cache: Miss from cloudfront"
    fi
    ;;
  */api/consent*)
    if [[ -n "\${STUB_CONSENT_STATUS:-}" ]]; then
      _respond "\$STUB_CONSENT_STATUS" '{}' ""
    elif [[ -f "$TEST_DIR/lambda-throttled" ]]; then
      _respond 503 '{"message":"Service Unavailable"}' ""
    else
      _respond 200 '{}' ""
    fi
    ;;
  */api/chat*) _respond 401 '{"message":"Unauthorized"}' "" ;;
  */health*)   _respond 200 '{"status":"ok"}' "" ;;
  *)           _respond 599 '' '' ;;
esac
exit 0
EOF
  chmod +x "$TEST_DIR/bin/curl"
}

# git stub for push-maintenance-rehearsed-tag.sh (TKT-MM-04). Default: no
# rehearsal tag exists on origin yet, so a real qa disable pushes one.
# Captures every invocation so tests can assert push happened (or didn't) —
# absence of $TEST_DIR/git-calls means git was never invoked at all.
_stub_git() {
  cat >"$TEST_DIR/bin/git" <<EOF
#!/bin/bash
echo "\$@" >> "$TEST_DIR/git-calls"
if [[ "\$1" == "ls-remote" ]]; then exit 2; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/git"
}

_mutating_calls() {
  grep -E 'update-keys|put-function-concurrency|delete-function-concurrency' \
    "$TEST_DIR/aws-calls" 2>/dev/null || true
}

# ── env / input validation ────────────────────────────────────────────────────

@test "[maintenance-yaml] unknown env → exit 1" {
  run bash "$SCRIPT" staging
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown env"* ]]
}

@test "[maintenance-yaml] role var unset → exit 1 with var name" {
  unset CDK_DEPLOY_ROLE_ARN_QA
  run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"CDK_DEPLOY_ROLE_ARN_QA"* ]]
}

@test "[maintenance-yaml] dev with MAINTENANCE_STATE set → exit 1 (GitOps only)" {
  MAINTENANCE_STATE="on" run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"MAINTENANCE_STATE"* ]]
}

@test "[maintenance-yaml] missing maintenance.yaml for dev → exit 1" {
  rm "$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"version.yaml"* ]]
}

@test "[maintenance-yaml] dev maintenance: true → enable ops issued" {
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q 'update-keys' "$TEST_DIR/aws-calls"
  grep -q 'put-function-concurrency' "$TEST_DIR/aws-calls"
}

@test "[maintenance-yaml] qa with MAINTENANCE_STATE set → exit 1 (GitOps only)" {
  MAINTENANCE_STATE="on" run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"MAINTENANCE_STATE"* ]]
}

@test "[maintenance-yaml] unknown flag (--dryrun typo) → exit 1, zero mutations" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa --dryrun
  [ "$status" -eq 1 ]
  [[ "$output" == *"--dry-run"* ]]
  [ -z "$(_mutating_calls)" ]
}

# ── maintenance: key parsing ─────────────────────────────────────────────────

@test "[maintenance-yaml] maintenance: true → enable ops issued" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  grep -q 'update-keys' "$TEST_DIR/aws-calls"
  grep -q 'put-function-concurrency' "$TEST_DIR/aws-calls"
}

@test "[maintenance-yaml] key absent → desired off, no-op when already off" {
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] maintenance: false among other keys, with comment → desired off" {
  printf 'env: qa\nmaintenance: false  # planned window done\nversion: 1.90.0\n' \
    >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] unrecognized maintenance value → exit 1" {
  printf 'version: 1.90.0\nmaintenance: yes\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"maintenance"* ]]
}

@test "[maintenance-yaml] missing version.yaml for qa → exit 1" {
  rm "$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"version.yaml"* ]]
}

# ── --dry-run ────────────────────────────────────────────────────────────────

@test "[maintenance-yaml] --dry-run with pending enable → plan printed, zero mutations" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"dry-run"* ]]
  [[ "$output" == *"update-keys"* ]]
  [[ "$output" == *"put-function-concurrency"* ]]
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] --dry-run when converged → reports no-op, zero mutations" {
  echo "on" >"$TEST_DIR/kvs-state"
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"already"* ]]
  [ -z "$(_mutating_calls)" ]
}

# ── idempotency / convergence ────────────────────────────────────────────────

@test "[maintenance-yaml] enable twice: second run is a verified no-op" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  rm "$TEST_DIR/aws-calls"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"already"* ]]
  [ -z "$(_mutating_calls)" ]
  # The no-op still verifies the live state.
  grep -q 'cloudfront.net' "$TEST_DIR/curl-calls"
}

@test "[maintenance-yaml] disable twice: second run is a no-op (stale-flag safe)" {
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  rm -f "$TEST_DIR/aws-calls"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ -z "$(_mutating_calls)" ]
}

# ── ordering + read-back ─────────────────────────────────────────────────────

@test "[maintenance-yaml] enable is edge-first: KVS write before put-function-concurrency" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  putkey_line="$(grep -n 'update-keys' "$TEST_DIR/aws-calls" | head -1 | cut -d: -f1)"
  conc_line="$(grep -n 'put-function-concurrency' "$TEST_DIR/aws-calls" | head -1 | cut -d: -f1)"
  [ "$putkey_line" -lt "$conc_line" ]
}

@test "[maintenance-yaml] disable is edge-first: KVS write before delete-function-concurrency" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  putkey_line="$(grep -n 'update-keys' "$TEST_DIR/aws-calls" | head -1 | cut -d: -f1)"
  del_line="$(grep -n 'delete-function-concurrency' "$TEST_DIR/aws-calls" | head -1 | cut -d: -f1)"
  [ "$putkey_line" -lt "$del_line" ]
}

@test "[maintenance-yaml] KVS read-back mismatch after put-key → exit 1" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  STUB_PUTKEY_STALE=1 run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"read-back"* ]]
  # The backend must not be throttled when the edge flip never stuck.
  ! grep -q 'put-function-concurrency' "$TEST_DIR/aws-calls"
}

@test "[maintenance-yaml] transient KVS read-back lag after put-key → retried and succeeds" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  STUB_GETKEY_STALE_ONCE=1 run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"KVS read-back pending"* ]]
  grep -q 'put-function-concurrency' "$TEST_DIR/aws-calls"
}

# ── smoke checks ─────────────────────────────────────────────────────────────

@test "[maintenance-yaml] enable smoke: maintenance page + consent 503 + chat 401 → OK" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [[ "$output" == *"Maintenance smoke [qa]: OK"* ]]
  grep -q '/api/consent' "$TEST_DIR/curl-calls"
  grep -q '/api/chat' "$TEST_DIR/curl-calls"
}

@test "[maintenance-yaml] enable smoke fails when backend still answers (consent not 503)" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  STUB_CONSENT_STATUS=200 run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"consent"* ]]
}

@test "[maintenance-yaml] disable smoke fails when maintenance page still served (edge lag)" {
  # Desired off and KVS already off, but the edge keeps serving the
  # maintenance page — the converged no-op's verification must catch it.
  STUB_CF_BODY='<link rel="stylesheet" href="maintenance.css" />' run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"maintenance page"* ]]
}

@test "[maintenance-yaml] CloudFront 503 with x-cache error → explicit function-failure message" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  STUB_CF_STATUS=503 STUB_CF_XCACHE="Error from cloudfront" run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [[ "$output" == *"CloudFront function execution failed"* ]]
}

# ── maintenance rehearsal tag (TKT-MM-04) ───────────────────────────────────

@test "[maintenance-yaml] real disable on qa pushes a maintenance-rehearsed tag" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  grep -qE '^tag maintenance-rehearsed-qa-1\.90\.0-4242$' "$TEST_DIR/git-calls"
  grep -q 'push .* refs/tags/maintenance-rehearsed-qa-1.90.0-4242' "$TEST_DIR/git-calls"
}

@test "[maintenance-yaml] real enable on qa does not push a rehearsal tag" {
  printf 'version: 1.90.0\nmaintenance: true\n' >"$TEST_DIR/deployments/qa/version.yaml"
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  ! grep -q 'maintenance-rehearsed' "$TEST_DIR/git-calls" || return 1
}

@test "[maintenance-yaml] no-op disable on qa (already off) does not push a rehearsal tag" {
  run bash "$SCRIPT" qa
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/git-calls" ]
}

@test "[maintenance-yaml] real disable on preprod does not push a rehearsal tag (qa-only rehearsal)" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  run bash "$SCRIPT" preprod
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/git-calls" ]
}

@test "[maintenance-yaml] failed disable smoke on qa does not push a rehearsal tag" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  STUB_CF_BODY='<link rel="stylesheet" href="maintenance.css" />' run bash "$SCRIPT" qa
  [ "$status" -eq 1 ]
  [ ! -f "$TEST_DIR/git-calls" ]
}

@test "[maintenance-yaml] --dry-run disable on qa does not push a rehearsal tag" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  run bash "$SCRIPT" qa --dry-run
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/git-calls" ]
}

# ── construct not deployed to the env (TKT-MM-07) ────────────────────────────
#
# preprod sat on a version pin (1.83.3) that predates the maintenance KVS, so
# the live stack had no FrontendMaintenanceModeStoreArn* output and the switch
# aborted with a bare CloudFormation message that gave the operator no hint
# about what to do. The abort itself is correct; the diagnosis must be too.

@test "[maintenance-yaml] maintenance construct not deployed → actionable abort" {
  printf 'version: 1.83.3\n' >"$TEST_DIR/deployments/preprod/version.yaml"
  STUB_NO_MAINTENANCE_OUTPUT=1 run bash "$SCRIPT" preprod
  [ "$status" -eq 1 ]
  # The underlying CFN fact is still reported …
  [[ "$output" == *"FrontendMaintenanceModeStoreArn"* ]]
  # … plus what it means and what to do about it.
  [[ "$output" == *"maintenance construct is not deployed to preprod"* ]]
  [[ "$output" == *"cdk-deploy:preprod"* ]]
  # Nothing was touched on a stack that cannot support the toggle.
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] construct-missing abort names the env it was run for" {
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  STUB_NO_MAINTENANCE_OUTPUT=1 run bash "$SCRIPT" dev
  [ "$status" -eq 1 ]
  [[ "$output" == *"not deployed to dev"* ]]
  [[ "$output" == *"cdk-deploy:dev"* ]]
}

# ── unreadable KVS flag (2026-07-21 dev incident) ────────────────────────────
#
# The dev CI role was granted DescribeKeyValueStore + UpdateKeys but not
# GetKey. Both reads failed, both errors were discarded, and the script
# reported the flag as "off" — so the disable path short-circuited to a no-op
# while the edge kept serving the maintenance page. An unreadable flag must
# abort loudly; it must never be reported as off.

@test "[maintenance-yaml] denied get-key on disable → abort, never a silent no-op" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  STUB_GETKEY_DENIED=1 run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
  # The real AWS error surfaces instead of being swallowed by 2>/dev/null.
  [[ "$output" == *"AccessDeniedException"* ]]
  [[ "$output" == *"get-key failed"* ]]
  # The old bug: claiming the flag was already off and doing nothing.
  [[ "$output" != *"already 'off'"* ]]
  # Nothing was mutated on the back of an unreadable flag.
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] denied get-key on enable → abort before the KVS write" {
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  STUB_GETKEY_DENIED=1 run bash "$SCRIPT" dev
  [ "$status" -ne 0 ]
  [[ "$output" == *"AccessDeniedException"* ]]
  # Previously the unreadable flag read as "off", so the script wrote the key
  # and only then failed on the read-back, leaving the edge changed.
  [ -z "$(_mutating_calls)" ]
}

@test "[maintenance-yaml] absent key still reads as off (not an error)" {
  rm -f "$TEST_DIR/kvs-state"
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  grep -q 'update-keys' "$TEST_DIR/aws-calls"
}

# ── maintenance-reason coexistence (#579) ─────────────────────────────────────
#
# Budget pacing can enable maintenance outside GitOps. These cases pin the
# contract that keeps this convergence controller from silently undoing it.

_reason_state() { cat "$TEST_DIR/reason-state" 2>/dev/null || true; }

@test "[maintenance-yaml] budget-triggered maintenance survives a converge to off" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  echo "budget" >"$TEST_DIR/reason-state"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  # Exit 0, not 1: the deploy pipeline must still succeed.
  [ "$status" -eq 0 ]
  [[ "$output" == *"Budget pacing active"* ]]
  [[ "$output" == *"budget-override"* ]]
  # Nothing was flipped — the service stays offline until pacing clears it.
  [ -z "$(_mutating_calls)" ]
  [ "$(_reason_state)" = "budget" ]
}

@test "[maintenance-yaml] manual enable records reason=manual" {
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ "$(_reason_state)" = "manual" ]
}

@test "[maintenance-yaml] manual disable clears reason to none" {
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  echo "manual" >"$TEST_DIR/reason-state"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ "$(_reason_state)" = "none" ]
  grep -q 'delete-function-concurrency' "$TEST_DIR/aws-calls"
}

@test "[maintenance-yaml] a manual enable escalates over a budget reason" {
  # Operator intent outranks the automation: pacing must not later clear a
  # window a human opened, so the reason becomes manual.
  echo "budget" >"$TEST_DIR/reason-state"
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [ "$(_reason_state)" = "manual" ]
}

@test "[maintenance-yaml] missing reason parameter is treated as none" {
  # Environments deployed before #579 have no parameter — the switch must keep
  # working rather than aborting.
  rm -f "$TEST_DIR/reason-state"
  echo "on" >"$TEST_DIR/kvs-state"
  touch "$TEST_DIR/lambda-throttled"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [ "$status" -eq 0 ]
  [[ "$output" == *"treating reason as 'none'"* ]]
  grep -q 'delete-function-concurrency' "$TEST_DIR/aws-calls"
}

@test "[maintenance-yaml] budget reason with flag already off falls through" {
  # Inconsistent state (reason says budget, flag says off) must not exit
  # silently — the normal convergence path reports it.
  rm -f "$TEST_DIR/kvs-state"
  echo "budget" >"$TEST_DIR/reason-state"
  echo "maintenance: false" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev
  [[ "$output" != *"Budget pacing active"* ]]
}

@test "[maintenance-yaml] --dry-run reports the pending reason change" {
  echo "maintenance: true" >"$TEST_DIR/deployments/dev/maintenance.yaml"
  run bash "$SCRIPT" dev --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"maintenance-reason=manual"* ]]
  [ -z "$(_mutating_calls)" ]
}
