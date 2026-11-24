#!/usr/bin/env bats
# #643 D10 — deployment-path guardrails. After cutover, ordinary promotion is
# the ONLY path that may build a candidate or move a selector. These tests lock
# the structural invariants that keep direct, configuration-only, and
# foundation paths from bypassing it.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPTS="$REPO_ROOT/.gitlab/ci/scripts"
PREPROD_YAML="$REPO_ROOT/.gitlab/ci/deploy/preprod/deploy.yml"
CHILD_YAML="$REPO_ROOT/.gitlab/ci/deploy/preprod/retrieval-promotion.yml"
CANDIDATE="$SCRIPTS/deploy/deploy-retrieval-candidate.sh"
CHATBOT="$SCRIPTS/deploy/deploy-retrieval-chatbot.sh"
ACTIVATE="$SCRIPTS/deploy/activate-retrieval.sh"
FOUNDATION="$SCRIPTS/deploy/deploy-preprod-retrieval-foundation.sh"
DEPLOY_ENV="$SCRIPTS/deploy/deploy-env.sh"

_job_block() {
  awk -v key="$1:" '
    $0 == key { found = 1 }
    found && $0 != key && /^[^[:space:]#][^:]*:$/ { exit }
    found { print }
  ' "$2"
}

@test "[#643 guardrail] direct generic preprod deployment is refused" {
  run "$DEPLOY_ENV" preprod
  [ "$status" -ne 0 ]
  [[ "$output" == *"Direct preprod deployment is disabled"* ]]
  [[ "$output" == *"preprod-retrieval-promotion"* ]]
}

@test "[#643 guardrail] legacy direct preprod deploy/smoke jobs stay disabled" {
  _job_block cdk-deploy:preprod "$PREPROD_YAML" | grep -q -- '- when: never'
  _job_block smoke-eval:preprod "$PREPROD_YAML" | grep -q -- '- when: never'
}

@test "[#643 guardrail] only activation and rollback may write retrieval selectors" {
  # The candidate build and the chatbot deploy must never move a selector —
  # they only ASSERT it is unchanged (deploy != activate). A selector write
  # outside activation/rollback would decouple semantic+BM25 from the chatbot.
  ! grep -qE 'put-parameter.*(ACTIVE_SELECTOR|PREVIOUS_SELECTOR)' "$CANDIDATE"
  ! grep -qE 'put-parameter' "$CHATBOT"
  ! grep -qE 'put-parameter.*(active-manifest|previous-manifest)' "$FOUNDATION"
  # activation does write them (the one atomic transition)
  grep -q 'selector-transition' "$ACTIVATE"
}

@test "[#643 guardrail] candidate and chatbot deploy assert selectors unchanged" {
  [ "$(grep -c 'qa_retrieval_assert_selectors_unchanged' "$CANDIDATE")" -ge 3 ]
  [ "$(grep -c 'qa_retrieval_assert_selectors_unchanged' "$CHATBOT")" -ge 2 ]
}

@test "[#643 guardrail] configuration-only promotions reuse the validated active manifest" {
  # decidePromotionPath returns chatbot-only only when data/etl/tokenizer/
  # artifact-id all match the ACTIVE manifest, and the chatbot-only manifest is
  # built from that active manifest — so a config-only change cannot silently
  # rebuild or repoint retrieval.
  grep -q 'decide-path' "$CANDIDATE"
  grep -q 'path: "chatbot-only"' "$CANDIDATE"
  grep -q 'activeManifest: \$active\[0\]' "$CANDIDATE"
  # and it never replays raw data on that path: the raw sync/replay calls live
  # in the full-retrieval branch only
  awk '/if \[\[ "\$CHATBOT_ONLY" == true \]\]; then/,/^else$/' "$CANDIDATE" \
    >"$BATS_TEST_TMPDIR/chatbot-only.txt"
  ! grep -q 'qa_retrieval_replay_tree' "$BATS_TEST_TMPDIR/chatbot-only.txt"
  ! grep -q 'qa_retrieval_sync_tree_write_once' "$BATS_TEST_TMPDIR/chatbot-only.txt"
}

@test "[#643 guardrail] the transaction lock is held by the bridge, not child jobs" {
  _job_block preprod-retrieval-promotion "$PREPROD_YAML" |
    grep -q 'resource_group: deploy-preprod'
  _job_block preprod-retrieval-promotion "$PREPROD_YAML" | grep -q 'strategy: mirror'
  # no child job may re-acquire it (nested acquisition would deadlock)
  ! grep -qE '^\s+resource_group:' "$CHILD_YAML"
}

@test "[#643 guardrail] one explicit development approval precedes the transaction" {
  # The approval is an environment-tracked job the bridge depends on. Its
  # single-operator policy is a reviewed positional argument, not a variable
  # that a manual pipeline can replace.
  _job_block approve-preprod-promotion "$PREPROD_YAML" | grep -q 'when: manual'
  _job_block approve-preprod-promotion "$PREPROD_YAML" | grep -q 'name: deploy/preprod'
  _job_block approve-preprod-promotion "$PREPROD_YAML" |
    grep -q 'record-retrieval-promotion-development-approval.sh'
  _job_block approve-preprod-promotion "$PREPROD_YAML" |
    grep -q 'preprod-retrieval-promotion-approval.json'
  _job_block approve-preprod-promotion "$PREPROD_YAML" |
    grep -q 'development-single-operator'
  ! _job_block approve-preprod-promotion "$PREPROD_YAML" |
    grep -q 'FOUR_EYES'
  _job_block preprod-retrieval-promotion "$PREPROD_YAML" |
    grep -q 'job: approve-preprod-promotion'
  # the preflight that feeds the approval is automatic and takes no lock
  # (anchor on the YAML key — surrounding prose legitimately mentions the word)
  _job_block validate-retrieval-promotion:preprod "$PREPROD_YAML" \
    >"$BATS_TEST_TMPDIR/preflight.txt"
  grep -q 'deploy-retrieval-candidate.sh preprod --dry-run' "$BATS_TEST_TMPDIR/preflight.txt"
  grep -q 'npm ci --cache ../.npm --prefer-offline' "$BATS_TEST_TMPDIR/preflight.txt"
  ! grep -qE '^[[:space:]]+resource_group:' "$BATS_TEST_TMPDIR/preflight.txt"
  ! grep -qE '^[[:space:]]+environment:' "$BATS_TEST_TMPDIR/preflight.txt"
}

@test "[#643 guardrail] every preprod mutation path is master-only and human-gated" {
  # Two entry points now exist (explicit web task, and merging the preprod pin),
  # so "web task only" is no longer the invariant. What must hold is: both paths
  # are master-only, unrelated explicit tasks cannot start a promotion, the rules
  # are closed by default, and no path reaches a mutation without a human.
  for job in validate-retrieval-promotion:preprod approve-preprod-promotion \
    preprod-retrieval-promotion; do
    _job_block "$job" "$PREPROD_YAML" >"$BATS_TEST_TMPDIR/job.txt"
    grep -q 'CI_COMMIT_BRANCH == \$CI_DEFAULT_BRANCH' "$BATS_TEST_TMPDIR/job.txt"
    # every branch comparison in the job must name the default branch, not a
    # literal — one guard, not many
    branches=$(grep -oE 'CI_COMMIT_BRANCH == [^[:space:]]+' "$BATS_TEST_TMPDIR/job.txt" \
      | sort -u)
    [ "$branches" = 'CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH' ]
    # entry point 1: the explicit development web task
    grep -q 'CI_PIPELINE_SOURCE == "web"' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'PIPELINE_TASK == "preprod-retrieval-promotion-development"' \
      "$BATS_TEST_TMPDIR/job.txt"
    # entry point 2: merging the preprod pin on master
    grep -q 'deployments/preprod/version.yaml' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'CI_PIPELINE_SOURCE != "merge_request_event"' "$BATS_TEST_TMPDIR/job.txt"
    # rehearsal/health/retention/rollback tasks must not start a promotion
    grep -q 'if: \$PIPELINE_TASK' "$BATS_TEST_TMPDIR/job.txt"
    # closed by default
    grep -q -- '- when: never' "$BATS_TEST_TMPDIR/job.txt"
  done

  # The human gate: approval is manual on every path it is reachable from, and
  # can never resolve to on_success.
  _job_block approve-preprod-promotion "$PREPROD_YAML" >"$BATS_TEST_TMPDIR/a.txt"
  [ "$(grep -c 'when: manual' "$BATS_TEST_TMPDIR/a.txt")" -ge 2 ]
  ! grep -q 'when: on_success' "$BATS_TEST_TMPDIR/a.txt"

  # And the transaction cannot precede that approval.
  _job_block preprod-retrieval-promotion "$PREPROD_YAML" \
    | grep -q 'job: approve-preprod-promotion'
}

@test "[#643 guardrail] the rehearsal takes no lock and cannot mutate" {
  _job_block preprod-retrieval-promotion-rehearsal "$PREPROD_YAML" \
    >"$BATS_TEST_TMPDIR/rehearsal.txt"
  ! grep -qE '^[[:space:]]+resource_group:' "$BATS_TEST_TMPDIR/rehearsal.txt"
  grep -q 'strategy: mirror' "$BATS_TEST_TMPDIR/rehearsal.txt"
  # every real-mutation child stage excludes the rehearsal task
  for job in deploy-chatbot:preprod activate-retrieval:preprod smoke-eval:preprod; do
    _job_block "$job" "$CHILD_YAML" |
      grep -q 'PIPELINE_TASK == "preprod-retrieval-promotion-rehearsal"'
  done
}
