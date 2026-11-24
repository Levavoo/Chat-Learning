#!/usr/bin/env bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/.gitlab/ci/scripts/verify/frontend-browser-smoke.sh"
TEMPLATE_YAML="$REPO_ROOT/.gitlab/ci/deploy/frontend-browser-smoke.yml"
FRONTEND_YAML="$REPO_ROOT/.gitlab/ci/deploy/frontend.yml"
DEV_YAML="$REPO_ROOT/.gitlab/ci/deploy/dev.yml"
QA_YAML="$REPO_ROOT/.gitlab/ci/deploy/qa/retrieval-promotion.yml"
PROD_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/retrieval-promotion.yml"
PROD_PARENT_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/deploy.yml"
PROD_ROLLBACK_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/retrieval-rollback.yml"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export PATH="$TEST_DIR/bin:$PATH"
  export ENV_LABEL="test"
  export NPM_LOG="$TEST_DIR/npm.log"
  export FRONTEND_ANONYMOUS_ACCESS="false"
  cd "$REPO_ROOT"

  cat >"$TEST_DIR/bin/npm" <<'EOF'
#!/usr/bin/env bash
printf 'pwd=%s args=%s base=%s path=%s sha=%s anonymous=%s\n' \
  "$PWD" "$*" "${FRONTEND_BASE_URL:-}" \
  "${FRONTEND_ENTRYPOINT_PATH:-}" "${FRONTEND_ENTRYPOINT_SHA256:-}" \
  "${FRONTEND_ANONYMOUS_ACCESS:-}" \
  >>"$NPM_LOG"
EOF
  chmod +x "$TEST_DIR/bin/npm"
}

teardown() {
  rm -rf "$TEST_DIR"
}

job_block() {
  local file="$1" job="$2"
  awk -v header="${job}:" '
    $0 == header { active=1; print; next }
    active && /^#/ { exit }
    active && /^[^[:space:]#][^[:space:]]*:[[:space:]]*$/ { exit }
    active { print }
  ' "$file"
}

@test "[frontend-browser-smoke] false deploy signal fails closed without invoking npm" {
  export FRONTEND_DEPLOYED=false
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FRONTEND_DEPLOYED must be true"* ]]
  [ ! -e "$NPM_LOG" ]
}

@test "[frontend-browser-smoke] missing deploy signal fails closed" {
  unset FRONTEND_DEPLOYED
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FRONTEND_DEPLOYED is missing"* ]]
}

@test "[frontend-browser-smoke] deployed frontend requires all dotenv evidence" {
  export FRONTEND_DEPLOYED=true
  unset CF_URL FRONTEND_ENTRYPOINT_PATH FRONTEND_ENTRYPOINT_SHA256
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"CF_URL is required"* ]]
}

@test "[frontend-browser-smoke] missing landing configuration fails closed" {
  export FRONTEND_DEPLOYED=true
  export CF_URL="https://frontend.example.test/"
  export FRONTEND_ENTRYPOINT_PATH="main.js"
  export FRONTEND_ENTRYPOINT_SHA256="$(printf 'a%.0s' {1..64})"
  unset FRONTEND_ANONYMOUS_ACCESS

  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FRONTEND_ANONYMOUS_ACCESS is missing"* ]]
  [ ! -e "$NPM_LOG" ]
}

@test "[frontend-browser-smoke] invalid landing configuration fails closed" {
  export FRONTEND_DEPLOYED=true
  export CF_URL="https://frontend.example.test/"
  export FRONTEND_ENTRYPOINT_PATH="main.js"
  export FRONTEND_ENTRYPOINT_SHA256="$(printf 'a%.0s' {1..64})"
  export FRONTEND_ANONYMOUS_ACCESS="yes"

  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FRONTEND_ANONYMOUS_ACCESS must be true or false"* ]]
  [ ! -e "$NPM_LOG" ]
}

@test "[frontend-browser-smoke] passes deploy evidence and both landing modes to npm" {
  export FRONTEND_DEPLOYED=true
  export CF_URL="https://frontend.example.test/"
  export FRONTEND_ENTRYPOINT_PATH="main.js"
  export FRONTEND_ENTRYPOINT_SHA256="$(printf 'a%.0s' {1..64})"

  for anonymous_access in false true; do
    export FRONTEND_ANONYMOUS_ACCESS="$anonymous_access"
    run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    tail -n 1 "$NPM_LOG" | grep -q "args=run test:smoke:deployed"
    tail -n 1 "$NPM_LOG" | grep -q "base=https://frontend.example.test/"
    tail -n 1 "$NPM_LOG" | grep -q "path=main.js"
    tail -n 1 "$NPM_LOG" | grep -q "sha=${FRONTEND_ENTRYPOINT_SHA256}"
    tail -n 1 "$NPM_LOG" | grep -q "anonymous=${anonymous_access}"
  done
}

@test "[frontend-browser-smoke] shared runtime is environment-neutral and has no AWS identity" {
  run job_block "$TEMPLATE_YAML" ".frontend_browser_smoke_base"
  [ "$status" -eq 0 ]
  [[ "$output" == *"node-chromium:0.2.0"* ]]
  [[ "$output" == *"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"* ]]
  [[ "$output" == *"frontend-browser-smoke.sh"* ]]
  [[ "$output" != *"ENV_LABEL"* ]]
  [[ "$output" != *"ROLE_ARN"* ]]
  [[ "$output" != *"id_tokens"* ]]
  [[ "$output" != *"aws_oidc"* ]]
}

