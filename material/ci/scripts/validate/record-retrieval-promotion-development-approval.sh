#!/usr/bin/env bash
# #643/#670 — Record the explicit single-operator development policy used by
# the manual downstream promotion gates.
#
# This script deliberately makes no authorization or identity claim from CI
# variables. Pipeline/manual variables can override predefined variables on
# this GitLab instance, so values such as GITLAB_USER_LOGIN, CI_PROJECT_ID, and
# CI_API_V4_URL are not a trustworthy security boundary. In particular, no API
# token is sent to a variable-controlled URL.
#
# The caller must hard-code both the environment and policy as positional
# arguments in reviewed repository YAML. GitLab's manual job and deployment
# records remain the authoritative record of who played the gate. The artifact
# produced here records the reviewed policy and links to those server-side
# records; it is evidence, not an authorization mechanism.
set -euo pipefail

fail() {
  echo "retrieval-promotion-development-approval: $*" >&2
  exit 1
}

environment="${1:-}"
policy="${2:-}"

case "$environment" in
  preprod | prod) ;;
  *) fail "expected environment 'preprod' or 'prod'" ;;
esac

[[ "$policy" == "development-single-operator" ]] || fail \
  "expected the reviewed policy argument 'development-single-operator'"

evidence_file="${APPROVAL_EVIDENCE_FILE:-${environment}-retrieval-promotion-approval.json}"
recorded_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n \
  --arg environment "$environment" \
  --arg policy "$policy" \
  --arg recorded_at "$recorded_at" \
  --arg pipeline_url "${CI_PIPELINE_URL:-}" \
  --arg job_url "${CI_JOB_URL:-}" '
    {
      schema_version: 1,
      environment: $environment,
      policy: $policy,
      recorded_at: $recorded_at,
      audit_authority: "gitlab-manual-job-and-deployment-record",
      pipeline_url: ($pipeline_url | if length > 0 then . else null end),
      job_url: ($job_url | if length > 0 then . else null end),
      identity_claimed_by_artifact: false,
      four_eyes_claimed: false
    }
  ' >"$evidence_file"

echo "retrieval-promotion-development-approval: DEVELOPMENT MODE — one operator may approve this ${environment} promotion."
echo "retrieval-promotion-development-approval: Four-eyes separation is intentionally not claimed."
echo "retrieval-promotion-development-approval: The GitLab manual-job/deployment record is the authoritative operator audit."
echo "retrieval-promotion-development-approval: Evidence written to ${evidence_file}."
