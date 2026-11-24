#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/build/build-review-image.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin" "$TEST_DIR/containers"

  export PATH="$TEST_DIR/bin:$PATH"

  export ECR_REGISTRY="123456789012.dkr.ecr.eu-central-1.amazonaws.com"
  export ECR_REPO="renate-chat-lambda"
  export CI_COMMIT_REF_SLUG="feature-my-branch"
  export CI_COMMIT_SHORT_SHA="abc1234"
  export ROLE_ARN="arn:aws:iam::123456789012:role/test-push-role"
  export GITLAB_OIDC_TOKEN="test-oidc-token"
  export CI_JOB_ID="42"
  export DOCKERFILE="backend/src/backend_orchestrator/Dockerfile"
  export REGISTRY_AUTH_FILE="$TEST_DIR/containers/auth.json"
  export AWS_DEFAULT_REGION="eu-central-1"

  # Default aws stub: valid STS creds, no existing image (describe-images exits 1), ECR password
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role-with-web-identity"* ]]; then
  printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'
  exit 0
fi
if [[ "\$*" == *"get-caller-identity"* ]]; then
  exit 0
fi
if [[ "\$*" == *"describe-images"* ]]; then
  exit 1  # tag does not exist → proceed with build
fi
if [[ "\$*" == *"get-login-password"* ]]; then
  printf 'ecr-password\n'
  exit 0
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"

  # Default buildah stub — records calls, succeeds
  cat >"$TEST_DIR/bin/buildah" <<EOF
#!/bin/bash
echo "buildah \$*" >> "$TEST_DIR/buildah.log"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/buildah"

  # base64 stub (GNU -w0 flag may not exist everywhere)
  if ! base64 -w0 /dev/null 2>/dev/null; then
    cat >"$TEST_DIR/bin/base64" <<'EOF'
#!/bin/bash
args=()
for a in "$@"; do [[ "$a" == "-w0" ]] || args+=("$a"); done
exec /usr/bin/base64 "${args[@]}"
EOF
    chmod +x "$TEST_DIR/bin/base64"
  fi
}

teardown() {
  rm -rf "$TEST_DIR"
}

# ── Tag construction ──────────────────────────────────────────────────────────

@test "[build-review-image] tag is review-<slug>-<sha>" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Image tag: review-feature-my-branch-abc1234"* ]]
}

@test "[build-review-image] tag is review-<slug>-<sha> for different slug/sha" {
  export CI_COMMIT_REF_SLUG="fix-broken-pipe"
  export CI_COMMIT_SHORT_SHA="deadbeef"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Image tag: review-fix-broken-pipe-deadbeef"* ]]
}

# ── Missing required vars ─────────────────────────────────────────────────────

@test "[build-review-image] missing ECR_REGISTRY → exit non-zero" {
  unset ECR_REGISTRY
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[build-review-image] missing CI_COMMIT_REF_SLUG → exit non-zero" {
  unset CI_COMMIT_REF_SLUG
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "[build-review-image] missing GITLAB_OIDC_TOKEN → exit non-zero" {
  unset GITLAB_OIDC_TOKEN
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}

# ── OIDC / STS ────────────────────────────────────────────────────────────────

@test "[build-review-image] empty STS output → exit 1 with error message" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then printf ''; exit 0; fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

@test "[build-review-image] STS CLI failure → exit non-zero and surfaces error" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/bin/bash
if [[ "$*" == *"assume-role-with-web-identity"* ]]; then
  printf 'AccessDenied: not authorised\n' >&2; exit 255
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"STS assume-role failed"* ]]
}

# ── Preflight tag-existence check ─────────────────────────────────────────────

@test "[build-review-image] tag already exists → skip build+push, exit 0" {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/bin/bash
if [[ "\$*" == *"assume-role-with-web-identity"* ]]; then
  printf 'AKIAIOSFODNN7EXAMPLE secretkey AQoXnyc4lcK4w\n'; exit 0
fi
if [[ "\$*" == *"get-caller-identity"* ]]; then exit 0; fi
if [[ "\$*" == *"describe-images"* ]]; then exit 0; fi  # tag exists
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skipping build+push"* ]]
  [ ! -f "$TEST_DIR/buildah.log" ]
}

# ── Build / push ──────────────────────────────────────────────────────────────

@test "[build-review-image] buildah build called with review tag" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "review-feature-my-branch-abc1234" "$TEST_DIR/buildah.log"
}

@test "[build-review-image] buildah push called with review tag" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "push.*review-feature-my-branch-abc1234" "$TEST_DIR/buildah.log"
}

@test "[build-review-image] buildah push failure → exit non-zero" {
  cat >"$TEST_DIR/bin/buildah" <<'EOF'
#!/bin/bash
if [[ "$1" == "push" ]]; then
  echo "push: server error" >&2; exit 1
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/buildah"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
}
