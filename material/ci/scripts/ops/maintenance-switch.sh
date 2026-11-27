#!/usr/bin/env bash
set -euo pipefail
# maintenance-switch.sh <env> [--dry-run]
#
# Toggles maintenance mode (TKT-MM-02, see docs/architecture/rfc/rfc-maintenance-mode.md):
#   frontend — CloudFront KVS flag `maintenance` read by the viewer-request
#              function (frontend.ts), serves /_maintenance/index.html when on
#   backend  — ChatHandler reserved concurrency 0 (API Gateway remaps the
#              resulting throttle to 503, api-gateway.ts)
#
# Desired state (dev/qa/preprod all identical):
#   `maintenance:` key in deployments/<env>/version.yaml (true → on; false or
#   absent → off). MAINTENANCE_STATE must NOT be set — the file is the only
#   source of truth (GitOps). dev's file carries only the maintenance key (no
#   version pin — dev has no promotion concept, it deploys master HEAD).
#
# The script converges: it compares the desired state against the live KVS
# flag and no-ops (exit 0) when they already match, so unrelated version
# bumps do nothing and running enable/disable twice never errors. Even the
# no-op verifies the live state with the smoke check.
#
# Toggle order is edge-first in BOTH directions (RFC review correction):
# KVS flag first, Lambda concurrency second — so users always see the
# maintenance page before (and while) the API starts refusing.
#
# Recovery note (incident 2026-07-15): if the CloudFront function itself
# breaks while maintenance is on, this switch cannot help — the KVS flag is
# only read by that function. The only way back is a CDK redeploy with a
# fixed function bundle.
#
# Required IAM on the assumed role (all three, scoped to the KVS ARN):
#   cloudfront-keyvaluestore:DescribeKeyValueStore  (ETag for the write)
#   cloudfront-keyvaluestore:UpdateKeys             (the write)
#   cloudfront-keyvaluestore:GetKey                 (convergence read + read-back)
# GetKey is easy to miss — TKT-MM-01 specced UpdateKeys only, and its absence
# on dev left the switch unable to turn maintenance off (incident 2026-07-21).
# Plus lambda:{Put,Delete}FunctionConcurrency on the ChatHandler ARN.
#
# Required: GITLAB_OIDC_TOKEN, CI_JOB_ID, CDK_DEPLOY_ROLE_ARN_<ENV>
# Optional: SMOKE_MAX_ATTEMPTS / SMOKE_BASE_DELAY_S / SMOKE_MAX_DELAY_S
#           (retry tuning, same semantics as smoke-eval-env.sh),
#           KVS_READBACK_MAX_ATTEMPTS / KVS_READBACK_BASE_DELAY_S /
#           KVS_READBACK_MAX_DELAY_S (post-write KVS read-back retry tuning),
#           REPO_ROOT (test override for the version.yaml location)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

ENV="${1:-}"
DRY_RUN="false"
if [[ -n "${2:-}" ]]; then
  if [[ "$2" == "--dry-run" ]]; then
    DRY_RUN="true"
  else
    echo "maintenance-switch: unknown argument '$2' (only --dry-run is supported)" >&2
    exit 1
  fi
fi

case "$ENV" in
  dev|qa|preprod|prod) ;;
  *)
    echo "maintenance-switch: unknown env '${ENV}' (allowed: dev qa preprod prod)" >&2
    exit 1
    ;;
esac

ENV_UPPER="${ENV^^}"
ROLE_VAR="CDK_DEPLOY_ROLE_ARN_${ENV_UPPER}"
ROLE_ARN="${!ROLE_VAR:?${ROLE_VAR} is required but not set}"
STACK="renate-chatbot-${ENV}"

SMOKE_MAX_ATTEMPTS="${SMOKE_MAX_ATTEMPTS:-5}"
SMOKE_BASE_DELAY_S="${SMOKE_BASE_DELAY_S:-4}"
SMOKE_MAX_DELAY_S="${SMOKE_MAX_DELAY_S:-60}"
KVS_READBACK_MAX_ATTEMPTS="${KVS_READBACK_MAX_ATTEMPTS:-5}"
KVS_READBACK_BASE_DELAY_S="${KVS_READBACK_BASE_DELAY_S:-1}"
KVS_READBACK_MAX_DELAY_S="${KVS_READBACK_MAX_DELAY_S:-8}"

