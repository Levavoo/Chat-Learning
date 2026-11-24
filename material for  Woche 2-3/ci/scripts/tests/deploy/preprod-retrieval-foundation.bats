#!/usr/bin/env bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
YAML="$REPO_ROOT/.gitlab/ci/deploy/preprod/deploy.yml"
QA_RETRIEVAL_YAML="$REPO_ROOT/.gitlab/ci/deploy/qa/retrieval-promotion.yml"
PREFLIGHT="$REPO_ROOT/.gitlab/ci/scripts/deploy/preflight-preprod-retrieval-foundation.sh"
DEPLOY="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-preprod-retrieval-foundation.sh"

_job_block() {
  awk -v key="$1:" '
    $0 == key {
      found = 1
    }
    found && $0 != key && /^[^[:space:]#][^:]*:$/ {
      exit
    }
    found {
      print
    }
  ' "$2"
}

@test "[#641 graph] foundation preflight gates one protected manual deployment" {
  grep -A18 '^preflight-retrieval-foundation:preprod:' "$YAML" |
    grep -q 'PIPELINE_TASK == "preprod-retrieval-foundation"'
  grep -A24 '^deploy-retrieval-foundation:preprod:' "$YAML" |
    grep -q 'job: preflight-retrieval-foundation:preprod'
  grep -A24 '^deploy-retrieval-foundation:preprod:' "$YAML" |
    grep -q 'resource_group: deploy-preprod'
  grep -A24 '^deploy-retrieval-foundation:preprod:' "$YAML" |
    grep -q 'name: deploy/preprod'
  grep -A24 '^deploy-retrieval-foundation:preprod:' "$YAML" |
    grep -q 'when: manual'
}

@test "[#641/#643 graph] pin merge starts the preflight; mutation still needs a human" {
  # #643 re-enables open-preprod-mr, and merging the preprod pin now starts the
  # zero-write preflight automatically (like qa). The safety property is NOT
  # "nothing is enabled" any more — it is "nothing mutates preprod without a
  # human", so assert the manual approval instead of a blanket when:never.
  _job_block open-preprod-mr "$QA_RETRIEVAL_YAML" | grep -q -- '- when: on_success'
  for job in validate-retrieval-promotion:preprod approve-preprod-promotion \
    preprod-retrieval-promotion; do
    _job_block "$job" "$YAML" >"$BATS_TEST_TMPDIR/job.txt"
    # both entry points present
    grep -q 'PIPELINE_TASK == "preprod-retrieval-promotion-development"' \
      "$BATS_TEST_TMPDIR/job.txt"
    grep -q 'deployments/preprod/version.yaml' "$BATS_TEST_TMPDIR/job.txt"
    # unrelated explicit tasks (rehearsal/health/retention/rollback) excluded
    grep -q 'if: \$PIPELINE_TASK' "$BATS_TEST_TMPDIR/job.txt"
    # closed by default
    grep -q -- '- when: never' "$BATS_TEST_TMPDIR/job.txt"
  done

  # The gate: approval is manual on BOTH entry paths and never on_success.
  _job_block approve-preprod-promotion "$YAML" >"$BATS_TEST_TMPDIR/approve.txt"
  [ "$(grep -c 'when: manual' "$BATS_TEST_TMPDIR/approve.txt")" -ge 2 ]
  ! grep -q 'when: on_success' "$BATS_TEST_TMPDIR/approve.txt"

  # legacy direct-deployment paths remain fully disabled
  _job_block cdk-deploy:preprod "$YAML" | grep -q -- '- when: never'
  _job_block cdk-deploy:preprod "$YAML" | grep -q 'when: manual'
  _job_block smoke-eval:preprod "$YAML" | grep -q -- '- when: never'

  ! _job_block cdk-deploy:preprod "$YAML" | grep -q 'when: on_success'
  ! _job_block smoke-eval:preprod "$YAML" | grep -q 'when: on_success'
}

