#!/usr/bin/env bash
set -euo pipefail
# renew-cert.sh <env>
#
# Reimport TLS certificate material from Secrets Manager into ACM.
# Designed for the GitLab CI cert-renew job (#577). The script:
#   1. Assumes the dedicated cert-renew OIDC role.
#   2. Reads the cert material from Secrets Manager (eu-central-1).
#   3. Verifies the candidate is a newer, equivalent rotation of the ACM cert.
#   4. Decrypts the private key in-RAM (no plaintext file on disk).
#   5. Reimports into the existing ACM certificate (us-east-1).
#   6. Validates the imported ACM certificate against the candidate.
#
# No plaintext key file ever touches the runner filesystem — process
# substitution via /dev/fd/* ensures the key lives only in memory.
#
# Required environment:
#   GITLAB_OIDC_TOKEN    — GitLab OIDC token (from id_tokens)
#   CERT_RENEW_ROLE_ARN  — IAM role to assume (ki-lab-digibro-<env>-cert-renew)
#
# Usage:
#   .gitlab/ci/scripts/ops/renew-cert.sh prod
#   .gitlab/ci/scripts/ops/renew-cert.sh preprod
#
# References: RFC 0003, #577, docs/runbooks/preprod_cert_import.md

# ── Args ──────────────────────────────────────────────────────────────────────

ENV="${1:?Usage: renew-cert.sh <env>}"

case "$ENV" in
  prod|preprod) ;;
  *) echo "ERROR: env must be 'prod' or 'preprod', got '$ENV'" >&2; exit 1 ;;
esac

SECRET_ID="renate/${ENV}/tls/rentenchat"

