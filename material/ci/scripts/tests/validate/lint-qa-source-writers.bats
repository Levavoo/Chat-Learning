#!/usr/bin/env bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
LINT="$REPO_ROOT/.gitlab/ci/scripts/validate/lint-qa-source-writers.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/.gitlab/ci/deploy/qa"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[#631 lint] passes on the current tree (real deploy.yml + retrieval-promotion.yml)" {
  run "$LINT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
}

@test "[#631 lint] true-negative: deploy-etl-candidate:qa (the real writer child job) is not flagged directly, because its parent trigger holds the lock" {
  # deploy-etl-candidate:qa lives in retrieval-promotion.yml and has no own
  # resource_group — this must NOT be interpreted as an unguarded writer.
  # The lint only requires deploy.yml's trigger job to hold the lock (rule 1),
  # which the real qa-retrieval-promotion job does.
  grep -A5 '^deploy-etl-candidate:qa:' \
    "$REPO_ROOT/.gitlab/ci/deploy/qa/retrieval-promotion.yml" \
    | grep -qv 'resource_group:'
  run "$LINT"
  [ "$status" -eq 0 ]
}

@test "[#631 lint] fails when a trigger of retrieval-promotion.yml has no deploy-qa lock and is not exempt" {
  cat >"$TEST_DIR/.gitlab/ci/deploy/qa/deploy.yml" <<'EOF'
some-other-job:
  stage: deploy-app
  script:
    - echo hi

qa-retrieval-promotion:
  stage: deploy-app
  trigger:
    include:
      - local: .gitlab/ci/deploy/qa/retrieval-promotion.yml
    strategy: mirror
  rules:
    - when: on_success
EOF
  REPO_ROOT="$TEST_DIR" run "$LINT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"qa-retrieval-promotion"* ]]
  [[ "$output" == *"without 'resource_group: deploy-qa'"* ]]
}

@test "[#631 lint] passes when a trigger of retrieval-promotion.yml is the explicitly exempt rehearsal job" {
  cat >"$TEST_DIR/.gitlab/ci/deploy/qa/deploy.yml" <<'EOF'
qa-retrieval-promotion:
  stage: deploy-app
  resource_group: deploy-qa
  trigger:
    include:
      - local: .gitlab/ci/deploy/qa/retrieval-promotion.yml
    strategy: mirror
  rules:
    - when: on_success

qa-retrieval-promotion-rehearsal:
  stage: deploy-app
  trigger:
    include:
      - local: .gitlab/ci/deploy/qa/retrieval-promotion.yml
    strategy: mirror
  rules:
    - when: on_success
EOF
  REPO_ROOT="$TEST_DIR" run "$LINT"
  [ "$status" -eq 0 ]
}

@test "[#631 lint] fails when a new job in deploy.yml invokes the writer script without resource_group: deploy-qa" {
  cat >"$TEST_DIR/.gitlab/ci/deploy/qa/deploy.yml" <<'EOF'
qa-retrieval-promotion:
  stage: deploy-app
  resource_group: deploy-qa
  trigger:
    include:
      - local: .gitlab/ci/deploy/qa/retrieval-promotion.yml
    strategy: mirror
  rules:
    - when: on_success

rogue-writer:qa:
  stage: deploy-app
  script:
    - .gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh
EOF
  REPO_ROOT="$TEST_DIR" run "$LINT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"rogue-writer:qa"* ]]
  [[ "$output" == *"without 'resource_group: deploy-qa'"* ]]
}

@test "[#631 lint] passes when a new job in deploy.yml invokes the writer script WITH resource_group: deploy-qa" {
  cat >"$TEST_DIR/.gitlab/ci/deploy/qa/deploy.yml" <<'EOF'
qa-retrieval-promotion:
  stage: deploy-app
  resource_group: deploy-qa
  trigger:
    include:
      - local: .gitlab/ci/deploy/qa/retrieval-promotion.yml
    strategy: mirror
  rules:
    - when: on_success

locked-writer:qa:
  stage: deploy-app
  resource_group: deploy-qa
  script:
    - .gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh
EOF
  REPO_ROOT="$TEST_DIR" run "$LINT"
  [ "$status" -eq 0 ]
}
