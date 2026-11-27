#!/usr/bin/env bash
# #631 D4 — lint that the QA source bucket has exactly one class of writer:
# jobs serialized under `resource_group: deploy-qa` (directly, or as a child
# of a `trigger` job that holds the lock via `strategy: mirror`). This is
# defense-in-depth for the KNOWN CI topology, not a complete guarantee — the
# real single-writer guarantee is IAM (only the
# ki-lab-digibro-qa-retrieval-promotion role can write the bucket). A future
# writer using an unlisted script name or a raw `aws s3` call is not caught by
# this grep-based check; extend WRITER_SCRIPT_TOKENS below when adding one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"

RETRIEVAL_PROMOTION_YAML_BASENAME="retrieval-promotion.yml"
QA_DEPLOY_YAML="${REPO_ROOT}/.gitlab/ci/deploy/qa/deploy.yml"

# Scripts that write the QA source bucket. A job invoking one of these is a
# writer and must either declare `resource_group: deploy-qa` itself, or be a
# job inside retrieval-promotion.yml (which is only ever reachable through a
# mirrored deploy-qa trigger — checked separately by check_rule1).
WRITER_SCRIPT_TOKENS=(
  "deploy-retrieval-candidate.sh"
)

# Trigger jobs in deploy.yml that include retrieval-promotion.yml but are
# explicitly read-only (their included pipeline never performs a live QA
# write, because deploy-retrieval-candidate.sh's own --dry-run stops
# before any QA mutation) and therefore do not need the lock.
EXEMPT_TRIGGER_JOBS=(
  "qa-retrieval-promotion-rehearsal"
)

fail() {
  echo "lint-qa-source-writers: $*" >&2
  exit 1
}

# Top-level job names (unindented "name:" lines, in order) from a GitLab CI
# YAML file. Hidden/template jobs (leading '.') are skipped by callers as
# needed, not here, since some checks legitimately want them (none currently
# do).
_job_names() {
  grep -E '^[A-Za-z][A-Za-z0-9_.:-]*:$' "$1" | sed 's/:$//'
}

# Print the body of job `$1`'s block in file `$2` (from its own line, up to
# but excluding the next top-level key).
_job_block() {
  local job="$1" file="$2"
  awk -v job="^${job}:\$" '
    $0 ~ job { infile=1; next }
    infile && /^[A-Za-z][A-Za-z0-9_.:-]*:$/ { exit }
    infile { print }
  ' "$file"
}

# ── Rule 1: every job in deploy.yml that triggers retrieval-promotion.yml
# (the writer pipeline) is either locked with resource_group: deploy-qa, or
# explicitly allowlisted as read-only. ───────────────────────────────────────
check_rule1() {
  local job block is_exempt exempt

  while IFS= read -r job; do
    [[ -n "$job" ]] || continue
    block=$(_job_block "$job" "$QA_DEPLOY_YAML")
    grep -q "$RETRIEVAL_PROMOTION_YAML_BASENAME" <<<"$block" || continue

    is_exempt=false
    for exempt in "${EXEMPT_TRIGGER_JOBS[@]}"; do
      [[ "$job" == "$exempt" ]] && is_exempt=true
    done
    [[ "$is_exempt" == true ]] && continue

    grep -q 'resource_group: *deploy-qa' <<<"$block" || \
      fail "job '${job}' triggers ${RETRIEVAL_PROMOTION_YAML_BASENAME} (a QA-source-bucket" \
        "writer pipeline) without 'resource_group: deploy-qa' and is not in" \
        "the exempt read-only allowlist (EXEMPT_TRIGGER_JOBS)"
  done < <(_job_names "$QA_DEPLOY_YAML")
}

# ── Rule 2: any job OUTSIDE retrieval-promotion.yml that invokes a writer
# script must declare its own resource_group: deploy-qa — it has no mirrored
# parent trigger to inherit the lock from. (Jobs INSIDE
# retrieval-promotion.yml are covered transitively by rule 1: that file is
# only ever reached through a deploy-qa-locked or exempt-read-only trigger.) ─
check_rule2() {
  local job block token

  while IFS= read -r job; do
    [[ -n "$job" ]] || continue
    [[ "$job" == .* ]] && continue
    block=$(_job_block "$job" "$QA_DEPLOY_YAML")
    for token in "${WRITER_SCRIPT_TOKENS[@]}"; do
      grep -q -- "$token" <<<"$block" || continue
      grep -q 'resource_group: *deploy-qa' <<<"$block" || \
        fail "job '${job}' in $(basename "$QA_DEPLOY_YAML") invokes the" \
          "QA-source-bucket writer '${token}' without" \
          "'resource_group: deploy-qa'"
    done
  done < <(_job_names "$QA_DEPLOY_YAML")
}

check_rule1
check_rule2
echo "lint-qa-source-writers: OK (retrieval-promotion.yml triggers locked;" \
  "no unguarded QA-source-bucket writer found in $(basename "$QA_DEPLOY_YAML"))"