@test "[#641 preflight] boundary probes are non-mutating or precondition-protected" {
  ! grep -q 'PRODUCTION_ACCESS_PROBE_ROLE_ARN' "$PREFLIGHT"
  ! grep -q 'ssm put-parameter' "$PREFLIGHT"
  ! grep -q 'cloudformation create-change-set' "$PREFLIGHT"
  ! grep -q 'bedrock-agent start-ingestion-job' "$PREFLIGHT"
  grep -q -- "--if-none-match '\\*'" "$PREFLIGHT"
  grep -q -- '--invocation-type DryRun' "$PREFLIGHT"
  ! grep -q 'cdk diff' "$PREFLIGHT"
  grep -q 'CFN_DEPLOY_ROLE=.*cdk-hnb659fds-deploy-role' "$PREFLIGHT"
  grep -q 'ECR_IMAGE_ROLE=.*cdk-hnb659fds-image-publishing-role' "$PREFLIGHT"
  grep -q -- '--image-ids "imageTag=${tag}"' "$PREFLIGHT"
  [ "$(grep -c '^cloudformation_get_template ' "$PREFLIGHT")" -eq 2 ]
  grep -q 'preprod-foundation-absent-probe' "$PREFLIGHT"
  grep -q 'Legacy preprod chatbot has no maintenance KVS' "$PREFLIGHT"
  grep -q 'iam simulate-principal-policy' "$PREFLIGHT"
  grep -q 'cloudfront-keyvaluestore:UpdateKeys' "$PREFLIGHT"
  grep -q 'lambda:PutFunctionConcurrency' "$PREFLIGHT"
  grep -q 'lambda:DeleteFunctionConcurrency' "$PREFLIGHT"
  grep -q 'explicitDeny | implicitDeny' "$PREFLIGHT"
  ! grep -q 'cloudfront-keyvaluestore update-keys' "$PREFLIGHT"
  grep -q 'preprod-foundation-diff.mjs" prepare' "$PREFLIGHT"
  grep -q 'preprod-foundation-diff-summary.json' "$PREFLIGHT"
}

@test "[#641 preflight] local diagnostics use SSO profiles without claiming OIDC denials" {
  grep -q 'FOUNDATION_LOCAL_MODE' "$PREFLIGHT"
  grep -q 'FOUNDATION_QA_PROFILE:-digibro-eu-qa' "$PREFLIGHT"
  grep -q 'FOUNDATION_PREPROD_PROFILE:-digibro-eu-pp' "$PREFLIGHT"
  grep -q 'FOUNDATION_DEV_PROFILE:-digibro-eu-dev' "$PREFLIGHT"
  grep -q 'CI-only OIDC authorization check skipped in local diagnostic mode' "$PREFLIGHT"
  grep -q 'local diagnostic mode is not allowed in CI' "$PREFLIGHT"
}

@test "[#641 drift] transient Lambda lifecycle state is not configuration drift" {
  for script in "$PREFLIGHT" "$DEPLOY"; do
    grep -q 'stable_lambda_config_sha' "$script"
    grep -q '\.StateReasonCode' "$script"
    grep -q '\.LastUpdateStatusReasonCode' "$script"
  done
  grep -q 'CHATBOT_CONFIG_SHA="$(stable_lambda_config_sha "\$CHATBOT_CONFIG")"' \
    "$PREFLIGHT"
  grep -q 'stable_lambda_config_sha "\${TMP_DIR}/chatbot-config-after.json"' \
    "$DEPLOY"
}

@test "[#641 verification] complete paginated stack resource lists are compared" {
  grep -q 'cloudformation list-stack-resources' "$PREFLIGHT"
  grep -q 'cloudformation list-stack-resources' "$DEPLOY"
  grep -q '\.StackResourceSummaries\[\]' "$PREFLIGHT"
  grep -q '\.StackResourceSummaries\[\]' "$DEPLOY"
  ! grep -q 'cloudformation describe-stack-resources' "$PREFLIGHT"
  ! grep -q 'cloudformation describe-stack-resources' "$DEPLOY"
}

@test "[#641 verification] an empty S3 response counts as zero objects" {
  grep -Fq "jq '(.Contents // []) | length'" "$DEPLOY"
  ! grep -q -- '--query KeyCount' "$DEPLOY"
}

@test "[#641 deploy] reviewed additive assembly deploys only the ETL stack" {
  grep -q 'ASSEMBLY_DIR="\${EVIDENCE_DIR}/cdk.out"' "$DEPLOY"
  grep -q 'npx cdk deploy --app "\$ASSEMBLY_DIR" "\$ETL_STACK"' "$DEPLOY"
  grep -q -- '--exclusively' "$DEPLOY"
  ! grep -q 'npx cdk synth' "$DEPLOY"
  ! grep -q 'cdk deploy.*chatbot' "$DEPLOY"
  ! grep -q 'ssm put-parameter' "$DEPLOY"
}

@test "[#641 scripts] shell entrypoints are syntactically valid" {
  run bash -n "$PREFLIGHT"
  [ "$status" -eq 0 ]
  run bash -n "$DEPLOY"
  [ "$status" -eq 0 ]
}
