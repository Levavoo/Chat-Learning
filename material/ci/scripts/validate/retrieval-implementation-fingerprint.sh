#!/usr/bin/env bash
# #643 D3 — Deployment-implementation fingerprint.
#
# The visible three-line pin proves a release's INPUTS (chatbot + data + ETL
# coordinates). It does not prove WHICH deployment implementation validated
# them. Between a green QA transaction and the preprod approval, someone can
# merge a retrieval CDK or CI-script change — including a #626 stack-only ETL
# change that deliberately does not move any coordinate — and the triple alone
# cannot see it. This fingerprint closes that gap.
#
# It is a sha256 over the CONTENTS of:
#   - the retrieval/ETL CDK constructs, stacks, and config (this is the #626
#     STACK input set, so a stack-only #626 change flips this fingerprint),
#   - the #626 ETL IMAGE input set (ETL runtime + bm25_shared + dep manifests),
#   - the chatbot stack (it resolves the active-manifest selector at runtime),
#   - the promotion / rollback / monitoring / retention CI implementation
#     (scripts, shared lib, and the typed decision modules).
#
# Hashing convention deliberately mirrors etl-changed.sh (#626): per-file
# content digests, null-delimited and sorted so ordering is stable, then one
# digest over that listing — an in-place edit of an existing file changes the
# result, and so does adding or removing a file.
#
# Usage:
#   retrieval-implementation-fingerprint.sh            # print the fingerprint
#   retrieval-implementation-fingerprint.sh --tag      # print the origin tag
# Pure and offline: no AWS, no git, no network.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Deliberately NOT overridable via $REPO_ROOT: this fingerprint must always
# describe the implementation actually shipped in this checkout. Callers use
# REPO_ROOT to locate their own inputs (e.g. a pin file, or a test fixture), and
# inheriting that here would hash the wrong tree — or no tree at all.
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

IMPL_DIRS=(
  # retrieval/ETL infrastructure (== #626 STACK dirs)
  "cdk/lib/constructs/knowledge-base"
  "cdk/lib/custom-resources/source-reprocess"
  "cdk/lib/config/kb"
  # ETL runtime image inputs (== #626 IMAGE dirs)
  "backend/src/etl"
  "backend/src/bm25_shared"
)

IMPL_FILES=(
  # retrieval/ETL + chatbot stacks and CDK wiring (== #626 STACK files, plus
  # the chatbot stack, which resolves the active-manifest selector)
  "cdk/lib/etl-kb-stack.ts"
  "cdk/lib/chatbot-stack.ts"
  "cdk/lib/utils/parameter-models.ts"
  "cdk/parameter.ts"
  "cdk/bin/infrastructure.ts"
  "cdk/package.json"
  "cdk/package-lock.json"
  "cdk/cdk.json"
  "cdk/tsconfig.json"
  # ETL image dependency inputs (== #626 IMAGE files)
  "pyproject.toml"
  "uv.lock"
  "backend/pyproject.toml"
  # promotion / rollback / monitoring / retention implementation
  ".gitlab/ci/scripts/deploy/prepare-retrieval-promotion.sh"
  ".gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
  ".gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
  ".gitlab/ci/scripts/deploy/activate-retrieval.sh"
  ".gitlab/ci/scripts/ops/rollback-retrieval.sh"
  ".gitlab/ci/scripts/verify/etl-readiness-check.sh"
  ".gitlab/ci/scripts/lib/qa-retrieval.sh"
  ".gitlab/ci/scripts/lib/node/retrieval-orchestration.mjs"
  ".gitlab/ci/scripts/lib/node/retrieval-release.mjs"
  ".gitlab/ci/scripts/lib/node/retrieval-environment.mjs"
  ".gitlab/ci/scripts/lib/node/release-retention.mjs"
)

sha256_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

# Release automation rewrites the digibro-backend package version in
# backend/pyproject.toml and its editable uv.lock entry on every release. Those
# metadata-only changes do not alter the deployment implementation, so
# normalize exactly those fields (mirrors etl-changed.sh) — otherwise every
# release would spuriously invalidate the attestation.
normalized_contents() {
  local path="$1"
  case "$path" in
    backend/pyproject.toml)
      awk '
        /^\[/ { in_project = ($0 == "[project]") }
        in_project && /^[[:space:]]*version[[:space:]]*=/ {
          print "version = \"<release-version>\""
          next
        }
        { print }
      ' "$path"
      ;;
    uv.lock)
      awk '
        /^\[\[package\]\]$/ { in_backend_package = 0 }
        /^name = "digibro-backend"$/ { in_backend_package = 1 }
        in_backend_package && /^version = / {
          print "version = \"<release-version>\""
          next
        }
        { print }
      ' "$path"
      ;;
    *)
      command cat "$path"
      ;;
  esac
}

collect_paths() {
  local d f
  # Only GIT-TRACKED files. `find -type f` would also hash untracked, generated
  # artifacts — in practice __pycache__/*.pyc under backend/src/etl and
  # backend/src/bm25_shared, which are gitignored, absent from a fresh clone, and
  # whose bytes vary with the interpreter that produced them. That made the
  # fingerprint depend on whether Python had run in the checkout: a tree with
  # bytecode hashed 163 files where a clean clone hashed 79, yielding a different
  # value for identical committed code. For an attestation that is fatal — the
  # attester and the verifier run in different jobs, so preprod could fail closed
  # with "never attested on qa" even though nothing changed. Tracked files are
  # exactly "the implementation", and are identical in every checkout of a commit.
  for d in "${IMPL_DIRS[@]}"; do
    [[ -d "$d" ]] && git ls-files -z -- "$d"
  done
  for f in "${IMPL_FILES[@]}"; do
    printf '%s\0' "$f"
  done
  return 0
}

# Fail closed on a declared-but-missing input, in the MAIN shell — a check
# inside collect_paths would only exit its process-substitution subshell and the
# fingerprint would silently be computed over a smaller surface. Silently
# skipping is exactly the blind spot this fingerprint exists to close: a renamed
# or deleted script must break the attestation, not disappear from it.
assert_declared_inputs_present() {
  local f missing=0
  for f in "${IMPL_FILES[@]}"; do
    [[ -f "$f" ]] || {
      echo "retrieval-implementation-fingerprint: declared implementation input is missing: ${f}" >&2
      missing=1
    }
  done
  [[ "$missing" -eq 0 ]] || exit 1
}

compute_fingerprint() {
  local entries path digest
  entries=$(
    while IFS= read -r -d '' path; do
      digest=$(normalized_contents "$path" | sha256_stdin)
      printf '%s  %s\n' "$digest" "$path"
    done < <(collect_paths | sort -z)
  )
  [[ -n "$entries" ]] || {
    echo "retrieval-implementation-fingerprint: no implementation files found in ${REPO_ROOT}" >&2
    exit 1
  }
  printf '%s\n' "$entries" | sha256_stdin
}

cd "$REPO_ROOT"
assert_declared_inputs_present
FINGERPRINT="$(compute_fingerprint)"

case "${1:-}" in
  "")
    printf '%s\n' "$FINGERPRINT"
    ;;
  --tag)
    printf 'qa-attested-impl-%s\n' "$FINGERPRINT"
    ;;
  *)
    echo "Usage: $0 [--tag]" >&2
    exit 2
    ;;
esac
