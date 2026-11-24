#!/usr/bin/env bash
# QA retrieval manifest, selector, and marker validation helpers.

# shellcheck source=qa-retrieval-common.sh disable=SC1091
source "${BASH_SOURCE[0]%/*}/qa-retrieval-common.sh"

qa_retrieval_optional_ssm() {
  local name="$1" error_file value
  error_file=$(mktemp)
  if value=$(aws ssm get-parameter --name "$name" \
      --query Parameter.Value --output text 2>"$error_file"); then
    rm -f "$error_file"
    printf '%s\n' "$value"
    return 0
  fi
  if grep -q ParameterNotFound "$error_file"; then
    rm -f "$error_file"
    return 1
  fi
  cat "$error_file" >&2
  rm -f "$error_file"
  qa_retrieval_fail "could not read SSM parameter ${name}"
}

qa_retrieval_capture_selector() {
  local name="$1" output="$2" value
  if value=$(qa_retrieval_optional_ssm "$name"); then
    printf '%s\n' "$value" >"$output"
  else
    : >"$output"
  fi
}

qa_retrieval_validate_manifest() {
  local manifest="$1"
  node "${REPO_ROOT}/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" validate "$manifest"
}

qa_retrieval_assert_selectors_unchanged() {
  local active_before="$1" previous_before="$2" active_now previous_now
  : "${RETRIEVAL_ACTIVE_SELECTOR:?qa_retrieval_init_env must run before qa_retrieval_assert_selectors_unchanged}"
  active_now=$(mktemp)
  previous_now=$(mktemp)
  qa_retrieval_capture_selector "$RETRIEVAL_ACTIVE_SELECTOR" "$active_now"
  qa_retrieval_capture_selector "$RETRIEVAL_PREVIOUS_SELECTOR" "$previous_now"
  cmp -s "$active_before" "$active_now" || {
    rm -f "$active_now" "$previous_now"
    qa_retrieval_fail "active retrieval selector changed during candidate preparation"
    return 1
  }
  cmp -s "$previous_before" "$previous_now" || {
    rm -f "$active_now" "$previous_now"
    qa_retrieval_fail "previous retrieval selector changed during candidate preparation"
    return 1
  }
  rm -f "$active_now" "$previous_now"
}

# Resolve the QA chat Lambda whose RETRIEVAL_MANIFEST_PARAMETER env var equals
# the given selector name. Shared by activation and rollback so both scripts
# invoke the same diagnostic path against the same function.
qa_retrieval_resolve_chat_function() {
  local stack_name="$1" selector_name="$2" function_name selector
  local function_names
  # Captured before the loop, not piped from a process substitution, so a
  # listing failure fails closed instead of degrading into "no match".
  function_names=$(qa_retrieval_stack_lambda_functions "$stack_name") || return 1
  while IFS= read -r function_name; do
    [[ -n "$function_name" ]] || continue
    selector=$(aws lambda get-function-configuration --function-name "$function_name" \
      --query 'Environment.Variables.RETRIEVAL_MANIFEST_PARAMETER' --output text 2>/dev/null || true)
    if [[ "$selector" == "$selector_name" ]]; then
      printf '%s\n' "$function_name"
      return 0
    fi
  done < <(printf '%s\n' "$function_names")
  qa_retrieval_fail "could not resolve QA chat Lambda for selector ${selector_name}"
  return 1
}

# Invoke the QA-only retrieval diagnostic (backend_orchestrator.retrieval_diagnostic)
# in one mode and assert every non-empty result names the expected release_id.
# Shared by activation and rollback: both need the identical coherence check.
qa_retrieval_invoke_diagnostic() {
  local function_name="$1" mode="$2" expected_release="$3" source_tag="$4"
  local response="$5" invoke_meta="$6" request
  request="${response}.request"
  jq -cn --arg mode "$mode" --arg source "$source_tag" --arg query \
    'Was ist die Regelaltersrente und wann kann ich sie beziehen?' \
    '{source:$source,mode:$mode,query:$query}' >"$request"
  aws lambda invoke --function-name "$function_name" \
    --cli-binary-format raw-in-base64-out \
    --payload "fileb://${request}" "$response" \
    --output json >"$invoke_meta"
  [[ "$(jq -r '.FunctionError // empty' "$invoke_meta")" == "" ]] || return 1
  jq -e --arg release "$expected_release" '
    .ok == true and .release_id == $release
    and .observed_release_ids == [$release]
  ' "$response" >/dev/null
}

# Invoke the diagnostic in hybrid mode WITHOUT a known expected release_id —
# used by the #494 scheduled health check, which has no promotion/rollback
# target to compare against. run_retrieval_diagnostic resolves the active
# manifest's own release_id internally and reports ok:true only when every
# semantic AND bm25 result named that single release_id — this alone is
# AC3's vector/BM25 coherence check. Prints the response body on success or
# failure so callers can inspect release_id/observed_release_ids either way.
qa_retrieval_invoke_hybrid_coherence_check() {
  local function_name="$1" source_tag="$2" response="$3" invoke_meta="$4" request
  request="${response}.request"
  jq -cn --arg source "$source_tag" --arg query \
    'Was ist die Regelaltersrente und wann kann ich sie beziehen?' \
    '{source:$source,mode:"hybrid",query:$query}' >"$request"
  if ! aws lambda invoke --function-name "$function_name" \
      --cli-binary-format raw-in-base64-out \
      --payload "fileb://${request}" "$response" \
      --output json >"$invoke_meta"; then
    qa_retrieval_fail "could not invoke ${function_name} for the hybrid coherence check"
    return 1
  fi
  if [[ "$(jq -r '.FunctionError // empty' "$invoke_meta")" != "" ]]; then
    qa_retrieval_fail "hybrid coherence check invocation returned a FunctionError"
    return 1
  fi
  jq -e '.ok == true' "$response" >/dev/null
}

