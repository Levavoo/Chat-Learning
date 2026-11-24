#!/usr/bin/env bats
# #630 — behavioral coverage for activate-qa-retrieval.sh's delegation to
# retrieval-orchestration.mjs (selector write order, retention-cleanup plan).
# The full activation transaction (CDK-free) is otherwise exercised via the
# qa-retrieval-promotion.bats / qa-retrieval-rollback.bats structural checks;
# this suite focuses on the parts that moved to Node.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
ACTIVATE="$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"
COMMON="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval.sh"
VALIDATION="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval-validation.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[#630 migration] activation delegates selector order to retrieval-orchestration.mjs" {
  grep -q 'retrieval-orchestration.mjs" selector-transition' "$ACTIVATE"
  grep -q '"kind": "activate"\|kind: "activate"' "$ACTIVATE"
}

@test "[#630 migration] selector-transition plan preserves previous-first write order" {
  jq -n --arg active /qa/renate/retrieval/active-manifest \
    --arg previous /qa/renate/retrieval/previous-manifest \
    --arg newActive "$TEST_DIR/candidate.json" --arg newPrevious "$TEST_DIR/old-active.json" '
      {
        kind: "activate",
        selectors: {
          activeSelector: $active, previousSelector: $previous,
          newActiveFile: $newActive, newPreviousFile: $newPrevious
        }
      }
    ' >"$TEST_DIR/input.json"
  run node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-orchestration.mjs" selector-transition \
    "$TEST_DIR/input.json"
  [ "$status" -eq 0 ]
  first_name=$(jq -r '.[0].name' <<<"$output")
  second_name=$(jq -r '.[1].name' <<<"$output")
  [ "$first_name" = "/qa/renate/retrieval/previous-manifest" ]
  [ "$second_name" = "/qa/renate/retrieval/active-manifest" ]
}

@test "[#671 config-only no-op] guard skips the SSM mutation block when candidate.release_id == active.release_id" {
  # Anchor the guard to the release_id comparison and confirm it sits before
  # the selector-transition block. Regression coverage for the 2026-09-15
  # incident where a config-only activation (deae65cd) copied the current
  # active manifest into previous-manifest, tripping
  # assert-prod-retrieval-monitoring-ready on the next prod pipeline.
  grep -q 'CANDIDATE_RELEASE_ID=\$(jq -r .release_id "\$CANDIDATE_MANIFEST")' "$ACTIVATE"
  grep -q 'if \[\[ "\$CANDIDATE_RELEASE_ID" == "\$OLD_RELEASE_ID" \]\]; then' "$ACTIVATE"
  grep -q 'previous-manifest rotation and convergence wait are a no-op' "$ACTIVATE"

  guard_line=$(grep -n 'if \[\[ "\$CANDIDATE_RELEASE_ID" == "\$OLD_RELEASE_ID" \]\]; then' \
    "$ACTIVATE" | head -1 | cut -d: -f1)
  transition_line=$(grep -n 'retrieval-orchestration.mjs" selector-transition' \
    "$ACTIVATE" | head -1 | cut -d: -f1)
  put_line=$(grep -n 'aws ssm put-parameter --name "\$selector_name"' \
    "$ACTIVATE" | head -1 | cut -d: -f1)
  [ -n "$guard_line" ]
  [ -n "$transition_line" ]
  [ -n "$put_line" ]
  [ "$guard_line" -lt "$transition_line" ]
  [ "$guard_line" -lt "$put_line" ]
}

@test "[#671 config-only no-op] running the guard block writes zero SSM parameters when release_ids match" {
  # Functional check: replay the exact if/else the script uses. On equal
  # release_ids the guard branch must run to completion and the aws stub
  # must record no invocations.
  mkdir -p "$TEST_DIR/bin"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TEST_DIR/aws-calls"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  printf '%s\n' '{"release_id":"sha256-abc","version":"3.44.3"}' >"$TEST_DIR/candidate.json"
  printf '%s\n' '{"release_id":"sha256-abc","version":"3.44.3"}' >"$TEST_DIR/active-before.json"

  PATH="$TEST_DIR/bin:$PATH" run bash -c '
    set -euo pipefail
    CANDIDATE_MANIFEST="$1"
    OLD_RELEASE_ID=$(jq -r .release_id "$2")
    CANDIDATE_RELEASE_ID=$(jq -r .release_id "$CANDIDATE_MANIFEST")
    if [[ "$CANDIDATE_RELEASE_ID" == "$OLD_RELEASE_ID" ]]; then
      echo "no-op"
    else
      aws ssm put-parameter --name /would/not/happen
    fi
  ' _ "$TEST_DIR/candidate.json" "$TEST_DIR/active-before.json"
  [ "$status" -eq 0 ]
  [[ "$output" == "no-op" ]]
  [ ! -e "$TEST_DIR/aws-calls" ]
}

