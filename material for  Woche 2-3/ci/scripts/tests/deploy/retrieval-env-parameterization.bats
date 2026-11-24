#!/usr/bin/env bats
# #643 — prove the generalized retrieval code resolves each environment's
# coordinates from retrieval-environment.mjs (qa stays byte-identical; preprod
# resolves the preprod stacks/selectors/roles/namespace). No AWS: exercises
# qa_retrieval_init_env and the env-parameterized entry-script arg handling.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
LIB="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval.sh"
PREPARE="$REPO_ROOT/.gitlab/ci/scripts/deploy/prepare-retrieval-promotion.sh"

@test "[#643 init] preprod resolves preprod selectors/stacks/roles/namespace/mode" {
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env preprod
    printf "%s\n" "$RETRIEVAL_ACTIVE_SELECTOR" "$RETRIEVAL_PREVIOUS_SELECTOR" \
      "$RETRIEVAL_ETL_STACK" "$RETRIEVAL_CHATBOT_STACK" \
      "$RETRIEVAL_PROMOTION_ROLE_ARN" "$RETRIEVAL_SOURCE_READER_ROLE_ARN" \
      "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN" "$RETRIEVAL_METRIC_NAMESPACE" \
      "$RETRIEVAL_RESOURCE_GROUP" "$RETRIEVAL_RAW_SOURCE_MODE" \
      "$RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER" "$RETRIEVAL_HEALTH_STATE_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/preprod/renate/retrieval/active-manifest"* ]]
  [[ "$output" == *"/preprod/renate/retrieval/previous-manifest"* ]]
  [[ "$output" == *"renate-etl-kb-preprod"* ]]
  [[ "$output" == *"renate-chatbot-preprod"* ]]
  [[ "$output" == *"ki-lab-digibro-preprod-retrieval-promotion"* ]]
  [[ "$output" == *"ki-lab-digibro-qa-retrieval-source-reader"* ]]
  [[ "$output" == *"ki-lab-digibro-dev-retrieval-reader"* ]]
  [[ "$output" == *"Renate/Preprod/Retrieval"* ]]
  [[ "$output" == *"deploy-preprod"* ]]
  [[ "$output" == *"downstream"* ]]
  [[ "$output" == *"/preprod/renate/retrieval/rollback-degraded"* ]]
  [[ "$output" == *"/preprod/renate/retrieval/health-check-state"* ]]
}

@test "[#726 init] prod resolves prod selectors/stacks/roles/namespace/mode" {
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env prod
    printf "%s\n" "$RETRIEVAL_ACTIVE_SELECTOR" "$RETRIEVAL_PREVIOUS_SELECTOR" \
      "$RETRIEVAL_ETL_STACK" "$RETRIEVAL_CHATBOT_STACK" \
      "$RETRIEVAL_PROMOTION_ROLE_ARN" "$RETRIEVAL_SOURCE_READER_ROLE_ARN" \
      "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN" "$RETRIEVAL_METRIC_NAMESPACE" \
      "$RETRIEVAL_RESOURCE_GROUP" "$RETRIEVAL_RAW_SOURCE_MODE" \
      "$RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER" "$RETRIEVAL_HEALTH_STATE_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/prod/renate/retrieval/active-manifest"* ]]
  [[ "$output" == *"/prod/renate/retrieval/previous-manifest"* ]]
  [[ "$output" == *"renate-etl-kb-prod"* ]]
  [[ "$output" == *"renate-chatbot-prod"* ]]
  [[ "$output" == *"ki-lab-digibro-prod-retrieval-promotion"* ]]
  [[ "$output" == *"ki-lab-digibro-qa-retrieval-source-reader"* ]]
  [[ "$output" == *"ki-lab-digibro-dev-retrieval-reader"* ]]
  [[ "$output" == *"Renate/Prod/Retrieval"* ]]
  [[ "$output" == *"deploy-prod"* ]]
  [[ "$output" == *"downstream"* ]]
  [[ "$output" == *"/prod/renate/retrieval/rollback-degraded"* ]]
  [[ "$output" == *"/prod/renate/retrieval/health-check-state"* ]]
}

@test "[#726 init] prod resolves qa as its upstream (dev → qa → prod chain, parallel to preprod)" {
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env prod
    printf "%s\n" "$RETRIEVAL_UPSTREAM_ENVIRONMENT" \
      "$RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa"* ]]
  [[ "$output" == *"/qa/renate/etl-source-bucket-name"* ]]
}