# ── Desired state ─────────────────────────────────────────────────────────────

if [[ -n "${MAINTENANCE_STATE:-}" ]]; then
  echo "maintenance-switch: MAINTENANCE_STATE must not be set for ${ENV} — the" >&2
  echo "maintenance: key is the only source of truth" >&2
  exit 1
fi
# For envs using split-file design (dev), maintenance.yaml holds the key.
# For envs using single-file design (qa/preprod), version.yaml holds it.
MAINTENANCE_FILE="${REPO_ROOT}/deployments/${ENV}/maintenance.yaml"
if [[ ! -f "$MAINTENANCE_FILE" ]]; then
  MAINTENANCE_FILE="${REPO_ROOT}/deployments/${ENV}/version.yaml"
fi
VERSION_FILE="$MAINTENANCE_FILE"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "maintenance-switch: ${VERSION_FILE#"${REPO_ROOT}/"} not found (expected deployments/${ENV}/version.yaml)" >&2
  exit 1
fi
# Same extraction idiom as render-deployment-page.sh (TKT-MM-03):
# first `maintenance:` line, trailing comment and whitespace stripped.
FLAG="$(sed -n 's/^maintenance:[[:space:]]*//p' "$VERSION_FILE" \
  | head -n1 | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"
case "$FLAG" in
  true) DESIRED="on" ;;
  false|'') DESIRED="off" ;;
  *)
    echo "maintenance-switch: unrecognized maintenance value '${FLAG}' in ${ENV} version.yaml (allowed: true false)" >&2
    exit 1
    ;;
esac

# ── Resolve live state ────────────────────────────────────────────────────────

assume_deploy_role "$ROLE_ARN"

_stack_output() { # <output-key-prefix-query>
  aws cloudformation describe-stacks \
    --stack-name "$STACK" \
    --query "$1" \
    --output text
}

_require_output() { # <value> <name> [hint...]
  [[ -n "$1" && "$1" != "None" ]] && return 0
  echo "CloudFormation output $2 not found in stack $STACK" >&2
  shift 2
  if [[ $# -gt 0 ]]; then printf '%s\n' "$@" >&2; fi
  exit 1
}

KVS_ARN="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendMaintenanceModeStoreArn')].OutputValue | [0]")"
CHAT_FN="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'LambdaBackendChatHandlerName')].OutputValue | [0]")"
CF_URL="$(_stack_output "Stacks[0].Outputs[?starts_with(OutputKey, 'FrontendCloudFrontDistributionUrl')].OutputValue | [0]")"
API_URL="$(_stack_output "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue | [0]")"
# The KVS output is the one an operator hits on a stack that predates the
# maintenance construct (TKT-MM-07: preprod was pinned to 1.83.3, deployed
# ~6 days before the construct existed). The construct is unconditional in
# source (frontend.ts), so a missing output means "this env has not been
# deployed since the construct landed" — never a source/config problem. Say
# that, instead of leaving the operator with a raw CloudFormation message.
_require_output "$KVS_ARN" "FrontendMaintenanceModeStoreArn*" \
  "The maintenance construct is not deployed to ${ENV} yet — the live ${STACK}" \
  "stack was last deployed from a version that predates it." \
  "Deploy it first (promote deployments/${ENV}/version.yaml, then run" \
  "cdk-deploy:${ENV}); this toggle cannot create the KeyValueStore itself."
_require_output "$CHAT_FN" "LambdaBackendChatHandlerName*"
_require_output "$CF_URL" "FrontendCloudFrontDistributionUrl*"
_require_output "$API_URL" "ApiUrl"

# Scratch files for the KVS read and the smoke HTTP calls. Deliberately one
# trap: a second `trap ... EXIT` would silently replace this one.
HTTP_BODY=""
HTTP_HEADERS=""
KVS_ERR=""
_cleanup() { rm -f "$HTTP_BODY" "$HTTP_HEADERS" "$KVS_ERR"; }
HTTP_BODY="$(mktemp)"
HTTP_HEADERS="$(mktemp)"
KVS_ERR="$(mktemp)"
trap _cleanup EXIT

