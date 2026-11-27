#!/usr/bin/env bash
# lib/deploy.sh — shared CDK deploy helpers. Source this file; do not execute.
#
# Functions:
#   assume_deploy_role <role_arn>
#   ensure_ecr_image   <registry> <repo> <tag>
#   validate_promotion_pin <pin_path>
#   assert_pin_on_qa <pin_path> <qa_pin_path>
#   promote_image_tag_ssm <env> <version>
#   cdk_deploy_stack   <stack> <env> <outputs_file>
#   assert_maintenance_rehearsed <version>

# shellcheck source=lib/log.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/log.sh"

# Allowed environments — guards against typos in callers.
_DEPLOY_ALLOWED_ENVS="dev qa preprod prod"

_deploy_validate_env() {
  local env="$1"
  for allowed in $_DEPLOY_ALLOWED_ENVS; do
    [[ "$env" == "$allowed" ]] && return 0
  done
  echo "deploy-lib: unknown env '$env' (allowed: $_DEPLOY_ALLOWED_ENVS)" >&2
  return 1
}

# assume_deploy_role <role_arn>
# Exports AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN.
# Requires: GITLAB_OIDC_TOKEN, CI_JOB_ID.
assume_deploy_role() {
  local role_arn="$1"
  : "${GITLAB_OIDC_TOKEN:?GITLAB_OIDC_TOKEN is required}"
  : "${CI_JOB_ID:?CI_JOB_ID is required}"

  log_section "Assuming role"
  log_kv "Role:" "$role_arn"

  local sts_output
  sts_output=$(aws sts assume-role-with-web-identity \
    --role-arn "$role_arn" \
    --role-session-name "gitlab-ci-${CI_JOB_ID}" \
    --web-identity-token "$GITLAB_OIDC_TOKEN" \
    --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
    --output text 2>/dev/null) || sts_output=""

  read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
    <<< "$sts_output"
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

  [[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" \
    && -n "$AWS_SESSION_TOKEN" ]] \
    || { echo "STS assume-role failed: empty credentials" >&2; return 1; }

  aws sts get-caller-identity
}

# ensure_ecr_image <registry> <repo> <tag>
# Fails fast if the image does not exist in ECR.
ensure_ecr_image() {
  local registry="$1" repo="$2" tag="$3"
  log_kv "ECR check:" "${registry}/${repo}:${tag}"
  aws ecr describe-images \
    --registry-id "$registry" \
    --repository-name "$repo" \
    --image-ids imageTag="$tag" \
    --region eu-central-1 > /dev/null \
    || { echo "ECR image ${repo}:${tag} not found — run build-lambda first" >&2; return 1; }
}

# promotion_pin_value <pin_path> <key>
promotion_pin_value() {
  local pin="$1" key="$2"
  awk -F': *' -v key="$key" '$1 == key { print $2; exit }' "$pin" \
    | tr -d '[:space:]'
}

# read_pin_version <pin_path>
# Extract version value from YAML pin file, handling optional spacing and trailing comments.
# Returns empty string if version is not found.
read_pin_version() {
  local pin="$1"
  sed -n 's/^version:[[:space:]]*//p' "$pin" \
    | head -n1 | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]'
}

# validate_promotion_pin <pin_path>
# A promotion pin intentionally has exactly three lines. Keeping this strict
# makes the generated QA/preprod MR as reviewable as the original version-only
# promotion while allowing data and ETL to advance independently.
validate_promotion_pin() {
  local pin="$1" version data_artifact_version etl_version expected actual
  [[ -f "$pin" ]] || { echo "promotion pin not found: $pin" >&2; return 1; }
  version=$(promotion_pin_value "$pin" version)
  data_artifact_version=$(promotion_pin_value "$pin" data_artifact_version)
  etl_version=$(promotion_pin_value "$pin" etl_version)
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "promotion pin has an invalid version: $pin" >&2
    return 1
  }
  [[ "$data_artifact_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "promotion pin has an invalid data_artifact_version: $pin" >&2
    return 1
  }
  [[ "$etl_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]] || {
    echo "promotion pin has an invalid etl_version: $pin" >&2
    return 1
  }
  expected=$(printf 'version: %s\ndata_artifact_version: %s\netl_version: %s' \
    "$version" "$data_artifact_version" "$etl_version")
  actual=$(cat "$pin")
  [[ "$actual" == "$expected" ]] || {
    echo "promotion pin must contain exactly version, data_artifact_version, and etl_version" >&2
    return 1
  }
}

# Canonical qa-deployed tag name. Field separator is `--` (double hyphen) so
# it cannot be produced by any legal `data_artifact_version` — semver
# pre-release suffixes like `-data.N` collided with the single-hyphen form.
# Double hyphen was picked over comma/colon because `:` is disallowed in git
# refnames (git-check-ref-format rule 5): `git tag qa-deployed-3.44.9,dataset:v...`
# fails with "not a valid tag name".
promotion_pin_attestation_tag() {
  local pin="$1"
  validate_promotion_pin "$pin" || return 1
  printf 'qa-deployed-%s--data-%s--etl-%s\n' \
    "$(promotion_pin_value "$pin" version)" \
    "$(promotion_pin_value "$pin" data_artifact_version)" \
    "$(promotion_pin_value "$pin" etl_version)"
}

# Pre-migration format. Kept only so downstream deploys can still resolve
# qa-deployed tags pushed before the separator switch. Drop this and the
# legacy branch in resolve_pin_attestation_tag_on_origin after every active
# preprod/prod pin references a tag in the new format.
promotion_pin_attestation_tag_legacy() {
  local pin="$1"
  validate_promotion_pin "$pin" || return 1
  printf 'qa-deployed-%s-data-%s-etl-%s\n' \
    "$(promotion_pin_value "$pin" version)" \
    "$(promotion_pin_value "$pin" data_artifact_version)" \
    "$(promotion_pin_value "$pin" etl_version)"
}

# resolve_pin_attestation_tag_on_origin <pin_path>
# Print the qa-deployed tag NAME that exists on origin for this pin. Tries
# the canonical format first, falls back to the legacy format. Preserves the
# 0/2/other exit-code discipline so a transient origin outage on the first
# probe never silently falls through to the legacy branch.
resolve_pin_attestation_tag_on_origin() {
  local pin="$1" tag ls_rc

  tag=$(promotion_pin_attestation_tag "$pin") || return 1
  ls_rc=0
  git ls-remote --tags --exit-code origin "refs/tags/${tag}" >/dev/null 2>&1 || ls_rc=$?
  case "$ls_rc" in
    0) printf '%s\n' "$tag"; return 0 ;;
    2) : ;;
    *)
      echo "Refusing deploy: could not reach origin to resolve ${tag} (git ls-remote exit ${ls_rc})." >&2
      echo "Likely a transient network or auth issue, not an attestation problem — retry the job." >&2
      return 1
      ;;
  esac

  tag=$(promotion_pin_attestation_tag_legacy "$pin") || return 1
  ls_rc=0
  git ls-remote --tags --exit-code origin "refs/tags/${tag}" >/dev/null 2>&1 || ls_rc=$?
  case "$ls_rc" in
    0)
      echo "note: resolved qa-deployed tag via legacy format (${tag})" >&2
      printf '%s\n' "$tag"
      return 0
      ;;
    2) return 2 ;;
    *)
      echo "Refusing deploy: could not reach origin to resolve legacy ${tag} (git ls-remote exit ${ls_rc})." >&2
      echo "Likely a transient network or auth issue, not an attestation problem — retry the job." >&2
      return 1
      ;;
  esac
}