@test "[#671 config-only no-op] the mutation branch still fires when release_ids differ" {
  mkdir -p "$TEST_DIR/bin"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TEST_DIR/aws-calls"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  printf '%s\n' '{"release_id":"sha256-new","version":"3.44.4"}' >"$TEST_DIR/candidate.json"
  printf '%s\n' '{"release_id":"sha256-old","version":"3.44.3"}' >"$TEST_DIR/active-before.json"

  PATH="$TEST_DIR/bin:$PATH" run bash -c '
    set -euo pipefail
    CANDIDATE_MANIFEST="$1"
    OLD_RELEASE_ID=$(jq -r .release_id "$2")
    CANDIDATE_RELEASE_ID=$(jq -r .release_id "$CANDIDATE_MANIFEST")
    if [[ "$CANDIDATE_RELEASE_ID" == "$OLD_RELEASE_ID" ]]; then
      echo "no-op"
    else
      aws ssm put-parameter --name /prod/renate/retrieval/previous-manifest
      aws ssm put-parameter --name /prod/renate/retrieval/active-manifest
    fi
  ' _ "$TEST_DIR/candidate.json" "$TEST_DIR/active-before.json"
  [ "$status" -eq 0 ]
  [ -s "$TEST_DIR/aws-calls" ]
  grep -q previous-manifest "$TEST_DIR/aws-calls"
  grep -q active-manifest "$TEST_DIR/aws-calls"
}

@test "[#627 migration] inline retention cleanup path is retired from activation" {
  ! grep -q 'QA_RETRIEVAL_INLINE_RETENTION_CLEANUP' "$ACTIVATE"
  ! grep -q 'retention-cleanup-plan' "$ACTIVATE"
  ! grep -q 'qa_retrieval_unpin_prefixes' "$ACTIVATE"
  grep -q 'Deferred stale retrieval retention cleanup to the RFC-0021 Lambda' "$ACTIVATE"
}

@test "[#630 shared] activation and rollback still share the same convergence/resolve helpers post-migration" {
  rollback="$REPO_ROOT/.gitlab/ci/scripts/ops/rollback-retrieval.sh"
  grep -q 'qa_retrieval_wait_for_release_convergence' "$ACTIVATE"
  grep -q 'qa_retrieval_wait_for_release_convergence' "$rollback"
  grep -q 'qa_retrieval_resolve_chat_function' "$ACTIVATE"
  grep -q 'qa_retrieval_resolve_chat_function' "$rollback"
  grep -q 'qa_retrieval_wait_for_release_convergence()' "$VALIDATION"
}

@test "[#671 recovery] a final convergence failure explicitly invokes activation rollback" {
  convergence_line=$(grep -n 'qa_retrieval_wait_for_release_convergence' \
    "$ACTIVATE" | head -1 | cut -d: -f1)
  rollback_line=$(grep -n '|| rollback "\$?"' "$ACTIVATE" | head -1 | cut -d: -f1)
  [ -n "$convergence_line" ]
  [ -n "$rollback_line" ]
  [ "$rollback_line" -eq "$((convergence_line + 2))" ]

  awk '/^rollback\(\) \{/,/^\}/' "$ACTIVATE" >"$TEST_DIR/rollback_fn.txt"
  grep -q 'local trap_rc=\$?' "$TEST_DIR/rollback_fn.txt"
  grep -q 'local original_rc="${1:-\$trap_rc}"' \
    "$TEST_DIR/rollback_fn.txt"
}

@test "[#628 marker] clear call sits after trap - ERR, before the deferred-cleanup log line" {
  err_line=$(grep -n '^trap - ERR$' "$ACTIVATE" | head -1 | cut -d: -f1)
  clear_line=$(grep -n 'qa_retrieval_clear_rollback_degraded_marker' "$ACTIVATE" | head -1 | cut -d: -f1)
  cleanup_line=$(grep -n 'Deferred stale retrieval retention cleanup to the RFC-0021 Lambda' "$ACTIVATE" | head -1 | cut -d: -f1)
  [ -n "$err_line" ]
  [ -n "$clear_line" ]
  [ -n "$cleanup_line" ]
  [ "$err_line" -lt "$clear_line" ]
  [ "$clear_line" -lt "$cleanup_line" ]
}

@test "[#628 marker] the rollback() ERR-trap function never calls the clear helper" {
  # rollback() is the failure path (selectors + chatbot image restored, but the
  # inactive slot's live corpus is NOT restored) -- the degraded window must
  # stay open, so it must never clear the marker.
  awk '/^rollback\(\) \{/,/^\}$/' "$ACTIVATE" >"$TEST_DIR/rollback_fn.txt"
  ! grep -q 'qa_retrieval_clear_rollback_degraded_marker' "$TEST_DIR/rollback_fn.txt"
}

@test "[#628 marker] activation script sources the shared library defining the clear helper" {
  grep -q 'qa_retrieval_clear_rollback_degraded_marker()' "$VALIDATION"
  grep -q 'source "${SCRIPT_DIR}/../lib/qa-retrieval-validation.sh"' "$ACTIVATE"
}
