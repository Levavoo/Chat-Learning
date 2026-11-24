#!/usr/bin/env bash
# lib/promote-mr.sh — shared promotion-MR helpers. Source this file; do not execute.
#
# Functions:
#   open_promotion_mr <from_env> <to_env> <new_version> <promo_branch> <smoke_test> <data_artifact_version> <etl_version>

# shellcheck source=lib/log.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/log.sh"

# open_promotion_mr <from_env> <to_env> <new_version> <promo_branch> <smoke_test> <data_artifact_version> <etl_version>
#
# Bumps the <to_env> version pin on <promo_branch> and opens/updates an MR.
# When smoke_test=true, the MR and branch are cleaned up on exit.
#
# Required: GL_TOKEN, CI_API_V4_URL, CI_PROJECT_ID, CI_SERVER_HOST,
#           CI_PROJECT_PATH, CI_JOB_TOKEN
open_promotion_mr() {
  # from_env is accepted for call-site readability but the "from" version shown
  # in the MR is the TARGET's current pin (what is being replaced), not the
  # source env's pin — see from_version below.
  # shellcheck disable=SC2034
  local from_env="$1"
  local to_env="$2" new_version="$3"
  # _promote_mr_promo_branch and _promote_mr_iid_file are intentionally non-local
  # so the EXIT trap can read them.
  _promote_mr_promo_branch="$4"
  local smoke_test="${5:-false}"
  local data_artifact_version="${6:-}"
  local etl_version="${7:-}"

  [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "Invalid application version: ${new_version}" >&2
    return 1
  }
  [[ "$data_artifact_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "Invalid data artifact version: ${data_artifact_version:-<empty>}" >&2
    return 1
  }
  [[ "$etl_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "Invalid ETL version: ${etl_version:-<empty>}" >&2
    return 1
  }

  : "${GL_TOKEN:?GL_TOKEN is required}"
  : "${CI_API_V4_URL:?CI_API_V4_URL is required}"
  : "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"
  : "${CI_SERVER_HOST:?CI_SERVER_HOST is required}"
  : "${CI_PROJECT_PATH:?CI_PROJECT_PATH is required}"

  local pin_file="deployments/${to_env}.yaml"
  # qa/preprod/prod use subdir layout: deployments/<env>/version.yaml
  case "$to_env" in
    qa | preprod | prod) pin_file="deployments/${to_env}/version.yaml" ;;
  esac
  _promote_mr_iid_file="$(mktemp)"
  echo "" > "$_promote_mr_iid_file"

  if [[ "$smoke_test" == "true" ]]; then
    # shellcheck disable=SC2317,SC2329  # invoked via trap EXIT
    _cleanup_promotion_mr() {
      local _saved_iid
      _saved_iid=$(tr -d '[:space:]' < "$_promote_mr_iid_file" 2>/dev/null || true)
      if [[ -n "$_saved_iid" ]]; then
        _mr_api PUT "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${_saved_iid}" \
          '{"state_event":"close"}' || true
      fi
      git push origin --delete "$_promote_mr_promo_branch" 2>/dev/null || true
      rm -f "$_promote_mr_iid_file"
    }
    trap _cleanup_promotion_mr EXIT
  fi

  local promo_branch_encoded="${_promote_mr_promo_branch//\//%2F}"

  git config user.email "ci@${CI_SERVER_HOST}"
  git config user.name "GitLab CI"
  git remote set-url origin "https://gitlab-ci-token:${GL_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"
  local default_branch="${CI_DEFAULT_BRANCH:-main}"
  git fetch --depth=1 origin "$default_branch"
  git checkout -B "$_promote_mr_promo_branch" "origin/${default_branch}"
  # "from" version = the target env's CURRENT pin (what this promotion replaces),
  # read from origin/${default_branch} before we overwrite it.
  local from_version
  from_version=$(grep '^version:' "$pin_file" 2>/dev/null \
    | sed 's/version: //' | tr -d '[:space:]' || true)
  [[ -n "$from_version" ]] || from_version="unknown"
  # Promotion pins deliberately stay human-readable: exactly the chatbot,
  # independently content-gated data, and immutable ETL release versions.
  printf 'version: %s\ndata_artifact_version: %s\netl_version: %s\n' \
    "$new_version" "$data_artifact_version" "$etl_version" >"$pin_file"
  git add "$pin_file"
  git commit -m "chore(deploy): ${to_env^^} Promotion auf ${new_version}"
  git push --force origin "$_promote_mr_promo_branch"

  # Mirror the branch commit at line 73 so the squash-merge commit (which
  # defaults to the MR title) lands as a conventional commit on master —
  # cocogitto parses commit type for version bumps.
  local mr_title="chore(deploy): ${to_env^^} Promotion auf ${new_version}"
  local mr_description
  mr_description="## \`${from_version}\` → \`${new_version}\`"$'\n\n'"Data artifact: \`${data_artifact_version}\`"$'\n\n'"ETL: \`${etl_version}\`"$'\n\n---\n'"*Automatisierte ${to_env^^}-Promotion*"

  local mr_url="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests"
  local mr_filter="state=opened&source_branch=${promo_branch_encoded}&target_branch=${default_branch}"

  local open_mrs
  open_mrs=$(_mr_api GET "${mr_url}?${mr_filter}") \
    || { echo "MR list request failed" >&2; return 1; }

  local mr_count
  mr_count=$(echo "$open_mrs" | jq 'length')

  if [[ "$mr_count" != "0" ]]; then
    local mr_iid
    mr_iid=$(echo "$open_mrs" | jq '.[0].iid')
    echo "$mr_iid" > "$_promote_mr_iid_file"
    local payload
    payload=$(jq -n \
      --arg title "$mr_title" \
      --arg description "$mr_description" \
      '{title: $title, description: $description}')
    _mr_api PUT "${mr_url}/${mr_iid}" "$payload" >/dev/null
    echo "Updated MR !${mr_iid}: ${mr_title}"
  else
    local payload
    payload=$(jq -n \
      --arg source_branch "$_promote_mr_promo_branch" \
      --arg target_branch "$default_branch" \
      --arg title "$mr_title" \
      --arg description "$mr_description" \
      '{source_branch: $source_branch, target_branch: $target_branch, title: $title, description: $description}')
    local response
    response=$(_mr_api POST "$mr_url" "$payload") \
      || { echo "MR create request failed" >&2; return 1; }
    local mr_iid
    mr_iid=$(echo "$response" | jq '.iid')
    echo "$mr_iid" > "$_promote_mr_iid_file"
    echo "Created MR !${mr_iid}: ${mr_title}"
  fi
  if [[ "$smoke_test" != "true" ]]; then rm -f "$_promote_mr_iid_file"; fi
}

# _mr_api METHOD URL [json_body]
# Authenticated GitLab API call; prints response body; returns curl exit code.
_mr_api() {
  local method="$1" url="$2" body="${3:-}"
  local args=(-sS --connect-timeout 10 --max-time 30
    -X "$method"
    -H "PRIVATE-TOKEN: $GL_TOKEN"
    -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then
    args+=(--data "$body")
  fi
  curl "${args[@]}" "$url"
}