# resolve_pin_attested_commit <pin_path>
# Print the exact origin commit QA attested for this pin's triple, by
# dereferencing the qa-deployed-<triple> tag that push-qa-deployed-tag.sh pushed
# at the QA transaction's HEAD. That same commit also carries the matching
# qa-attested-impl-<fp> tag (both are pushed together), so the resolved commit IS
# an attested deployment implementation. #660 runs a downstream promotion from
# this commit instead of comparing master HEAD against a tag, which removed the
# freeze window (see docs/architecture/runbooks/643-preprod-retrieval-promotion.md).
#
# Unlike assert_pin_on_qa this ALWAYS resolves the tag: it has no "matches
# current qa pin" fast path, because the caller needs the commit itself, not mere
# proof of existence. Fail-closed with the git ls-remote 0/2/other exit-code
# discipline (see assert_version_on_qa) so a transient origin outage is never
# mistaken for an unattested triple.
resolve_pin_attested_commit() {
  local pin="$1" tag out sha ls_rc=0 resolve_rc=0
  # Resolve which tag NAME exists on origin (new or legacy format). A transport
  # error emits its own message and returns 1; a definitively absent tag returns
  # 2 and we surface the "never QA-deployed" refusal below.
  # NOTE: bare `tag=$(fn)` under caller `set -e` aborts on non-zero — capture
  # the exit code with the `|| rc=$?` idiom so we can branch on it.
  tag=$(resolve_pin_attestation_tag_on_origin "$pin") || resolve_rc=$?
  case "$resolve_rc" in
    0) : ;;
    2)
      tag=$(promotion_pin_attestation_tag "$pin") || return 1
      echo "Refusing deploy: no qa-deployed tag ${tag} on origin." >&2
      echo "This triple was never smoke-tested on qa, so there is no attested" >&2
      echo "implementation to run. Promote it through qa first." >&2
      return 1
      ;;
    *) return 1 ;;
  esac

  # We already know the ref exists (resolver returned 0), so a non-zero here is
  # transport. Query the tag and its peeled form in one round-trip.
  out=$(git ls-remote --tags --exit-code origin \
    "refs/tags/${tag}" "refs/tags/${tag}^{}" 2>/dev/null) || ls_rc=$?
  case "$ls_rc" in
    0) : ;;
    *)
      echo "Refusing deploy: could not reach origin to resolve ${tag} (git ls-remote exit ${ls_rc})." >&2
      echo "Likely a transient network or auth issue, not an attestation problem — retry the job." >&2
      return 1
      ;;
  esac

  # Prefer the peeled (^{}) line when present (annotated tag) and fall back to
  # the plain line (push-qa-deployed-tag.sh pushes LIGHTWEIGHT tags, which have
  # no peeled ref and point straight at the commit).
  sha=$(awk '
    $2 ~ /\^\{\}$/ { peeled = $1 }
    $2 !~ /\^\{\}$/ { plain = $1 }
    END { print (peeled != "" ? peeled : plain) }
  ' <<<"$out")
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Refusing deploy: could not parse a commit sha for ${tag} from origin." >&2
    return 1
  }
  printf '%s\n' "$sha"
}

