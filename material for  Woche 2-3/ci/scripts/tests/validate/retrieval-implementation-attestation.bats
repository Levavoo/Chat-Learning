#!/usr/bin/env bats
# #643 D3 / #660 — deployment-implementation attestation.
#
# The visible triple proves release INPUTS; the implementation attestation proves
# WHICH retrieval CDK/CI implementation validated them, so a post-QA change
# (notably a #626 stack-only one, which moves no coordinate) cannot reach preprod
# unvalidated. #643 enforced this by fingerprinting master HEAD and requiring a
# matching qa-attested-impl-<fp> tag; because HEAD drifts with unrelated commits,
# that comparison forced a freeze window on every promotion (#660). #660 replaced
# the comparison by RUNNING the exact implementation QA attested: the promoted
# triple resolves (via its qa-deployed tag) to the exact QA commit, and
# resolve-attested-implementation.sh overlays that commit's cdk/ app + deploy
# scripts before any mutation. These tests cover both the still-attested surface
# (the unchanged fingerprint) and the new discovery + overlay.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
FINGERPRINT="$REPO_ROOT/.gitlab/ci/scripts/validate/retrieval-implementation-fingerprint.sh"
PREPARE="$REPO_ROOT/.gitlab/ci/scripts/deploy/prepare-retrieval-promotion.sh"
RESOLVE="$REPO_ROOT/.gitlab/ci/scripts/deploy/resolve-attested-implementation.sh"
PUSH_TAG="$REPO_ROOT/.gitlab/ci/scripts/release/push-qa-deployed-tag.sh"
LIB_DEPLOY="$REPO_ROOT/.gitlab/ci/scripts/lib/deploy.sh"

# A well-formed 40-hex commit the git stub hands back for the qa-deployed tag.
FIXTURE_SHA="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
  export TEST_DIR
  printf 'version: 1.83.3\ndata_artifact_version: v1.2.3-data.1\netl_version: v1.2.3\n' \
    >"$TEST_DIR/pin.yaml"
  # shellcheck source=/dev/null
  source "$LIB_DEPLOY"
}
teardown() { rm -rf "$TEST_DIR"; }

# Runtime-configurable git stub. It reads its behaviour from the environment so a
# single installed stub serves every scenario:
#   STUB_LSREMOTE = found (default) | absent | unreachable
#   STUB_SHA      = the commit ls-remote/rev-parse report (default FIXTURE_SHA)
#   STUB_MISSING  = a path for which ls-tree reports empty (i.e. absent at the
#                   attested commit), to exercise the fail-closed overlay
# git never touches the network here; the discovery, fetch, verify, and overlay
# are all intercepted so the tests are hermetic.
_install_git_stub() {
  cat >"$TEST_DIR/bin/git" <<'STUB'
#!/usr/bin/env bash
sha="${STUB_SHA:-a1b2c3d4e5f60718293a4b5c6d7e8f9012345678}"
case "$*" in
  *ls-remote*)
    case "${STUB_LSREMOTE:-found}" in
      found)      printf '%s\trefs/tags/stub\n' "$sha"; exit 0 ;;
      absent)     exit 2 ;;
      *)          exit 128 ;;
    esac ;;
  *rev-parse*FETCH_HEAD*) printf '%s\n' "$sha"; exit 0 ;;
  *ls-tree*)
    path="${@: -1}"
    [[ -n "${STUB_MISSING:-}" && "$path" == "${STUB_MISSING}" ]] && exit 0
    printf '040000 tree deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\t%s\n' "$path"; exit 0 ;;
  *fetch*)    exit 0 ;;
  *checkout*) exit 0 ;;
  *)          exit 0 ;;
esac
STUB
  chmod +x "$TEST_DIR/bin/git"
}

# --- Unchanged attested surface: the fingerprint (still pushed by QA) ---------