# A key that was never written counts as off — the KVS is seeded with off at
# creation (frontend.ts) and the function defaults to off when the key is
# missing. Any OTHER failure (AccessDenied, throttling) must abort instead:
# reporting an unreadable flag as "off" makes the disable path a silent no-op,
# and that is the path incident recovery depends on. This masked a missing
# cloudfront-keyvaluestore:GetKey grant until 2026-07-21 — the dev switch
# reported "already off" while the edge served the maintenance page.
_kvs_get() { # → echoes the live value; empty when the key does not exist
  local out status=0
  out="$(aws cloudfront-keyvaluestore get-key \
    --kvs-arn "$KVS_ARN" --key maintenance \
    --query Value --output text 2>"$KVS_ERR")" || status=$?
  if [[ $status -ne 0 ]]; then
    if grep -qi 'ResourceNotFoundException' "$KVS_ERR"; then
      return 0
    fi
    echo "maintenance-switch: cloudfront-keyvaluestore get-key failed (exit ${status}) on ${KVS_ARN} — refusing to assume the flag is off:" >&2
    sed 's/^/  /' "$KVS_ERR" >&2
    return 1
  fi
  [[ "$out" == "None" ]] && out=""
  printf '%s' "$out"
}

CURRENT="$(_kvs_get)"
if [[ -z "$CURRENT" ]]; then
  CURRENT="off"
fi

# ── Maintenance reason (#579) ─────────────────────────────────────────────────
#
# Budget pacing (#579) can enable maintenance on its own, outside this script
# and outside GitOps. Without the reason parameter this convergence controller
# would happily turn that protection off on the next unrelated deploy: the file
# still says `maintenance: false`, the live flag says on, so it "fixes" the
# drift and puts a service that is burning through its budget back online.
#
# A missing parameter is treated as `none` (not an abort): envs deployed before
# the parameter landed must keep working, and `none` is the conservative value
# — it only ever allows this script to do what it already did.
REASON_PARAM="/${ENV}/renate/maintenance-reason"
_reason_get() {
  local out status=0
  out="$(aws ssm get-parameter --name "$REASON_PARAM" \
    --query 'Parameter.Value' --output text 2>"$KVS_ERR")" || status=$?
  if [[ $status -ne 0 ]]; then
    if grep -qi 'ParameterNotFound' "$KVS_ERR"; then
      echo "maintenance-switch: ${REASON_PARAM} not found — treating reason as 'none'" >&2
      printf 'none'
      return 0
    fi
    echo "maintenance-switch: ssm get-parameter failed (exit ${status}) on ${REASON_PARAM}:" >&2
    sed 's/^/  /' "$KVS_ERR" >&2
    return 1
  fi
  [[ "$out" == "None" || -z "$out" ]] && out="none"
  printf '%s' "$out"
}

_reason_set() { # <none|manual|budget>
  aws ssm put-parameter --name "$REASON_PARAM" \
    --value "$1" --type String --overwrite > /dev/null
  log_kv "Reason:" "$1"
}

REASON="$(_reason_get)"

log_section "Maintenance switch [${ENV}]"
log_kv "Desired:" "$DESIRED"
log_kv "Current:" "$CURRENT"
log_kv "Reason:" "$REASON"

# Budget pacing owns the current maintenance state — this script must not clear
# it. Exit 0, not 1: a deploy pipeline should still succeed (the code update is
# independent of the cost-control state), it just must not flip the switch.
# The operator escape hatch is `make budget-override ENV=<env>`.
#
# Scoped to CURRENT=on: a `budget` reason with the flag already off is an
# inconsistent state (pacing wrote the reason but the flag never took, or an
# out-of-band change), and falling through lets the normal convergence path
# report it instead of exiting silently.
if [[ "$DESIRED" == "off" && "$REASON" == "budget" && "$CURRENT" == "on" ]]; then
  echo "Budget pacing active — maintenance state preserved. Deploy continues."
  echo "To force-clear: make budget-override ENV=${ENV} (or wait for the next budget check)."
  exit 0
fi

# ── Smoke check ───────────────────────────────────────────────────────────────

_http() { # <GET|POST> <url> → echoes status code; body/headers in temp files
  local method="$1" url="$2" status
  local args=(-s -o "$HTTP_BODY" -D "$HTTP_HEADERS" -w '%{http_code}' --max-time 30)
  if [[ "$method" == "POST" ]]; then
    args+=(-X POST -H 'Content-Type: application/json' -d '{}')
  fi
  status="$(curl "${args[@]}" "$url" || true)"
  echo "${status:-000}"
}