# assert_version_on_qa <version> <qa_pin_path>
# Accepts <version> for downstream (preprod/prod) deploy iff it was previously
# on qa — either:
#   (a) it equals qa's CURRENT pinned version (deployments/qa/version.yaml), OR
#   (b) a `qa-deployed-<version>` git tag exists on origin (pushed by
#       smoke-eval:qa after a successful qa deploy).
#
# Rationale: (a) covers the fresh-promotion happy path (fast, offline, no git);
# (b) enables preprod to hold a previously-deployed qa version — needed for
# preprod-independent rollback and RC-hold flows.
#
# Reading tags directly from origin (git ls-remote) is deliberate: the CI
# clone is shallow (--depth 20) and may not carry all local tags, but every
# runner can talk to origin. See #560 for the design rationale.
assert_version_on_qa() {
  local version="$1" qa_pin="$2"
  : "${qa_pin:?assert_version_on_qa: qa_pin path is required}"
  [[ -f "$qa_pin" ]] || { echo "qa pin not found: $qa_pin" >&2; return 1; }

  local qa_current
  qa_current=$(read_pin_version "$qa_pin")

  if [[ "$version" == "$qa_current" ]]; then
    log_kv "qa check:" "${version} (matches current qa pin)"
    return 0
  fi

  # git ls-remote --exit-code contract (see git-ls-remote(1)):
  #   0   → talked to origin, ref found
  #   2   → talked to origin, ref definitively absent
  #   *   → could not talk to origin (network, auth, DNS)
  # Conflating the last two would send operators hunting for a promotion bug
  # during a transient GitLab outage, and would spuriously fail legitimate
  # rollback deploys. Branch explicitly on the exit code.
  local tag="qa-deployed-${version}"
  local ls_rc=0
  git ls-remote --tags --exit-code origin "refs/tags/${tag}" >/dev/null 2>&1 || ls_rc=$?

  case "$ls_rc" in
    0)
      log_kv "qa check:" "${version} (qa-deployed tag ${tag} found)"
      return 0
      ;;
    2)
      echo "Refusing deploy: version ${version} was never smoke-tested on qa." >&2
      echo "Current qa pin is ${qa_current}. No git tag ${tag} on origin." >&2
      echo "preprod/prod may only deploy versions that passed smoke-eval:qa." >&2
      return 1
      ;;
    *)
      echo "Refusing deploy: could not reach origin to check qa-deployed tags (git ls-remote exit ${ls_rc})." >&2
      echo "Likely a transient network or auth issue, not a promotion problem — retry the job." >&2
      return 1
      ;;
  esac
}

