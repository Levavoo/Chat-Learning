#!/usr/bin/env bats
# #669 — offline safety contracts for the one-time workstation prod seed.
# No AWS calls: these tests prove argument gates and structural ordering around
# the operator-only mutation path.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SEED="$REPO_ROOT/scripts/seed-blue-baseline.sh"
ACTIVATE="$REPO_ROOT/scripts/activate-blue-baseline-selector.sh"
PREPROD_WRAPPER="$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-preprod-blue-baseline.sh"

_first_line() {
  grep -nF -- "$2" "$1" | head -1 | cut -d: -f1
}

@test "[#669] operator scripts are syntactically valid" {
  run bash -n "$SEED" "$ACTIVATE" "$PREPROD_WRAPPER"
  [ "$status" -eq 0 ]
}

@test "[#669] seed accepts only explicit prod + pin input" {
  run "$SEED"
  [ "$status" -eq 2 ]
  [[ "$output" == *"--env prod"* ]]
  [[ "$output" == *"--pin-file"* ]]

  run "$SEED" --env preprod --pin-file x
  [ "$status" -eq 2 ]
  [[ "$output" == *"seeds only --env prod"* ]]
}

@test "[#669] seed and prod activation refuse CI/OIDC before AWS" {
  CI=true run "$SEED" --env prod --pin-file "$REPO_ROOT/deployments/prod/version.yaml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"operator workstation"* ]]

  CI=true run "$ACTIVATE" --env prod --pin-file "$REPO_ROOT/deployments/prod/version.yaml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"operator workstation"* ]]
}

@test "[#669] selector activation has prod profile and no hardcoded baseline version" {
  grep -F 'prod)    PROFILE="${PROD_PROFILE:-renate-prod}"' "$ACTIVATE"
  grep -F -- '--pin-file' "$ACTIVATE"
  grep -F 'promotion_pin_value "$PIN_FILE" version' "$ACTIVATE"
  ! grep -q 'VERSION="1\.83\.3"' "$ACTIVATE"
  grep -F 'lib/node/retrieval-release.mjs' "$ACTIVATE"
  grep -F 'lib/node/retrieval-environment.mjs' "$ACTIVATE"
  grep -F 'lib/node/release-retention.mjs' "$ACTIVATE"
}

@test "[#669] historical preprod activation passes its coordinates explicitly" {
  grep -F -- '--version 1.83.3' "$PREPROD_WRAPPER"
  grep -F -- '--data-artifact-version v1.83.3-preprod-blue-baseline' "$PREPROD_WRAPPER"
  grep -F -- '--etl-version v1.83.3-preprod-blue-baseline' "$PREPROD_WRAPPER"
}

@test "[#669] seed binds the prod pin to current QA pin and active selector" {
  grep -F 'cmp -s "$PIN_FILE" "$QA_PIN"' "$SEED"
  grep -F '/qa/renate/retrieval/active-manifest' "$SEED"
  grep -F '.release_id == $release' "$SEED"
  grep -F 'qa_retrieval_composite_manifest_complete' "$SEED"
}

@test "[#669] QA access is read-only and prod writes use the prod profile" {
  ! grep -Eq 'qa_aws (s3api (put|copy|delete)|s3 rm|ssm put|lambda update)' "$SEED"
  grep -F 'qa_aws s3 sync "s3://${QA_SOURCE_BUCKET}/${BROCHURE_PREFIX}"' "$SEED"
  grep -F 'qa_aws s3 sync "s3://${QA_SOURCE_BUCKET}/${FAQ_PREFIX}"' "$SEED"
  grep -F 'prod_aws s3 rm "s3://${BLUE_PROCESSED_BUCKET}/docs/"' "$SEED"
  grep -F 'AWS_PROFILE="$PROD_PROFILE"' "$SEED"
}

