#!/usr/bin/env bats
# #671 — the attested retrieval implementation must be releasable.
#
# resolve-attested-implementation.sh overlays the retrieval deploy scripts into
# every downstream promotion, and retrieval-implementation-fingerprint.sh hashes
# them, so a change to them changes what prod executes. Cocogitto only bumps for
# commits that touch a declared package path, and .gitlab/ci/scripts belonged to
# no package: the fix in !1192 produced no version, so no QA promotion MR, no
# qa-deployed-<triple> tag, and no route to prod. These tests keep the cog.toml
# package definition and the fingerprint's file list from drifting apart again.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
COG_TOML="$REPO_ROOT/cog.toml"
FINGERPRINT="$REPO_ROOT/.gitlab/ci/scripts/validate/retrieval-implementation-fingerprint.sh"
ATTEST="$REPO_ROOT/.gitlab/ci/scripts/deploy/resolve-attested-implementation.sh"

# Every .gitlab/ci/scripts entry the fingerprint hashes, one per line.
impl_ci_files() {
  grep -oE '"\.gitlab/ci/scripts/[^"]+"' "$FINGERPRINT" | tr -d '"' | sort -u
}

# Every .gitlab/ci/scripts entry cog.toml assigns to a package.
cog_ci_includes() {
  grep -oE '"\.gitlab/ci/scripts/[^"]+"' "$COG_TOML" | tr -d '"' | sort -u
}

@test "[#671 release] every fingerprinted CI implementation file belongs to a cocogitto package" {
  missing=""
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    cog_ci_includes | grep -Fxq "$file" || missing="${missing}${file}"$'\n'
  done < <(impl_ci_files)
  [ -z "$missing" ] || {
    echo "Not releasable — absent from cog.toml packages:" >&2
    printf '%s' "$missing" >&2
    false
  }
}

@test "[#671 release] cog.toml claims no CI implementation file the fingerprint ignores" {
  extra=""
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    impl_ci_files | grep -Fxq "$file" || extra="${extra}${file}"$'\n'
  done < <(cog_ci_includes)
  [ -z "$extra" ] || {
    echo "In cog.toml but not fingerprinted:" >&2
    printf '%s' "$extra" >&2
    false
  }
}

@test "[#671 release] every attested overlay path is fingerprinted or a directory" {
  # ATTESTED_PATHS is what actually executes downstream; anything file-shaped in
  # it must also be hashed, otherwise prod could run unfingerprinted code.
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    [[ -d "$REPO_ROOT/$path" ]] && continue
    grep -Fq "\"$path\"" "$FINGERPRINT"
  done < <(grep -oE '"\.gitlab/ci/scripts/[^"]+"' "$ATTEST" | tr -d '"' | sort -u)
}

@test "[#671 release] the retrieval implementation files exist where both lists claim" {
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    [ -f "$REPO_ROOT/$file" ]
  done < <(cog_ci_includes)
}