@test "[#643 fingerprint] is deterministic and emits a sha256 tag form" {
  run "$FINGERPRINT"
  [ "$status" -eq 0 ]
  [[ "$output" =~ ^[0-9a-f]{64}$ ]]
  first="$output"
  run "$FINGERPRINT"
  [ "$output" = "$first" ]
  run "$FINGERPRINT" --tag
  [ "$output" = "qa-attested-impl-${first}" ]
}

@test "[#643 fingerprint] a #626 stack-only CDK change flips the fingerprint" {
  run "$FINGERPRINT"
  before="$output"
  cp "$REPO_ROOT/cdk/lib/etl-kb-stack.ts" "$TEST_DIR/etl-kb-stack.bak"
  printf '\n// bats fingerprint sensitivity probe\n' >>"$REPO_ROOT/cdk/lib/etl-kb-stack.ts"
  run "$FINGERPRINT"
  after="$output"
  cp "$TEST_DIR/etl-kb-stack.bak" "$REPO_ROOT/cdk/lib/etl-kb-stack.ts"
  [ "$before" != "$after" ]
  run "$FINGERPRINT"
  [ "$output" = "$before" ]
}

@test "[#643 fingerprint] a promotion-script change flips the fingerprint" {
  run "$FINGERPRINT"
  before="$output"
  cp "$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh" "$TEST_DIR/activate.bak"
  printf '\n# bats fingerprint sensitivity probe\n' >>"$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"
  run "$FINGERPRINT"
  after="$output"
  cp "$TEST_DIR/activate.bak" "$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"
  [ "$before" != "$after" ]
}

@test "[#643 fingerprint] a declared-but-missing implementation input fails closed" {
  moved="$REPO_ROOT/.gitlab/ci/scripts/ops/rollback-retrieval.sh"
  mv "$moved" "$TEST_DIR/rollback.moved"
  run "$FINGERPRINT"
  mv "$TEST_DIR/rollback.moved" "$moved"
  [ "$status" -ne 0 ]
  [[ "$output" == *"declared implementation input is missing"* ]]
}

@test "[#643 fingerprint] untracked build artifacts do not change the fingerprint" {
  before="$("$FINGERPRINT")"
  mkdir -p "$REPO_ROOT/backend/src/etl/__pycache__"
  probe="$REPO_ROOT/backend/src/etl/__pycache__/bats-probe.cpython-314.pyc"
  printf 'not-real-bytecode' >"$probe"
  after="$("$FINGERPRINT")"
  rm -f "$probe"
  [ "$before" = "$after" ]
  run git -C "$REPO_ROOT" check-ignore -q "backend/src/etl/__pycache__"
  [ "$status" -eq 0 ]
}

@test "[#643 attestation] qa publishes both the triple and implementation tags" {
  grep -q 'retrieval-implementation-fingerprint.sh" --tag' "$PUSH_TAG"
  grep -q 'push_tag_if_absent "\$TAG"' "$PUSH_TAG"
  grep -q 'push_tag_if_absent "\$IMPL_TAG"' "$PUSH_TAG"
}

# --- #660 discovery: pin -> qa-deployed tag -> attested commit ----------------

@test "[#660 discovery] resolve_pin_attested_commit prints the qa-deployed commit" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=found STUB_SHA="$FIXTURE_SHA"
  run resolve_pin_attested_commit "$TEST_DIR/pin.yaml"
  [ "$status" -eq 0 ]
  [ "$output" = "$FIXTURE_SHA" ]
}

@test "[#660 discovery] an absent qa-deployed tag fails closed (never attested)" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=absent
  run resolve_pin_attested_commit "$TEST_DIR/pin.yaml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"no qa-deployed tag"* ]]
  [[ "$output" == *"never smoke-tested on qa"* ]]
}

@test "[#660 discovery] an unreachable origin is not treated as unattested" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=unreachable
  run resolve_pin_attested_commit "$TEST_DIR/pin.yaml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not reach origin"* ]]
  [[ "$output" == *"retry the job"* ]]
}