# assert_pin_on_qa <pin_path> <qa_pin_path>
# The application, data, and ETL versions are one promotion unit. Downstream
# deploys accept either QA's current triple or its smoke-test tag.
assert_pin_on_qa() {
  local pin="$1" qa_pin="$2"
  validate_promotion_pin "$pin" || return 1
  validate_promotion_pin "$qa_pin" || return 1

  local version data_version etl_version qa_version qa_data_version qa_etl_version tag ls_rc=0
  version=$(promotion_pin_value "$pin" version)
  data_version=$(promotion_pin_value "$pin" data_artifact_version)
  etl_version=$(promotion_pin_value "$pin" etl_version)
  qa_version=$(promotion_pin_value "$qa_pin" version)
  qa_data_version=$(promotion_pin_value "$qa_pin" data_artifact_version)
  qa_etl_version=$(promotion_pin_value "$qa_pin" etl_version)

  if [[ "$version" == "$qa_version" && "$data_version" == "$qa_data_version" \
    && "$etl_version" == "$qa_etl_version" ]]; then
    log_kv "qa check:" "${version} + ${data_version} + ${etl_version} (matches current qa pin)"
    return 0
  fi

  local resolve_rc=0
  tag=$(resolve_pin_attestation_tag_on_origin "$pin") || resolve_rc=$?
  case "$resolve_rc" in
    0)
      log_kv "qa check:" "${version} + ${data_version} + ${etl_version} (${tag} found)"
      ;;
    2)
      tag=$(promotion_pin_attestation_tag "$pin")
      echo "Refusing deploy: ${version} + ${data_version} + ${etl_version} was never smoke-tested on qa." >&2
      echo "No git tag ${tag} (or legacy equivalent) on origin." >&2
      return 1
      ;;
    *)
      return 1
      ;;
  esac
}

# promote_image_tag_ssm <env> <version>
# Saves current tag to /env/renate/image-tag-previous, then writes /env/renate/image-tag.
promote_image_tag_ssm() {
  local env="$1" version="$2"
  _deploy_validate_env "$env" || return 1
  local ssm_current="/${env}/renate/image-tag"
  local ssm_prev="/${env}/renate/image-tag-previous"

  local prev
  prev=$(aws ssm get-parameter --name "$ssm_current" \
    --query Parameter.Value --output text 2>/dev/null || true)
  if [[ -n "$prev" ]]; then
    aws ssm put-parameter --name "$ssm_prev" \
      --value "$prev" --type String --overwrite
    log_kv "SSM prev:" "$prev"
  fi
  aws ssm put-parameter --name "$ssm_current" \
    --value "$version" --type String --overwrite
  log_kv "SSM tag:" "$version"
}

# cdk_deploy_stack <stack> <env> <outputs_file> [extra_context...]
# Deploys the CDK stack; falls back to CloudFormation describe-stacks for outputs.
# Extra positional args after <outputs_file> are passed through verbatim as
# additional `--context key=value` flags (e.g. for the ETL image-tag override).
cdk_deploy_stack() {
  local stack="$1" env="$2" outputs_file="$3"
  shift 3
  local extra_context=("$@")
  local fallback_script
  fallback_script="$(dirname "${BASH_SOURCE[0]}")/../util/get-stack-outputs.sh"

  log_section "CDK deploy"
  log_kv "Stack:" "$stack"
  log_kv "Env:" "$env"

  rm -f "$outputs_file"
  local context_args=("--context" "env=${env}")
  local ctx
  for ctx in "${extra_context[@]}"; do
    context_args+=("--context" "$ctx")
  done

  (cd cdk && npx cdk deploy "$stack" \
    "${context_args[@]}" \
    --require-approval never \
    --outputs-file "$outputs_file")

  if [[ ! -f "$outputs_file" ]] || \
      ! jq -e 'type == "object"' "$outputs_file" >/dev/null 2>&1; then
    echo "Retrieving outputs from CloudFormation (fallback)…" >&2
    rm -f "$outputs_file"
    bash "$fallback_script" "$stack" "$outputs_file"
  fi
  log_done
}

# assert_maintenance_rehearsed <version>
# Requires at least 2 maintenance-rehearsed-qa-<version>-* tags on origin,
# confirming the version completed at least two qa enable→disable cycles before
# preprod maintenance is enabled. Tags are pushed by
# push-maintenance-rehearsed-tag.sh. See TKT-MM-04.
assert_maintenance_rehearsed() {
  local version="$1"
  local count=0
  count=$(git ls-remote --tags origin "refs/tags/maintenance-rehearsed-qa-${version}-*" \
    | grep -c "maintenance-rehearsed-qa-${version}-" || true)
  if [[ "$count" -ge 2 ]]; then
    return 0
  fi
  echo "Refusing: ${version} has only ${count} rehearsal(s) on qa (need at least 2)." >&2
  return 1
}
