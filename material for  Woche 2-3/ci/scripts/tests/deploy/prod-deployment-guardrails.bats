#!/usr/bin/env bats
# #670/#671 prod promotion guardrails. Promotion and rollback remain behind
# their manual gates; health and retention expose only their reviewed task
# entry points.
#
# These are static structural assertions on the committed YAML (no AWS, no
# GitLab evaluation engine) — the same style as the preprod suite.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPTS="$REPO_ROOT/.gitlab/ci/scripts"
PROD_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/deploy.yml"
CHILD_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/retrieval-promotion.yml"
QA_YAML="$REPO_ROOT/.gitlab/ci/deploy/qa/retrieval-promotion.yml"
ROLLBACK_YAML="$REPO_ROOT/.gitlab/ci/deploy/prod/retrieval-rollback.yml"
DEPLOY_ENV="$SCRIPTS/deploy/deploy-env.sh"
MONITORING_DEPLOY="$SCRIPTS/deploy/deploy-prod-retrieval-monitoring.sh"

# Print a single top-level job/anchor block. The boundary is any column-0,
# non-comment line ending in `:` — this correctly treats colon-containing job
# names (foo:prod:) as boundaries, so a block is captured cleanly.
_job_block() {
  awk -v key="$1:" '
    $0 == key { found = 1 }
    found && $0 != key && /^[^[:space:]#].*:$/ { exit }
    found { print }
  ' "$2"
}

# Print ONLY the `rules:` sub-block of a job (its indented children), stripping
# any following job's lead comment that _job_block may over-capture. This lets a
# negative assertion (e.g. "no when: manual") test the rule set in isolation of
# neighbouring prose.
_rules_block() {
  _job_block "$1" "$2" | awk '
    /^  rules:[[:space:]]*$/ { inr = 1; next }
    inr && /^    / { print; next }
    inr && /^$/ { next }
    inr { exit }
  '
}

@test "[#670 guardrail] direct generic prod deployment is refused" {
  run "$DEPLOY_ENV" prod
  [ "$status" -ne 0 ]
  [[ "$output" == *"Direct prod deployment is disabled"* ]]
}

@test "[#670 guardrail] legacy direct prod deploy/smoke placeholders stay disabled" {
  _job_block cdk-deploy:prod "$PROD_YAML" | grep -q -- '- when: never'
  _job_block smoke-eval:prod "$PROD_YAML" | grep -q -- '- when: never'
}

@test "[#670 guardrail] prod promotion mirrors the two preprod entry points" {
  for job in validate-retrieval-promotion:prod approve-prod-promotion \
    prod-retrieval-promotion; do
    _job_block "$job" "$PROD_YAML" >"$BATS_TEST_TMPDIR/job.txt"
    grep -q 'CI_COMMIT_BRANCH == \$CI_DEFAULT_BRANCH' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'CI_PIPELINE_SOURCE == "web"' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'PIPELINE_TASK == "prod-retrieval-promotion-development"' \
      "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'if: \$PIPELINE_TASK' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'deployments/prod/version.yaml' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'deployments/prod/config.yaml' "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'CI_PIPELINE_SOURCE != "merge_request_event"' \
      "$BATS_TEST_TMPDIR/job.txt"
    grep -q -- '- when: never' "$BATS_TEST_TMPDIR/job.txt"
  done
}

@test "[#670 guardrail] one recorded manual approval precedes every mutation" {
  _job_block approve-prod-promotion "$PROD_YAML" >"$BATS_TEST_TMPDIR/a.txt"
  grep -qE '^  when: manual$' "$BATS_TEST_TMPDIR/a.txt"
  [ "$(grep -c 'when: manual' "$BATS_TEST_TMPDIR/a.txt")" -ge 3 ]
  ! grep -q 'when: on_success' "$BATS_TEST_TMPDIR/a.txt"
  grep -q 'name: deploy/prod' "$BATS_TEST_TMPDIR/a.txt"
  grep -q 'record-retrieval-promotion-development-approval.sh' \
    "$BATS_TEST_TMPDIR/a.txt"
  grep -q 'prod-retrieval-promotion-approval.json' "$BATS_TEST_TMPDIR/a.txt"
  _job_block prod-retrieval-promotion "$PROD_YAML" |
    grep -q 'job: approve-prod-promotion'
}

@test "[#670 guardrail] prod rollback is manual, serialized, and notified" {
  _rules_block rollback-retrieval:prod "$ROLLBACK_YAML" >"$BATS_TEST_TMPDIR/r.txt"
  grep -q 'PIPELINE_TASK == "prod-retrieval-rollback"' "$BATS_TEST_TMPDIR/r.txt"
  grep -q 'CI_PIPELINE_SOURCE == "web"' "$BATS_TEST_TMPDIR/r.txt"
  grep -q 'when: manual' "$BATS_TEST_TMPDIR/r.txt"
  _job_block rollback-retrieval:prod "$ROLLBACK_YAML" |
    grep -q 'resource_group: deploy-prod'
  _job_block notify-rocketchat:prod-rollback "$ROLLBACK_YAML" |
    grep -q 'notify-rocketchat.sh prod rollback'
}

@test "[#671 monitoring] alarm actions use a separate protected ETL-only activation" {
  _job_block activate-prod-retrieval-monitoring "$PROD_YAML" \
    >"$BATS_TEST_TMPDIR/monitoring.txt"
  grep -q 'resource_group: deploy-prod' "$BATS_TEST_TMPDIR/monitoring.txt"
  grep -qE '^  when: manual$' "$BATS_TEST_TMPDIR/monitoring.txt"
  grep -q 'name: deploy/prod' "$BATS_TEST_TMPDIR/monitoring.txt"
  grep -q 'PIPELINE_TASK == "prod-retrieval-monitoring-activate"' \
    "$BATS_TEST_TMPDIR/monitoring.txt"
  grep -q 'resolve-attested-implementation.sh prod' \
    "$BATS_TEST_TMPDIR/monitoring.txt"
  grep -q 'prod-retrieval-monitoring-activation-evidence.json' \
    "$BATS_TEST_TMPDIR/monitoring.txt"
}

@test "[#671 monitoring] ETL deployment is template-allowlisted and selector-inert" {
  run bash -n "$MONITORING_DEPLOY"
  [ "$status" -eq 0 ]
  grep -q 'assert-prod-retrieval-monitoring-ready.sh' "$MONITORING_DEPLOY"
  grep -q 'RetrievalHealthAlarms' "$MONITORING_DEPLOY"
  grep -q 'ETL template contains changes outside retrieval-health AlarmActions' \
    "$MONITORING_DEPLOY"
  grep -q 'npx cdk deploy "\$RETRIEVAL_ETL_STACK"' "$MONITORING_DEPLOY"
  ! grep -q 'npx cdk deploy "\$RETRIEVAL_CHATBOT_STACK"' "$MONITORING_DEPLOY"
  grep -q 'cmp -s "\$ACTIVE_BEFORE" "\$ACTIVE_AFTER"' "$MONITORING_DEPLOY"
  grep -q 'cmp -s "\$PREVIOUS_BEFORE" "\$PREVIOUS_AFTER"' "$MONITORING_DEPLOY"
  ! grep -q 'ssm put-parameter' "$MONITORING_DEPLOY"
}

@test "[#670 guardrail] the rehearsal stays enabled, takes no lock, and cannot mutate" {
  _job_block prod-retrieval-promotion-rehearsal "$PROD_YAML" \
    >"$BATS_TEST_TMPDIR/rehearsal.txt"
  # still enabled (it was NOT killed with the mutating path)
  grep -q 'PIPELINE_TASK == "prod-retrieval-promotion-rehearsal"' \
    "$BATS_TEST_TMPDIR/rehearsal.txt"
  grep -q 'when: on_success' "$BATS_TEST_TMPDIR/rehearsal.txt"
  grep -q 'strategy: mirror' "$BATS_TEST_TMPDIR/rehearsal.txt"
  # takes no lock (read-only, must not serialize behind real deploys)
  ! grep -qE '^[[:space:]]+resource_group:' "$BATS_TEST_TMPDIR/rehearsal.txt"
}

@test "[#670 guardrail] rehearsal runs candidate dry-run and excludes mutation stages" {
  # The candidate stage reuses its own --dry-run under the rehearsal task.
  _job_block deploy-etl-candidate:prod "$CHILD_YAML" >"$BATS_TEST_TMPDIR/cand.txt"
  grep -q 'rehearsal_task="prod-retrieval-promotion-rehearsal"' \
    "$BATS_TEST_TMPDIR/cand.txt"
  grep -q 'prod --dry-run' "$BATS_TEST_TMPDIR/cand.txt"
  # Every real-mutation child stage excludes the rehearsal task (when: never).
  for job in deploy-chatbot:prod apigateway-redeploy:prod deploy-frontend:prod \
    frontend-browser-smoke:prod activate-retrieval:prod smoke-eval:prod; do
    _job_block "$job" "$CHILD_YAML" >"$BATS_TEST_TMPDIR/child.txt"
    grep -q 'PIPELINE_TASK == "prod-retrieval-promotion-rehearsal"' \
      "$BATS_TEST_TMPDIR/child.txt"
    grep -q 'when: never' "$BATS_TEST_TMPDIR/child.txt"
  done
}

@test "[#670 guardrail] only the mirrored parent owns deploy-prod" {
  _job_block prod-retrieval-promotion "$PROD_YAML" |
    grep -q 'resource_group: deploy-prod'
  _job_block prod-retrieval-promotion "$PROD_YAML" | grep -q 'strategy: mirror'
  ! grep -qE '^[[:space:]]+resource_group:' "$CHILD_YAML"
}

@test "[#670 QA handoff] green QA activation opens both downstream MRs" {
  _job_block open-preprod-mr "$QA_YAML" >"$BATS_TEST_TMPDIR/preprod-mr.txt"
  _job_block open-prod-mr "$QA_YAML" >"$BATS_TEST_TMPDIR/prod-mr.txt"
  grep -q 'open-promotion-mr.sh qa preprod' "$BATS_TEST_TMPDIR/preprod-mr.txt"
  grep -q 'open-promotion-mr.sh qa prod' "$BATS_TEST_TMPDIR/prod-mr.txt"
  grep -q 'when: on_success' "$BATS_TEST_TMPDIR/preprod-mr.txt"
  grep -q 'when: on_success' "$BATS_TEST_TMPDIR/prod-mr.txt"
}

@test "[#670 notification] successful promotion retains Rocket.Chat wiring" {
  _job_block notify-rocketchat:prod "$CHILD_YAML" |
    grep -q 'notify-rocketchat.sh prod'
}

@test "[#670 guardrail] maintenance switching is preserved and enabled" {
  _job_block maintenance-switch:prod "$PROD_YAML" >"$BATS_TEST_TMPDIR/m.txt"
  grep -q 'resource_group: deploy-prod' "$BATS_TEST_TMPDIR/m.txt"
  _rules_block maintenance-switch:prod "$PROD_YAML" >"$BATS_TEST_TMPDIR/m-rules.txt"
  grep -q 'deployments/prod/maintenance.yaml' "$BATS_TEST_TMPDIR/m-rules.txt"
  grep -q 'when: on_success' "$BATS_TEST_TMPDIR/m-rules.txt"
  ! grep -q 'when: never' "$BATS_TEST_TMPDIR/m-rules.txt"
}
