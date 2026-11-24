#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/ops/renew-cert.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  export TEST_DIR
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CERT_RENEW_ROLE_ARN="arn:aws:iam::123456789012:role/test-cert-renew"
  export CI_JOB_ID="99"

  _make_ca "trusted" "Test Issuer"
  _make_ca "untrusted" "Unexpected Issuer"
  _make_leaf "current" "rentenchat.example.test" "trusted" 60
  _make_leaf "valid" "rentenchat.example.test" "trusted" 180
  _make_leaf "stale" "rentenchat.example.test" "trusted" 30
  _make_leaf "wrong-domain" "other.example.test" "trusted" 180
  _make_leaf "wrong-issuer" "rentenchat.example.test" "untrusted" 180

  CURRENT_NOT_AFTER=$(_certificate_not_after "$TEST_DIR/current.pem")
  _write_describe "$TEST_DIR/current.json" "$CURRENT_NOT_AFTER" "Test Issuer" "rentenchat.example.test"
  _write_describe "$TEST_DIR/post.json" "$(_certificate_not_after "$TEST_DIR/valid.pem")" \
    "Test Issuer" "rentenchat.example.test"
  _write_secret "$TEST_DIR/valid"
  _stub_aws
}

teardown() {
  rm -rf "$TEST_DIR"
}

_make_ca() {
  local name="$1" issuer="$2"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TEST_DIR/${name}-ca.key" \
    -out "$TEST_DIR/${name}-ca.pem" \
    -subj "/CN=${issuer}" \
    -days 365 >/dev/null 2>&1
}

_make_leaf() {
  local name="$1" domain="$2" ca="$3" days="$4"
  openssl genpkey -algorithm RSA -aes-256-cbc -pass pass:test-passphrase \
    -out "$TEST_DIR/${name}.key" >/dev/null 2>&1
  openssl req -new -key "$TEST_DIR/${name}.key" -passin pass:test-passphrase \
    -subj "/CN=${domain}" -out "$TEST_DIR/${name}.csr" >/dev/null 2>&1
  printf 'subjectAltName=DNS:%s\n' "$domain" >"$TEST_DIR/${name}.ext"
  openssl x509 -req -in "$TEST_DIR/${name}.csr" \
    -CA "$TEST_DIR/${ca}-ca.pem" -CAkey "$TEST_DIR/${ca}-ca.key" -CAcreateserial \
    -out "$TEST_DIR/${name}.pem" -days "$days" -extfile "$TEST_DIR/${name}.ext" \
    >/dev/null 2>&1
}

_certificate_not_after() {
  local cert="$1" value
  value=$(openssl x509 -noout -enddate -in "$cert" | sed 's/^notAfter=//')
  if date -u -d "$value" '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null; then
    return
  fi
  date -j -u -f '%b %e %T %Y %Z' "$value" '+%Y-%m-%dT%H:%M:%S%z' | sed -E 's/([+-][0-9]{2})([0-9]{2})$/\1:\2/'
}

_write_describe() {
  local output="$1" not_after="$2" issuer="$3" domain="$4"
  jq -n --arg not_after "$not_after" --arg issuer "$issuer" --arg domain "$domain" \
    '{Certificate: {
      Status: "ISSUED",
      NotAfter: $not_after,
      DomainName: $domain,
      SubjectAlternativeNames: [$domain],
      Issuer: $issuer,
      InUseBy: ["arn:aws:cloudfront::123456789012:distribution/test"]
    }}' >"$output"
}

_write_secret() {
  local name="$1"
  jq -n \
    --rawfile certificate "${name}.pem" \
    --rawfile chain "$TEST_DIR/trusted-ca.pem" \
    --rawfile private_key_encrypted "${name}.key" \
    --arg passphrase "test-passphrase" \
    --arg acm_arn "arn:aws:acm:us-east-1:123456789012:certificate/test" \
    '{
      certificate: $certificate,
      chain: $chain,
      private_key_encrypted: $private_key_encrypted,
      passphrase: $passphrase,
      acm_arn: $acm_arn
    }' >"$TEST_DIR/secret.json"
}

_stub_aws() {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$TEST_DIR/aws-calls"
case "$*" in
  *assume-role-with-web-identity*)
    printf '%s\n' '{"Credentials":{"AccessKeyId":"AKID","SecretAccessKey":"SECRET","SessionToken":"TOKEN"}}'
    ;;
  *secretsmanager*get-secret-value*)
    cat "$TEST_DIR/secret.json"
    ;;
  *acm*describe-certificate*)
    if [[ -f "$TEST_DIR/imported" ]]; then cat "$TEST_DIR/post.json"
    else cat "$TEST_DIR/current.json"; fi
    ;;
  *acm*import-certificate*)
    touch "$TEST_DIR/imported"
    ;;
  *)
    echo "Unexpected aws invocation: $*" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

@test "[renew-cert] stale candidate aborts before ACM import" {
  _write_secret "$TEST_DIR/stale"

  run bash "$SCRIPT" prod

  [ "$status" -eq 1 ]
  [[ "$output" == *"candidate certificate is not newer"* ]]
  ! grep -q 'acm import-certificate' "$TEST_DIR/aws-calls"
}

@test "[renew-cert] candidate with different DNS SAN aborts before ACM import" {
  _write_secret "$TEST_DIR/wrong-domain"

  run bash "$SCRIPT" prod

  [ "$status" -eq 1 ]
  [[ "$output" == *"DNS subject alternative names do not match"* ]]
  ! grep -q 'acm import-certificate' "$TEST_DIR/aws-calls"
}

@test "[renew-cert] candidate with different issuer aborts before ACM import" {
  _write_secret "$TEST_DIR/wrong-issuer"

  run bash "$SCRIPT" prod

  [ "$status" -eq 1 ]
  [[ "$output" == *"does not match current ACM issuer"* ]]
  ! grep -q 'acm import-certificate' "$TEST_DIR/aws-calls"
}

@test "[renew-cert] newer candidate with matching DNS SAN and issuer is imported and verified" {
  run bash "$SCRIPT" prod

  [ "$status" -eq 0 ]
  [[ "$output" == *"Candidate is a newer equivalent rotation"* ]]
  [[ "$output" == *"cert-renew: prod — SUCCESS"* ]]
  grep -q 'acm import-certificate' "$TEST_DIR/aws-calls"
}