@test "[#643 init] qa resolves byte-identical legacy /qa/ coordinates" {
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env qa
    printf "%s\n" "$RETRIEVAL_ACTIVE_SELECTOR" "$RETRIEVAL_ETL_STACK" \
      "$RETRIEVAL_CHATBOT_STACK" "$RETRIEVAL_METRIC_NAMESPACE" \
      "$RETRIEVAL_RESOURCE_GROUP" "$RETRIEVAL_RAW_SOURCE_MODE" \
      "$RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/qa/renate/retrieval/active-manifest"* ]]
  [[ "$output" == *"renate-etl-kb-qa"* ]]
  [[ "$output" == *"renate-chatbot-qa"* ]]
  [[ "$output" == *"Renate/QA/Retrieval"* ]]
  [[ "$output" == *"deploy-qa"* ]]
  [[ "$output" == *"origin"* ]]
  [[ "$output" == *"/qa/renate/retrieval/rollback-degraded"* ]]
}

@test "[#643 init] unknown environment fails closed before any resolution" {
  run env REPO_ROOT="$REPO_ROOT" bash -c 'source "$1"; qa_retrieval_init_env bogus' _ "$LIB"
  [ "$status" -ne 0 ]
}

@test "[#643 init] preprod resolves its upstream and the parameter naming its bucket" {
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env preprod
    printf "%s\n" "$RETRIEVAL_UPSTREAM_ENVIRONMENT" \
      "$RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"qa"* ]]
  [[ "$output" == *"/qa/renate/etl-source-bucket-name"* ]]
}

@test "[#643 init] qa (origin) carries no upstream of record" {
  # Origin mode must not name an upstream: qa resolves its own bucket, and dev
  # is a non-authoritative fallback, not a durable source of record.
  run env REPO_ROOT="$REPO_ROOT" bash -c '
    source "$1"; qa_retrieval_init_env qa
    printf "[%s][%s]\n" "$RETRIEVAL_UPSTREAM_ENVIRONMENT" \
      "$RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER"
  ' _ "$LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[][]"* ]]
}

@test "[#643 init] a downstream env declaring no upstream parameter fails closed" {
  # A downstream promotion that cannot resolve its upstream must refuse, never
  # fall back to guessing a bucket name.
  TMP="$(mktemp -d)"
  mkdir -p "$TMP/.gitlab/ci/scripts/lib/node"
  cat >"$TMP/.gitlab/ci/scripts/lib/node/retrieval-environment.mjs" <<'STUB'
const c = {
  environment: 'preprod', accountId: '1', sourceAccountId: '2',
  sourceReaderRoleArn: 'arn:r', imageMetadataReaderRoleArn: 'arn:m',
  imageMetadataAccountId: '3', rawSourceMode: 'downstream',
  upstreamEnvironment: null, upstreamSourceBucketParameter: null,
  promotionRoleArn: 'arn:p', etlStackName: 'e', chatbotStackName: 'c',
  retrievalBasePath: '/p', activeSelector: '/a', previousSelector: '/pr',
  healthStateParameter: '/h', rollbackDegradedParameter: '/d',
  artifactPrefix: 'x', metricNamespace: 'N', resourceGroup: 'g',
};
process.stdout.write(JSON.stringify(c) + '\n');
STUB
  run env REPO_ROOT="$TMP" bash -c 'source "$1"; qa_retrieval_init_env preprod' _ "$LIB"
  rm -rf "$TMP"
  [ "$status" -ne 0 ]
  [[ "$output" == *"downstream but declares no upstreamEnvironment"* ]]
}

@test "[#643 candidate] downstream discovers the upstream bucket in-entitlement, not from CI" {
  CANDIDATE="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
  # No hand-maintained bucket name anywhere in the promotion implementation.
  ! grep -rq 'UPSTREAM_SOURCE_BUCKET:' "$REPO_ROOT/.gitlab/ci/deploy/preprod/"
  ! grep -q 'UPSTREAM_SOURCE_BUCKET:?' "$CANDIDATE"
  # The name is read from the upstream's own parameter with the same role that
  # entitles the corpus read, so discovery cannot exceed the entitlement.
  downstream_block="$(awk '/RETRIEVAL_RAW_SOURCE_MODE.*== downstream/,/^  else$/' "$CANDIDATE")"
  grep -q 'qa_retrieval_assume_oidc "\$RETRIEVAL_SOURCE_READER_ROLE_ARN"' <<<"$downstream_block"
  grep -q 'RETRIEVAL_UPSTREAM_SOURCE_BUCKET_PARAMETER' <<<"$downstream_block"
  # Fail closed, with the bootstrap grant named for the operator.
  grep -q 'retrieval_source_reader.tf' <<<"$downstream_block"
}

@test "[#643 prepare] preprod prepare validates the preprod pin and derives a release id" {
  TMP="$(mktemp -d)"
  mkdir -p "$TMP/bin"
  printf 'version: 1.83.3\ndata_artifact_version: v1.83.3-preprod-blue-baseline\netl_version: v1.83.3-preprod-blue-baseline\n' >"$TMP/pin.yaml"
  # preprod is a downstream env, so prepare resolves the qa-attested commit from
  # the qa-deployed tag (#660); stub git so ls-remote returns a sha to parse
  # (the overlay itself is covered by retrieval-implementation-attestation.bats).
  cat >"$TMP/bin/git" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *ls-remote* ]]; then
  printf '%s\trefs/tags/stub\n' 1111111111111111111111111111111111111111