cleanup() {
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  unset CREDS SECRET_JSON CERT CHAIN KEY_ENC PASSPHRASE ACM_ARN
  unset DESCRIBE STATUS NOT_AFTER NOT_AFTER_EPOCH IN_USE_BY DOMAIN ISSUER DOMAINS
  unset CANDIDATE_NOT_AFTER CANDIDATE_NOT_AFTER_EPOCH CANDIDATE_ISSUER CANDIDATE_DOMAINS
  exec 3<&- 2>/dev/null || true
}
trap cleanup EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# Convert the ACM RFC3339 timestamp and OpenSSL's GMT timestamp into epochs.
# GNU date is used in CI; BSD date keeps local validation working on macOS.
timestamp_to_epoch() {
  local timestamp="$1"
  local epoch

  if epoch=$(date -u -d "$timestamp" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi
  if epoch=$(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$timestamp" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi
  # BSD date accepts %z without a colon, while ACM returns RFC3339 offsets
  # such as +00:00. Keep the original timestamp for the GNU-date path above.
  local bsd_timestamp
  bsd_timestamp=$(printf '%s' "$timestamp" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')
  if epoch=$(date -j -u -f '%Y-%m-%dT%H:%M:%S%z' "$bsd_timestamp" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi
  if epoch=$(date -j -u -f '%b %e %T %Y %Z' "$timestamp" +%s 2>/dev/null); then
    printf '%s' "$epoch"
    return 0
  fi

  fail "cannot parse certificate expiry timestamp '${timestamp}'"
}

acm_domains() {
  jq -er '.Certificate.SubjectAlternativeNames[]? | ascii_downcase' | LC_ALL=C sort -u
}

candidate_domains() {
  openssl x509 -noout -ext subjectAltName <<<"$CERT" \
    | tr ',' '\n' \
    | sed -n -E 's/^[[:space:]]*DNS:([^[:space:]]+)[[:space:]]*$/\1/p' \
    | tr '[:upper:]' '[:lower:]' \
    | LC_ALL=C sort -u
}

candidate_issuer_cn() {
  local issuer

  issuer=$(openssl x509 -noout -issuer -nameopt RFC2253 <<<"$CERT" | sed -E 's/^issuer=//')
  case "$issuer" in
    *CN=*) printf '%s\n' "$issuer" | sed -E 's/.*(^|,)CN=([^,]+).*/\2/' ;;
    *) fail "candidate certificate issuer has no common name" ;;
  esac
}

assert_rotation_candidate() {
  local current_describe="$1"
  local current_not_after current_not_after_epoch current_domain current_issuer current_domains

  STATUS=$(jq -er '.Certificate.Status' <<<"$current_describe")
  [ "$STATUS" = "ISSUED" ] || fail "current ACM certificate status is '${STATUS}', expected 'ISSUED'"

  current_not_after=$(jq -er '.Certificate.NotAfter' <<<"$current_describe")
  current_not_after_epoch=$(timestamp_to_epoch "$current_not_after")
  current_domain=$(jq -er '.Certificate.DomainName | ascii_downcase' <<<"$current_describe")
  current_issuer=$(jq -er '.Certificate.Issuer' <<<"$current_describe")
  current_domains=$(acm_domains <<<"$current_describe")
  [ -n "$current_domains" ] || fail "current ACM certificate has no SubjectAlternativeNames"

  CANDIDATE_NOT_AFTER=$(openssl x509 -noout -enddate <<<"$CERT" | sed 's/^notAfter=//')
  CANDIDATE_NOT_AFTER_EPOCH=$(timestamp_to_epoch "$CANDIDATE_NOT_AFTER")
  CANDIDATE_ISSUER=$(candidate_issuer_cn)
  CANDIDATE_DOMAINS=$(candidate_domains)
  [ -n "$CANDIDATE_DOMAINS" ] || fail "candidate certificate has no DNS subject alternative names"

  echo "  Current ACM NotAfter: ${current_not_after}"
  echo "  Candidate NotAfter:   ${CANDIDATE_NOT_AFTER}"
  echo "  Current ACM domains:  $(tr '\n' ',' <<<"$current_domains" | sed 's/,$//')"
  echo "  Candidate domains:    $(tr '\n' ',' <<<"$CANDIDATE_DOMAINS" | sed 's/,$//')"
  echo "  Current ACM issuer:   ${current_issuer}"
  echo "  Candidate issuer:     ${CANDIDATE_ISSUER}"

  if [ "$CANDIDATE_NOT_AFTER_EPOCH" -le "$current_not_after_epoch" ]; then
    fail "candidate certificate is not newer than the current ACM certificate"
  fi
  if [ "$CANDIDATE_DOMAINS" != "$current_domains" ]; then
    fail "candidate certificate DNS subject alternative names do not match the current ACM certificate"
  fi
  if ! grep -Fxq "$current_domain" <<<"$CANDIDATE_DOMAINS"; then
    fail "candidate certificate does not include ACM primary domain '${current_domain}'"
  fi
  if [ "$CANDIDATE_ISSUER" != "$current_issuer" ]; then
    fail "candidate issuer '${CANDIDATE_ISSUER}' does not match current ACM issuer '${current_issuer}'"
  fi
}

assert_import_result() {
  local imported_domains imported_issuer

  STATUS=$(jq -er '.Certificate.Status' <<<"$DESCRIBE")
  NOT_AFTER=$(jq -er '.Certificate.NotAfter' <<<"$DESCRIBE")
  NOT_AFTER_EPOCH=$(timestamp_to_epoch "$NOT_AFTER")
  IN_USE_BY=$(jq -r '.Certificate.InUseBy[]?' <<<"$DESCRIBE")
  DOMAIN=$(jq -er '.Certificate.DomainName' <<<"$DESCRIBE")
  imported_domains=$(acm_domains <<<"$DESCRIBE")
  imported_issuer=$(jq -er '.Certificate.Issuer' <<<"$DESCRIBE")

  echo "  Domain:    ${DOMAIN}"
  echo "  Status:    ${STATUS}"
  echo "  NotAfter:  ${NOT_AFTER}"
  echo "  InUseBy:   ${IN_USE_BY}"
  echo ""

  [ "$STATUS" = "ISSUED" ] || fail "certificate status is '${STATUS}', expected 'ISSUED'"
  [ "$NOT_AFTER_EPOCH" -eq "$CANDIDATE_NOT_AFTER_EPOCH" ] \
    || fail "imported ACM certificate NotAfter does not match the candidate"
  [ "$imported_domains" = "$CANDIDATE_DOMAINS" ] \
    || fail "imported ACM certificate DNS subject alternative names do not match the candidate"
  [ "$imported_issuer" = "$CANDIDATE_ISSUER" ] \
    || fail "imported ACM certificate issuer does not match the candidate"

  if [ -z "$IN_USE_BY" ]; then
    echo "WARNING: Certificate is not attached to any resource" >&2
  fi
}

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  cert-renew: ${ENV}                                            ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Assume the cert-renew role via OIDC ───────────────────────────────

echo "→ Assuming role: ${CERT_RENEW_ROLE_ARN}"

CREDS=$(aws sts assume-role-with-web-identity \
  --role-arn "${CERT_RENEW_ROLE_ARN}" \
  --role-session-name "cert-renew-${CI_JOB_ID:-local}" \
  --web-identity-token "${GITLAB_OIDC_TOKEN}" \
  --duration-seconds 900 \
  --output json)

AWS_ACCESS_KEY_ID=$(echo "$CREDS" | jq -r '.Credentials.AccessKeyId')
AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | jq -r '.Credentials.SecretAccessKey')
AWS_SESSION_TOKEN=$(echo "$CREDS" | jq -r '.Credentials.SessionToken')
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

echo "  ✓ Role assumed (session expires in 15 min)"
echo ""

# ── Step 2: Read cert material from Secrets Manager ───────────────────────────

echo "→ Reading secret: ${SECRET_ID}"

SECRET_JSON=$(aws secretsmanager get-secret-value \
  --region eu-central-1 \
  --secret-id "${SECRET_ID}" \
  --query 'SecretString' \
  --output text)

read_secret_field() {
  local field="$1"
  local value

  if ! value=$(jq -er --arg field "$field" \
    '.[$field] | select(type == "string" and length > 0)' \
    <<<"$SECRET_JSON"); then
    echo "ERROR: secret '${SECRET_ID}' is missing a non-empty '${field}' field" >&2
    return 1
  fi

  printf '%s' "$value"
}

CERT=$(read_secret_field certificate)
CHAIN=$(read_secret_field chain)
KEY_ENC=$(read_secret_field private_key_encrypted)
PASSPHRASE=$(read_secret_field passphrase)
ACM_ARN=$(read_secret_field acm_arn)

echo "  ✓ Secret read (ACM ARN: ${ACM_ARN})"
echo ""

# ── Step 3: Verify the secret holds a newer equivalent certificate ────────────

echo "→ Pre-flight: comparing candidate with current ACM certificate"

DESCRIBE=$(aws acm describe-certificate \
  --region us-east-1 \
  --certificate-arn "${ACM_ARN}" \
  --output json)

assert_rotation_candidate "$DESCRIBE"

echo "  ✓ Candidate is a newer equivalent rotation"
echo ""

# ── Step 4: Prepare private-key decryption ────────────────────────────────────

echo "→ Preparing private-key decryption (in-RAM, no file on disk)"

# The passphrase is supplied on FD 3, avoiding both argv exposure and files.
# printf does not append a newline, preserving the exact secret value.
exec 3< <(printf '%s' "$PASSPHRASE")

echo "  ✓ Private-key stream prepared"
echo ""

# ── Step 5: Reimport into ACM ─────────────────────────────────────────────────

echo "→ Reimporting certificate into ACM (us-east-1)"
echo "  Target ARN: ${ACM_ARN}"

aws acm import-certificate \
  --region us-east-1 \
  --certificate-arn "${ACM_ARN}" \
  --certificate fileb://<(printf '%s' "$CERT") \
  --private-key fileb://<(printf '%s' "$KEY_ENC" | openssl pkey -passin fd:3) \
  --certificate-chain fileb://<(printf '%s' "$CHAIN") \
  --output json > /dev/null

# Close the passphrase descriptor immediately after ACM has consumed the key.
exec 3<&-

echo "  ✓ Certificate reimported"
echo ""

# ── Step 6: Post-reimport validation ─────────────────────────────────────────

echo "→ Validating reimported certificate"

DESCRIBE=$(aws acm describe-certificate \
  --region us-east-1 \
  --certificate-arn "${ACM_ARN}" \
  --output json)

assert_import_result

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  ✓ cert-renew: ${ENV} — SUCCESS                               ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