# One smoke pass; sets SMOKE_REASON on failure. The CloudFront-function
# check runs first so a broken function is reported as exactly that
# (incident 2026-07-15) instead of a generic page-content failure.
_smoke_check() { # <on|off>
  local state="$1" status

  status="$(_http GET "${CF_URL}/")"
  if [[ "$status" == "503" ]] && grep -qi 'Error from cloudfront' "$HTTP_HEADERS"; then
    SMOKE_REASON="CloudFront function execution failed (503 generated by CloudFront, not the origin)"
    return 1
  fi
  if [[ "$status" != "200" ]]; then
    SMOKE_REASON="GET / returned ${status}, expected 200"
    return 1
  fi
  if [[ "$state" == "on" ]]; then
    if ! grep -q 'maintenance.css' "$HTTP_BODY"; then
      SMOKE_REASON="maintenance page not served on GET / (marker maintenance.css missing)"
      return 1
    fi
  else
    if grep -q 'maintenance.css' "$HTTP_BODY"; then
      SMOKE_REASON="maintenance page still served on GET / (marker maintenance.css present)"
      return 1
    fi
  fi

  # POST /api/chat is Cognito-protected — an unauthenticated probe can never
  # see the throttle 503, only 401. /api/consent routes to the same
  # ChatHandler with no authorizer, so it is the observable 503 probe.
  status="$(_http POST "${API_URL}api/consent")"
  if [[ "$state" == "on" ]]; then
    if [[ "$status" != "503" ]]; then
      SMOKE_REASON="POST /api/consent returned ${status}, expected 503 (backend not throttled)"
      return 1
    fi
    status="$(_http POST "${API_URL}api/chat")"
    if [[ "$status" != "401" ]]; then
      SMOKE_REASON="POST /api/chat returned ${status}, expected 401 (auth layer changed)"
      return 1
    fi
  else
    if [[ "$status" == "503" ]]; then
      SMOKE_REASON="POST /api/consent still returns 503 (backend still throttled)"
      return 1
    fi
    status="$(_http GET "${API_URL}health")"
    if [[ "$status" != "200" ]]; then
      SMOKE_REASON="GET /health returned ${status}, expected 200"
      return 1
    fi
  fi
  return 0
}

# Retry with exponential backoff + jitter (same strategy as smoke-eval-env.sh)
# — the KVS flag takes a few seconds to propagate to the edge.
_smoke() { # <on|off>
  local state="$1" attempt=1 raw_delay jitter delay
  while [[ $attempt -le $SMOKE_MAX_ATTEMPTS ]]; do
    if _smoke_check "$state"; then
      echo "Maintenance smoke [${ENV}]: OK (maintenance=${state})"
      return 0
    fi
    echo "Maintenance smoke [${ENV}]: attempt ${attempt}/${SMOKE_MAX_ATTEMPTS} — ${SMOKE_REASON}"
    if [[ $attempt -lt $SMOKE_MAX_ATTEMPTS ]]; then
      raw_delay=$(( SMOKE_BASE_DELAY_S * (1 << (attempt - 1)) ))
      [[ $raw_delay -gt $SMOKE_MAX_DELAY_S ]] && raw_delay=$SMOKE_MAX_DELAY_S
      jitter=$(( (RANDOM % (raw_delay / 2 + 1)) - raw_delay / 4 ))
      delay=$(( raw_delay + jitter ))
      [[ $delay -lt 1 ]] && delay=1
      sleep "$delay"
    fi
    attempt=$(( attempt + 1 ))
  done
  echo "Maintenance smoke [${ENV}]: FAILED after ${SMOKE_MAX_ATTEMPTS} attempts — ${SMOKE_REASON}" >&2
  return 1
}

# ── Converge ──────────────────────────────────────────────────────────────────