fi
exit 0
EOF
  chmod +x "$TMP/bin/git"
  PATH="$TMP/bin:$PATH" run "$PREPARE" preprod "$TMP/pin.yaml" "$TMP/out.env"
  [ "$status" -eq 0 ]
  grep -q '^CHATBOT_VERSION=1.83.3$' "$TMP/out.env"
  grep -q '^DATA_ARTIFACT_VERSION=v1.83.3-preprod-blue-baseline$' "$TMP/out.env"
  grep -q '^RELEASE_ID=sha256-' "$TMP/out.env"
  rm -rf "$TMP"
}

@test "[#643 parity] every entry script is env-parameterized, with no qa literals" {
  # A rename without its content change would leave a qa-literal script serving
  # preprod — writing QA's selectors during a preprod promotion. Assert the
  # generalization itself, not just that the file exists.
  for s in deploy/prepare-retrieval-promotion deploy/deploy-retrieval-candidate \
    deploy/deploy-retrieval-chatbot deploy/activate-retrieval \
    ops/rollback-retrieval; do
    script="$REPO_ROOT/.gitlab/ci/scripts/${s}.sh"
    echo "checking $s"
    [ -x "$script" ]
    # takes <env> and resolves coordinates from the shared config
    grep -qE 'ENV="\$\{1' "$script"
    grep -q 'qa_retrieval_init_env' "$script"
    # carries no hardcoded qa stack, selector path, or qa-only role variable
    ! grep -qE 'renate-chatbot-qa|renate-etl-kb-qa|"/qa/renate|QA_RETRIEVAL_PROMOTION_ROLE_ARN:\?' "$script"
  done
}

@test "[#643 args] entry scripts reject a missing environment argument" {
  # Paths are asserted to exist first: a non-existent path also exits non-zero
  # (127), which would let this test pass without ever reaching the argument
  # check it exists to prove.
  for s in deploy/prepare-retrieval-promotion deploy/deploy-retrieval-candidate \
    deploy/deploy-retrieval-chatbot deploy/activate-retrieval \
    ops/rollback-retrieval; do
    script="$REPO_ROOT/.gitlab/ci/scripts/${s}.sh"
    echo "checking $script"
    [ -x "$script" ]
    run "$script"
    [ "$status" -ne 0 ]
    [ "$status" -ne 127 ]
    echo "output was: $output"
    # The refusal must name the environments it accepts, so an operator learns
    # the contract from the failure itself.
    [[ "$output" == *"qa"* && "$output" == *"preprod"* && "$output" == *"prod"* ]]
  done
}

@test "[#643 preflight] image recoverability covers incoming AND outgoing, before mutation" {
  CANDIDATE="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
  # Both directions: incoming or the transaction dies after mutation; outgoing or
  # a #493 selector-flip rollback restores a manifest whose image was reaped.
  grep -q 'incoming chatbot' "$CANDIDATE"
  grep -q 'incoming ETL' "$CANDIDATE"
  grep -q 'outgoing chatbot' "$CANDIDATE"
  grep -q 'outgoing ETL' "$CANDIDATE"
  # Must run before the first live mutation, so the dry-run preflight covers it
  # too and it repeats under the lock.
  recover_line=$(grep -n 'Verify image recoverability' "$CANDIDATE" | head -1 | cut -d: -f1)
  dryrun_line=$(grep -n 'DRY_RUN" == true' "$CANDIDATE" | head -1 | cut -d: -f1)
  deploy_line=$(grep -n 'npx cdk deploy' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ "$recover_line" -lt "$dryrun_line" ]
  [ "$recover_line" -lt "$deploy_line" ]
  # Digest-based, not tag-based: tags can be reassigned, digests cannot. The
  # same checked values are passed directly to CDK.
  grep -q 'imageDigest=' "$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval-auth.sh"
  grep -Fq 'etlImageTag=${ETL_IMAGE_DIGEST}' "$CANDIDATE"
  grep -Fq 'chatbotImageTag=${CHATBOT_IMAGE_DIGEST}' "$CANDIDATE"
}

@test "[#643 preflight] the dry-run synthesizes both stacks with the real contexts" {
  CANDIDATE="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
  block=$(awk '/DRY_RUN" == true/,/^  fi$/' "$CANDIDATE")
  grep -q 'npx cdk synth' <<<"$block"
  # The exact contexts the real deploys pass, or the check proves nothing.
  for ctx in 'env=' 'etlImageTag=' 'retrievalCandidateSlot=' 'blueEtlImageTag=' \
    'greenEtlImageTag=' 'chatbotImageTag='; do
    grep -q "$ctx" <<<"$block"
  done
  # Zero-write: a preflight must not deploy.
  ! grep -q 'cdk deploy' <<<"$block"
}