# Poll semantic mode until the runtime observes expected_release within
# timeout_seconds, then verify bm25 and hybrid modes once each. Fails closed on
# timeout or on any mode reporting a different release_id.
qa_retrieval_wait_for_release_convergence() {
  local function_name="$1" expected_release="$2" source_tag="$3" timeout_seconds="$4"
  local output_dir="${5:-/tmp}" deadline
  deadline=$(( $(date +%s) + timeout_seconds ))
  while true; do
    if qa_retrieval_invoke_diagnostic "$function_name" semantic "$expected_release" "$source_tag" \
      "${output_dir}/qa-diag-semantic.json" "${output_dir}/qa-diag-semantic-invoke.json"; then
      break
    fi
    [[ "$(date +%s)" -lt "$deadline" ]] || {
      qa_retrieval_fail "runtime did not observe ${expected_release} within ${timeout_seconds}s"
      return 1
    }
    sleep 5
  done
  qa_retrieval_invoke_diagnostic "$function_name" bm25 "$expected_release" "$source_tag" \
    "${output_dir}/qa-diag-bm25.json" "${output_dir}/qa-diag-bm25-invoke.json" || {
    qa_retrieval_fail "bm25 diagnostic did not observe ${expected_release}"
    return 1
  }
  qa_retrieval_invoke_diagnostic "$function_name" hybrid "$expected_release" "$source_tag" \
    "${output_dir}/qa-diag-hybrid.json" "${output_dir}/qa-diag-hybrid-invoke.json" || {
    qa_retrieval_fail "hybrid diagnostic did not observe ${expected_release}"
    return 1
  }
}

# #628 — Signal the window in which a QA candidate build has overwritten the
# inactive slot's live corpus (the slot /qa/renate/retrieval/previous-manifest
# points at), making the #493 fast selector-flip rollback degraded: a flip
# would land on partially-ingested candidate content, not the previous
# release, because #493's own preflight only checks the still-pinned immutable
# control objects, not the live docs/ tree.
#
# Presence of the parameter IS the signal; absence (ParameterNotFound) means
# "not degraded" and is the fail-safe default (also correct for a fresh
# environment with no previous release to protect).
#
# The parameter name is per-environment (RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER,
# populated by qa_retrieval_init_env from retrieval-environment.mjs) so the
# same helpers serve qa and preprod (#643).

# Set the marker. FAIL-CLOSED: returns non-zero on any failure. Callers invoke
# this under `set -e` strictly before the first live mutation (the `aws s3 rm
# .../docs/` that overwrites the inactive slot), so a failed set aborts the
# job before anything is destroyed rather than leaving an undetectable window.
qa_retrieval_set_rollback_degraded_marker() {
  local release_id="$1" candidate_slot="$2" job_url="$3" pipeline_url="$4"
  local marker="${RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER:?qa_retrieval_init_env must run before the rollback-degraded marker}"
  local body
  body=$(mktemp)
  jq -n \
    --arg release "$release_id" \
    --arg slot "$candidate_slot" \
    --arg job "$job_url" \
    --arg pipeline "$pipeline_url" \
    --arg opened_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      {
        schema_version: 1,
        release_id: $release,
        candidate_slot: $slot,
        ci_job_url: $job,
        ci_pipeline_url: $pipeline,
        opened_at: $opened_at
      }
    ' >"$body"
  if ! aws ssm put-parameter --name "$marker" \
      --type String --value "file://${body}" --overwrite >/dev/null; then
    rm -f "$body"
    qa_retrieval_fail "could not set degraded-rollback marker ${marker}"
    return 1
  fi
  rm -f "$body"
}

# Clear the marker. BEST-EFFORT / FAIL-SAFE: MUST return 0 in every case. This
# is invoked under `set -e` from candidate_exit() (a non-zero return would
# corrupt the exit status the EXIT trap propagates) and from
# activate-qa-retrieval.sh after `trap - ERR` (a non-zero return would abort
# the job AFTER a healthy activation already completed). A failed clear leaves
# a stale marker set — a false alarm, which is always the safe direction; it
# must never look clear while the window is genuinely still open.
qa_retrieval_clear_rollback_degraded_marker() {
  local marker="${RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER:?qa_retrieval_init_env must run before the rollback-degraded marker}"
  local delete_error
  delete_error=$(mktemp)
  if aws ssm delete-parameter --name "$marker" \
      >/dev/null 2>"$delete_error"; then
    rm -f "$delete_error"
    return 0
  fi
  if grep -q ParameterNotFound "$delete_error"; then
    rm -f "$delete_error"
    return 0
  fi
  cat "$delete_error" >&2
  rm -f "$delete_error"
  echo "WARNING: degraded-rollback marker ${marker} not cleared (false alarm); clear manually with: aws ssm delete-parameter --name ${marker}" >&2
  return 0
}