@test "[frontend-browser-smoke] dev always deploys and browser job needs its artifact" {
  local deploy_base deploy_block browser_block
  deploy_base="$(job_block "$FRONTEND_YAML" ".frontend_deploy_base")"
  deploy_block="$(job_block "$FRONTEND_YAML" "deploy-frontend:dev")"
  browser_block="$(job_block "$FRONTEND_YAML" "frontend-browser-smoke:dev")"
  [[ "$deploy_base" == *'.gitlab/ci/scripts/deploy/deploy-frontend.sh "$ENV"'* ]]
  [[ "$deploy_block" != *"BUMPED"* ]]
  [[ "$deploy_block" != *"FRONTEND_DEPLOYED=false"* ]]
  [[ "$deploy_block" != *"No version bump"* ]]
  [[ "$browser_block" == *"extends: .frontend_browser_smoke_base"* ]]
  [[ "$browser_block" == *"job: deploy-frontend:dev"* ]]
  [[ "$browser_block" == *"artifacts: true"* ]]
  [[ "$browser_block" == *"ENV_LABEL: dev"* ]]
  [[ "$browser_block" != *"activate-retrieval"* ]]
  [[ "$browser_block" != *"retrieval"* ]]
}

@test "[frontend-browser-smoke] QA deploy evidence gates smoke and downstream promotions" {
  grep -q 'local: .gitlab/ci/deploy/frontend-browser-smoke.yml' "$QA_YAML"
  local browser_block smoke_block preprod_block prod_block notify_block
  browser_block="$(job_block "$QA_YAML" "frontend-browser-smoke:qa")"
  smoke_block="$(job_block "$QA_YAML" "smoke-eval:qa")"
  preprod_block="$(job_block "$QA_YAML" "open-preprod-mr")"
  prod_block="$(job_block "$QA_YAML" "open-prod-mr")"
  notify_block="$(job_block "$QA_YAML" "notify-rocketchat:qa")"

  [[ "$browser_block" == *"extends: .frontend_browser_smoke_base"* ]]
  [[ "$browser_block" == *"job: deploy-frontend:qa"* ]]
  [[ "$browser_block" == *"artifacts: true"* ]]
  [[ "$browser_block" == *"ENV_LABEL: qa"* ]]
  [[ "$browser_block" == *'PIPELINE_TASK == "retrieval-promotion-rehearsal"'* ]]
  [[ "$browser_block" == *"when: never"* ]]
  [[ "$browser_block" != *"activate-retrieval"* ]]
  [[ "$smoke_block" == *"job: activate-retrieval:qa"* ]]
  [[ "$smoke_block" == *"job: frontend-browser-smoke:qa"* ]]
  [[ "$preprod_block" == *"job: smoke-eval:qa"* ]]
  [[ "$prod_block" == *"job: smoke-eval:qa"* ]]
  [[ "$notify_block" == *"job: smoke-eval:qa"* ]]
}

@test "[frontend-browser-smoke] Prod deploy evidence gates smoke and success while rollback stays manual" {
  grep -q 'local: .gitlab/ci/deploy/frontend-browser-smoke.yml' "$PROD_YAML"
  local browser_block smoke_block notify_block bridge_block rollback_block
  browser_block="$(job_block "$PROD_YAML" "frontend-browser-smoke:prod")"
  smoke_block="$(job_block "$PROD_YAML" "smoke-eval:prod")"
  notify_block="$(job_block "$PROD_YAML" "notify-rocketchat:prod")"
  bridge_block="$(job_block "$PROD_PARENT_YAML" "prod-retrieval-promotion")"
  rollback_block="$(job_block "$PROD_ROLLBACK_YAML" "rollback-retrieval:prod")"

  [[ "$browser_block" == *"extends: .frontend_browser_smoke_base"* ]]
  [[ "$browser_block" == *"job: deploy-frontend:prod"* ]]
  [[ "$browser_block" == *"artifacts: true"* ]]
  [[ "$browser_block" == *"ENV_LABEL: prod"* ]]
  [[ "$browser_block" == *'PIPELINE_TASK == "prod-retrieval-promotion-rehearsal"'* ]]
  [[ "$browser_block" == *"when: never"* ]]
  [[ "$browser_block" != *"activate-retrieval"* ]]
  [[ "$smoke_block" == *"job: activate-retrieval:prod"* ]]
  [[ "$smoke_block" == *"job: frontend-browser-smoke:prod"* ]]
  [[ "$notify_block" == *"job: smoke-eval:prod"* ]]
  [[ "$bridge_block" == *"strategy: mirror"* ]]
  [[ "$rollback_block" == *"when: manual"* ]]
  [[ "$rollback_block" != *"frontend-browser-smoke"* ]]
}

@test "[frontend-browser-smoke] smoke eval and QA promotion form the final gate chain" {
  local smoke_block promotion_block
  smoke_block="$(job_block "$DEV_YAML" "smoke-eval:dev")"
  promotion_block="$(job_block "$DEV_YAML" "open-qa-mr")"

  [[ "$smoke_block" == *"job: frontend-browser-smoke:dev"* ]]
  [[ "$promotion_block" == *"job: smoke-eval:dev"* ]]
  [[ "$promotion_block" == *"job: cocogitto-release"* ]]
  [[ "$promotion_block" == *"job: build-data-artifacts"* ]]
  [[ "$promotion_block" == *"job: build-etl-image:dev"* ]]
}