if [[ "$CURRENT" == "$DESIRED" ]]; then
  echo "Maintenance flag already '${DESIRED}' — no-op, verifying live state"
  [[ "$DRY_RUN" == "true" ]] && { echo "dry-run: nothing to do"; exit 0; }
  _smoke "$DESIRED"
  exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "dry-run: would perform (in this order):"
  echo "  1. cloudfront-keyvaluestore update-keys maintenance=${DESIRED} (${KVS_ARN})"
  if [[ "$DESIRED" == "on" ]]; then
    echo "  2. lambda put-function-concurrency 0 (${CHAT_FN})"
    echo "  3. ssm put-parameter ${REASON_PARAM}=manual (was '${REASON}')"
  else
    echo "  2. lambda delete-function-concurrency (${CHAT_FN})"
    echo "  3. ssm put-parameter ${REASON_PARAM}=none (was '${REASON}')"
  fi
  echo "  4. smoke check (maintenance=${DESIRED})"
  exit 0
fi

# Edge first: flip the flag, prove the write stuck, only then touch the
# backend — so a failed KVS write never leaves the API dead while the
# frontend still looks healthy.
# update-keys (not put-key): it is the action TKT-MM-01's IAM policy grants
# (cloudfront-keyvaluestore:UpdateKeys); put-key would need a separate grant.
ETAG="$(aws cloudfront-keyvaluestore describe-key-value-store \
  --kvs-arn "$KVS_ARN" --query ETag --output text)"
aws cloudfront-keyvaluestore update-keys \
  --kvs-arn "$KVS_ARN" --if-match "$ETAG" \
  --puts "Key=maintenance,Value=${DESIRED}" > /dev/null
log_kv "KVS put:" "maintenance=${DESIRED}"

READBACK=""
READBACK_ATTEMPT=1
while [[ $READBACK_ATTEMPT -le $KVS_READBACK_MAX_ATTEMPTS ]]; do
  # A hard read failure aborts here via set -e rather than burning the retry
  # budget — retrying a denied call five times is still denied.
  READBACK="$(_kvs_get)"

  if [[ "$READBACK" == "$DESIRED" ]]; then
    break
  fi

  if [[ $READBACK_ATTEMPT -lt $KVS_READBACK_MAX_ATTEMPTS ]]; then
    raw_delay=$(( KVS_READBACK_BASE_DELAY_S * (1 << (READBACK_ATTEMPT - 1)) ))
    [[ $raw_delay -gt $KVS_READBACK_MAX_DELAY_S ]] && raw_delay=$KVS_READBACK_MAX_DELAY_S
    jitter=$(( (RANDOM % (raw_delay / 2 + 1)) - raw_delay / 4 ))
    delay=$(( raw_delay + jitter ))
    [[ $raw_delay -gt 0 && $delay -lt 1 ]] && delay=1
    echo "KVS read-back pending: attempt ${READBACK_ATTEMPT}/${KVS_READBACK_MAX_ATTEMPTS} read '${READBACK:-<none>}'"
    [[ $delay -gt 0 ]] && sleep "$delay"
  fi

  READBACK_ATTEMPT=$(( READBACK_ATTEMPT + 1 ))
done

if [[ "$READBACK" != "$DESIRED" ]]; then
  echo "KVS read-back mismatch: wrote maintenance=${DESIRED}, read '${READBACK:-<none>}' after ${KVS_READBACK_MAX_ATTEMPTS} attempts — aborting before touching the backend" >&2
  exit 1
fi
log_kv "KVS read-back:" "$READBACK"

if [[ "$DESIRED" == "on" ]]; then
  aws lambda put-function-concurrency \
    --function-name "$CHAT_FN" --reserved-concurrent-executions 0 > /dev/null
  log_kv "Lambda:" "${CHAT_FN} concurrency=0"
  # A manual enable escalates over a budget-triggered one: the operator's
  # intent outranks the automation, and pacing must not later clear a window
  # a human opened.
  _reason_set manual
else
  aws lambda delete-function-concurrency --function-name "$CHAT_FN"
  log_kv "Lambda:" "${CHAT_FN} concurrency restored"
  _reason_set none
fi

_smoke "$DESIRED"

# Record a completed qa rehearsal cycle (TKT-MM-04): this line only runs
# after a real off transition (CURRENT was "on" before this run), never on
# the no-op convergence path above and never on --dry-run — so a plain
# version bump with maintenance already off never produces a rehearsal tag.
# Only qa rehearses; preprod's own disable is incident recovery, not a
# rehearsal, so it is deliberately excluded.
if [[ "$ENV" == "qa" && "$DESIRED" == "off" ]]; then
  "${SCRIPT_DIR}/../release/push-maintenance-rehearsed-tag.sh"
fi
