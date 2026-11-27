#!/usr/bin/env bats
# TKT-RO-03: candidate deployment changes an inactive slot, but its recovery
# path is what protects the live retrieval service when a later step fails.
# shellcheck disable=SC2016

bats_require_minimum_version 1.5.0

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
SCRIPT="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  TEST_SCRIPT="$TEST_DIR/deploy-retrieval-candidate.sh"
  sed 's/\r$//' "$SCRIPT" >"$TEST_SCRIPT"
}

teardown() { rm -rf "$TEST_DIR"; }

@test "[deploy-retrieval-candidate] rejects extra arguments before credentials" {
  run bash "$TEST_SCRIPT" qa --unexpected
  [ "$status" -eq 2 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "[deploy-retrieval-candidate] assumes promotion role before image metadata reader" {
  promotion=$(grep -nF 'qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN"' "$SCRIPT" | head -1 | cut -d: -f1)
  metadata=$(grep -nF 'qa_retrieval_assume_oidc "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN"' "$SCRIPT" | head -1 | cut -d: -f1)
  [ "$promotion" -lt "$metadata" ]
  grep -Fq 'qa_retrieval_assume_oidc "$RETRIEVAL_PROMOTION_ROLE_ARN" "$ENV"' "$SCRIPT"
  grep -Fq 'qa_retrieval_assume_oidc "$RETRIEVAL_IMAGE_METADATA_READER_ROLE_ARN" image-metadata' "$SCRIPT"
}

@test "[deploy-retrieval-candidate] recovery requires unchanged selectors and restores the inactive corpus" {
  grep -Fq 'qa_retrieval_assert_selectors_unchanged' "$SCRIPT"
  grep -Fq 'qa_retrieval_restore_immutable_corpus' "$SCRIPT"
  grep -Fq 'qa_retrieval_clear_rollback_degraded_marker' "$SCRIPT"
  grep -Fq 'CANDIDATE_LIVE_MUTATED' "$SCRIPT"
}

@test "[deploy-retrieval-candidate] dry-run remains a supported non-mutating entrypoint" {
  grep -Fq 'DRY_RUN=true' "$SCRIPT"
  grep -Fq -- '--dry-run' "$SCRIPT"
  grep -Fq 'TMP_DIR=$(mktemp -d)' "$SCRIPT"
}