# --- #660 prepare: record the attested commit, fail closed before approval ----

@test "[#660 prepare] qa (the attester) records no attested commit and needs no tag" {
  # qa runs its own current implementation; it must not consult origin for an
  # attestation, so no git stub is installed. The dotenv carries an empty
  # ATTESTED_COMMIT and the real coordinates.
  run "$PREPARE" qa "$TEST_DIR/pin.yaml" "$TEST_DIR/out.env"
  [ "$status" -eq 0 ]
  grep -q '^ATTESTED_COMMIT=$' "$TEST_DIR/out.env"
  grep -q '^RELEASE_ID=' "$TEST_DIR/out.env"
}

@test "[#660 prepare] preprod records the qa-attested commit when the triple is attested" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=found STUB_SHA="$FIXTURE_SHA"
  run "$PREPARE" preprod "$TEST_DIR/pin.yaml" "$TEST_DIR/out.env"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Implementation attestation:"* ]]
  [[ "$output" == *"$FIXTURE_SHA"* ]]
  grep -q "^ATTESTED_COMMIT=${FIXTURE_SHA}$" "$TEST_DIR/out.env"
}

@test "[#660 prepare] preprod fails closed when the triple was never on qa" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=absent
  run "$PREPARE" preprod "$TEST_DIR/pin.yaml" "$TEST_DIR/out.env"
  [ "$status" -ne 0 ]
  [[ "$output" == *"never smoke-tested on qa"* ]]
}

@test "[#660 prepare] break-glass skip is explicit and loudly logged" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=found ATTESTATION_MODE=skip
  run "$PREPARE" preprod "$TEST_DIR/pin.yaml" "$TEST_DIR/out.env"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
  [[ "$output" == *"attestation bypassed"* ]]
  grep -q '^ATTESTED_COMMIT=$' "$TEST_DIR/out.env"
}

# --- #660 overlay: materialize the attested implementation --------------------

@test "[#660 overlay] downstream overlays the attested implementation and records its identity" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=found STUB_SHA="$FIXTURE_SHA"
  export ATTESTED_ENV="$TEST_DIR/attested.env"
  run "$RESOLVE" preprod "$TEST_DIR/pin.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Overlaid the qa-attested implementation from ${FIXTURE_SHA}"* ]]
  grep -q "^ATTESTED_COMMIT=${FIXTURE_SHA}$" "$TEST_DIR/attested.env"
  grep -q '^ATTESTED_TRIPLE_TAG=qa-deployed-1.83.3--data-v1.2.3-data.1--etl-v1.2.3$' "$TEST_DIR/attested.env"
}

@test "[#660 overlay] a declared attested path absent at the commit fails closed" {
  _install_git_stub
  export PATH="$TEST_DIR/bin:$PATH" STUB_LSREMOTE=found STUB_SHA="$FIXTURE_SHA" STUB_MISSING="cdk"
  export ATTESTED_ENV="$TEST_DIR/attested.env"
  run "$RESOLVE" preprod "$TEST_DIR/pin.yaml"
  [ "$status" -ne 0 ]
  [[ "$output" == *"declared attested path missing"* ]]
  [ ! -f "$TEST_DIR/attested.env" ]
}

@test "[#660 overlay] qa (origin mode) is a no-op — the attester runs current code" {
  # No git stub: origin mode must exit before any discovery/overlay.
  export ATTESTED_ENV="$TEST_DIR/attested.env"
  run "$RESOLVE" qa "$TEST_DIR/pin.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not downstream"* ]]
  [ ! -f "$TEST_DIR/attested.env" ]
}

@test "[#660 overlay] break-glass skip runs current master and overlays nothing" {
  export ATTESTED_ENV="$TEST_DIR/attested.env" ATTESTATION_MODE=skip
  run "$RESOLVE" preprod "$TEST_DIR/pin.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ATTESTATION_MODE=skip"* ]]
  [ ! -f "$TEST_DIR/attested.env" ]
}