@test "[#669] dry run exits before every AWS mutation" {
  dry_exit=$(_first_line "$SEED" 'if [ "$EXECUTE" != true ]; then')
  cdk_deploy=$(_first_line "$SEED" 'npx cdk deploy "$ETL_STACK"')
  live_delete=$(_first_line "$SEED" 'prod_aws s3 rm "s3://${BLUE_PROCESSED_BUCKET}/docs/"')
  raw_write=$(_first_line "$SEED" 'prod_shared qa_retrieval_put_write_once "$TARGET_SOURCE_BUCKET"')
  [ "$dry_exit" -lt "$cdk_deploy" ]
  [ "$dry_exit" -lt "$live_delete" ]
  [ "$dry_exit" -lt "$raw_write" ]
  [ "$(grep -c -- '--method=template' "$SEED")" -eq 2 ]
  ! grep -Eq '^[[:space:]]+--strict([[:space:]\\]|$)' "$SEED"
}

@test "[#669] seed builds schema-v2 blue without a chatbot claim" {
  manifest_block=$(sed -n '/jq -n \\/,/retrieval-manifest.json/p' "$SEED")
  [[ "$manifest_block" == *"schema_version:2"* ]]
  [[ "$manifest_block" == *'processed_prefix:$processed_prefix'* ]]
  [[ "$manifest_block" == *'etl_image_digest:$etl_digest'* ]]
  [[ "$manifest_block" != *"chatbot_image_digest"* ]]
}

@test "[#669] blue/transform advance while green digest is preserved" {
  grep -F 'retrievalCandidateSlot=blue' "$SEED"
  grep -F 'blueEtlImageTag=${ETL_IMAGE_DIGEST}' "$SEED"
  grep -F 'greenEtlImageTag=${GREEN_ETL_IMAGE_COORDINATE}' "$SEED"
  grep -F 'preserved green coordinate ${GREEN_ETL_IMAGE_COORDINATE}' "$SEED"
  grep -F '[ "${GREEN_DEPLOYED_URI##*@}" = "$GREEN_ETL_IMAGE_DIGEST" ]' "$SEED"
  grep -F 'cloudformation get-template' "$SEED"
  ! grep -F '/${ENV_NAME}/renate/etl-image-tag' "$SEED"
}

@test "[#669] SourceReprocess discovery uses the complete paginated stack listing" {
  grep -F 'cloudformation list-stack-resources' "$SEED"
  grep -F 'SourceReprocessTriggerReprocessFunction' "$SEED"
  grep -F 'StackResourceSummaries[]' "$SEED"
  ! grep -F 'cloudformation describe-stack-resources' "$SEED"
  ! grep -F -- "--query \"StackResourceSummaries" "$SEED"
}

@test "[#669] seed never writes selectors and activation creates active only" {
  ! grep -F 'ssm put-parameter' "$SEED"
  grep -F 'aws ssm put-parameter --name "$ACTIVE_SELECTOR"' "$ACTIVATE"
  ! grep -F 'aws ssm put-parameter --name "$PREVIOUS_SELECTOR"' "$ACTIVATE"
}

@test "[#669] retention, read-back, and clean final diff are mandatory" {
  [ "$(grep -c 'node "$RELEASE_RETENTION" pin' "$SEED")" -eq 2 ]
  [ "$(grep -c 'node "$RELEASE_RETENTION" audit' "$SEED")" -eq 2 ]
  grep -F 'qa_retrieval_verify_immutable_corpus' "$SEED"
  grep -F 'cmp -s "$TMP_DIR/retrieval-manifest.json" "$TMP_DIR/readback-manifest.json"' "$SEED"
  grep -F -- '--fail' "$SEED"
  grep -F 'selectors:{active:"absent",previous:"absent"}' "$SEED"
  grep -F -- '--managed-prefix "$BROCHURE_PREFIX"' "$ACTIVATE"
  grep -F -- '--managed-prefix "$FAQ_PREFIX"' "$ACTIVATE"
}
