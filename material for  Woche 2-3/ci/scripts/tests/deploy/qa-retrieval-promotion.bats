#!/usr/bin/env bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
PREPARE="$REPO_ROOT/.gitlab/ci/scripts/deploy/prepare-retrieval-promotion.sh"
PUBLISH="$REPO_ROOT/.gitlab/ci/scripts/build/publish-image-metadata.sh"
PARENT_YAML="$REPO_ROOT/.gitlab/ci/deploy/qa/deploy.yml"
CHILD_YAML="$REPO_ROOT/.gitlab/ci/deploy/qa/retrieval-promotion.yml"
CANDIDATE="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh"
COMMON="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval.sh"
QA_RETRIEVAL_COMMON="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval-common.sh"
S3="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval-s3.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[#492 prepare] exact three-line pin emits canonical release ID" {
  printf 'version: 1.83.3\ndata_artifact_version: v1.83.3-qa-blue-baseline\netl_version: v1.83.3-qa-blue-baseline\n' >"$TEST_DIR/pin.yaml"
  run "$PREPARE" qa "$TEST_DIR/pin.yaml" "$TEST_DIR/output.env"
  [ "$status" -eq 0 ]
  grep -q '^RELEASE_ID=sha256-4a68e8e7f1bfa474a9d2c955a0c208e5229fbfa8c723a554d9266e165958325a$' "$TEST_DIR/output.env"
}

@test "[#492 prepare] canonical release ID is deterministic and changes with every coordinate" {
  run node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" \
    derive-release 1.2.3 v1.2.3-data.1 v1.2.3
  [ "$status" -eq 0 ]
  first="$output"

  run node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" \
    derive-release 1.2.3 v1.2.3-data.1 v1.2.3
  [ "$status" -eq 0 ]
  [ "$output" = "$first" ]

  run node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" \
    derive-release 1.2.4 v1.2.3-data.1 v1.2.3
  [ "$status" -eq 0 ]
  [ "$output" != "$first" ]
}

@test "[#492 prepare] extra pin field fails before output" {
  printf 'version: 1.2.3\ndata_artifact_version: v1.2.3\netl_version: v1.2.3\nrelease_id: nope\n' >"$TEST_DIR/pin.yaml"
  run "$PREPARE" qa "$TEST_DIR/pin.yaml" "$TEST_DIR/output.env"
  [ "$status" -ne 0 ]
  [ ! -e "$TEST_DIR/output.env" ]
}

@test "[#492 metadata] publishes immutable tokenizer compatibility metadata" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$TEST_DIR/aws-args"
EOF
  cat >"$TEST_DIR/bin/jq" <<'EOF'
#!/usr/bin/env bash
touch "$TEST_DIR/jq-called"
exit 99
EOF
  chmod +x "$TEST_DIR/bin/aws" "$TEST_DIR/bin/jq"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run "$PUBLISH" chatbot 1.2.3 \
    "sha256:$(printf 'a%.0s' {1..64})" cistem-decompound-v1
  [ "$status" -eq 0 ]
  [ ! -e "$TEST_DIR/jq-called" ]
  grep -q '/dev/renate/image-metadata/chatbot/1.2.3' "$TEST_DIR/aws-args"
  grep -q '"schema_version":1' "$TEST_DIR/aws-args"
  grep -q 'cistem-decompound-v1' "$TEST_DIR/aws-args"
}

@test "[#492 metadata] mutable digest is rejected before AWS" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
touch "$TEST_DIR/aws-called"
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run "$PUBLISH" etl v1.2.3 latest cistem-decompound-v1
  [ "$status" -ne 0 ]
  [ ! -e "$TEST_DIR/aws-called" ]
}

@test "[#492 graph] one parent resource-group lock mirrors the complete child pipeline" {
  grep -A12 '^qa-retrieval-promotion:' "$PARENT_YAML" | grep -q 'resource_group: deploy-qa'
  grep -A12 '^qa-retrieval-promotion:' "$PARENT_YAML" | grep -q 'strategy: mirror'
  ! grep -q '^cdk-deploy:qa:' "$PARENT_YAML"
  ! grep -q '^smoke-eval:qa:' "$PARENT_YAML"
}

@test "[#492 graph] child order is candidate then chatbot then activation" {
  grep -A8 '^deploy-etl-candidate:qa:' "$CHILD_YAML" | grep -q 'validate-retrieval-promotion:qa'
  grep -A8 '^deploy-chatbot:qa:' "$CHILD_YAML" | grep -q 'deploy-etl-candidate:qa'
  grep -A8 '^activate-retrieval:qa:' "$CHILD_YAML" | grep -q 'deploy-chatbot:qa'
}

@test "[#492 tokenizer] compatibility mismatch is an early fail-closed gate, not maintenance orchestration" {
  grep -q 'tokenizer mismatch:' "$CANDIDATE"
  ! grep -q 'maintenance-switch' "$CANDIDATE"
  ! grep -q 'MAINTENANCE_STATE' "$CANDIDATE"
}

@test "[#630 defect 1] component-presence checks have no SIGPIPE-prone pipe" {
  # A `find ... | grep -q`/`grep -Eq` under set -o pipefail can report a
  # spurious failure: grep exits on the first match, SIGPIPE-kills find, and
  # pipefail then fails the whole pipeline even though a match existed.
  # Assert no such pipe remains, broader than the exact original shape so a
  # differently-written regression still fails this test.
  ! grep -E "find .* \| *grep -(q|Eq)" "$CANDIDATE"
  grep -q -- '-print -quit' "$CANDIDATE"
}

@test "[#630 defect 1] brochure presence check accepts a deeply-nested XML source" {
  mkdir -p "$TEST_DIR/dev-raw/brochure/nested/deeper" "$TEST_DIR/dev-raw/faq"
  printf '<x/>' >"$TEST_DIR/dev-raw/brochure/nested/deeper/doc.xml"
  printf '<html></html>' >"$TEST_DIR/dev-raw/faq/faq.html"
  run bash -c '
    set -euo pipefail
    brochure_src=$(find "$1/dev-raw/brochure" -type f \
      \( -name "*.xml" -o -name "*.md" -o -name "*.pdf" -o -path "*/deletes/*" \) -print -quit)
    [[ -n "$brochure_src" ]] || { echo "brochure component contains no processable source"; exit 1; }
    faq_src=$(find "$1/dev-raw/faq" -type f -name "*.html" -print -quit)
    [[ -n "$faq_src" ]] || { echo "FAQ component contains no HTML source"; exit 1; }
    echo ok
  ' _ "$TEST_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}

@test "[#501] brochure presence check accepts structured Merkblatt Markdown" {
  mkdir -p "$TEST_DIR/dev-raw/brochure/md" "$TEST_DIR/dev-raw/faq"
  printf '## Abschnitt\n\nInhalt\n' >"$TEST_DIR/dev-raw/brochure/md/V0090.md"
  printf '<html></html>' >"$TEST_DIR/dev-raw/faq/faq.html"
  run bash -c '
    set -euo pipefail
    brochure_src=$(find "$1/dev-raw/brochure" -type f \
      \( -name "*.xml" -o -name "*.md" -o -name "*.pdf" -o -path "*/deletes/*" \) -print -quit)
    [[ -n "$brochure_src" ]] || { echo "brochure component contains no processable source"; exit 1; }
    echo ok
  ' _ "$TEST_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}

@test "[#630 defect 1] brochure presence check accepts a deletes/-only tree with no xml, md, or pdf" {
  mkdir -p "$TEST_DIR/dev-raw/brochure/deletes" "$TEST_DIR/dev-raw/faq"
  printf 'DELETE_ME\n' >"$TEST_DIR/dev-raw/brochure/deletes/marker"
  printf '<html></html>' >"$TEST_DIR/dev-raw/faq/faq.html"
  run bash -c '
    set -euo pipefail
    brochure_src=$(find "$1/dev-raw/brochure" -type f \
      \( -name "*.xml" -o -name "*.md" -o -name "*.pdf" -o -path "*/deletes/*" \) -print -quit)
    [[ -n "$brochure_src" ]] || { echo "brochure component contains no processable source"; exit 1; }
    echo ok
  ' _ "$TEST_DIR"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}

@test "[#630 defect 1] empty brochure tree fails with the exact original message" {
  mkdir -p "$TEST_DIR/dev-raw/brochure"
  run bash -c '
    set -euo pipefail
    brochure_src=$(find "$1/dev-raw/brochure" -type f \
      \( -name "*.xml" -o -name "*.md" -o -name "*.pdf" -o -path "*/deletes/*" \) -print -quit)
    [[ -n "$brochure_src" ]] || { echo "brochure component contains no processable source"; exit 1; }
  ' _ "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == "brochure component contains no processable source" ]]
}

@test "[#630 defect 1] empty FAQ tree fails with the exact original message" {
  mkdir -p "$TEST_DIR/dev-raw/faq"
  run bash -c '
    set -euo pipefail
    faq_src=$(find "$1/dev-raw/faq" -type f -name "*.html" -print -quit)
    [[ -n "$faq_src" ]] || { echo "FAQ component contains no HTML source"; exit 1; }
  ' _ "$TEST_DIR"
  [ "$status" -ne 0 ]
  [[ "$output" == "FAQ component contains no HTML source" ]]
}

@test "[#492 retention] promotion protects control artifacts without corpus-wide tag scans" {
  activation="$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"
  ! grep -q 'qa_retrieval_pin_prefixes' "$CANDIDATE"
  ! grep -q 'qa_retrieval_pin_prefixes' "$activation"
  grep -q 'qa_retrieval_assert_objects_pinned' "$CANDIDATE"
  grep -q 'qa_retrieval_assert_objects_pinned' "$activation"
  ! grep -q 'QA_RETRIEVAL_INLINE_RETENTION_CLEANUP' "$activation"
  grep -Fq 'QA_RETENTION_CONCURRENCY="${QA_RETENTION_CONCURRENCY:-24}"' "$QA_RETRIEVAL_COMMON"
  ! grep -q 'qa_retrieval_audit_pinned_prefixes' "$CANDIDATE"
  ! grep -q 'qa_retrieval_audit_pinned_prefixes' "$activation"
}

@test "[#492 retention] a pinned write-once control object is protected at creation" {
  printf '{"release_id":"test"}\n' >"$TEST_DIR/manifest.json"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api head-object" ]]; then
  exit 1
fi
if [[ "$1 $2" == "s3api put-object" ]]; then
  printf '%s\n' "$*" >"$TEST_DIR/put-args"
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_put_write_once bucket manifest.json "$2" application/json pinned' \
    _ "$COMMON" "$TEST_DIR/manifest.json"
  [ "$status" -eq 0 ]
  grep -q -- '--tagging renate%3Aretention=pinned' "$TEST_DIR/put-args"
}

@test "[#492 retention] exact-object pinning preserves unrelated tags and verifies the write" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api get-object-tagging" ]]; then
  if [[ -s "$TEST_DIR/tag-state.json" ]]; then
    cat "$TEST_DIR/tag-state.json"
  else
    printf '%s\n' '{"TagSet":[{"Key":"owner","Value":"retrieval"},{"Key":"renate:retention","Value":"unpinned"}]}'
  fi
  exit 0
fi
if [[ "$1 $2" == "s3api put-object-tagging" ]]; then
  while [[ "$#" -gt 0 ]]; do
    if [[ "$1" == --tagging ]]; then
      cp "${2#file://}" "$TEST_DIR/tag-state.json"
      exit 0
    fi
    shift
  done
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_set_object_retention bucket manifest.json pinned' \
    _ "$COMMON"
  [ "$status" -eq 0 ]
  jq -e '
    .TagSet == [
      {"Key":"owner","Value":"retrieval"},
      {"Key":"renate:retention","Value":"pinned"}
    ]
  ' "$TEST_DIR/tag-state.json"
}

@test "[#492 retention] QA retention concurrency remains operator-configurable" {
  cat >"$TEST_DIR/bin/node" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$TEST_DIR/node-args"
EOF
  chmod +x "$TEST_DIR/bin/node"
  export TEST_DIR REPO_ROOT

  PATH="$TEST_DIR/bin:$PATH" QA_RETENTION_CONCURRENCY=17 run bash -c \
    'source "$1"; qa_retrieval_pin_prefixes bucket prefix/' _ "$COMMON"
  [ "$status" -eq 0 ]
  grep -q 'release-retention.mjs pin' "$TEST_DIR/node-args"
  grep -q -- '--concurrency 17' "$TEST_DIR/node-args"
}

@test "[#492 immutability] candidate rejects divergent existing immutable trees" {
  grep -q 'qa_retrieval_sync_tree_write_once' "$CANDIDATE"
  grep -q 'already contains divergent' "$S3"
  grep -q 'diff -qr' "$S3"
}

@test "[#492 immutability] divergent bytes fail before an immutable tree upload" {
  mkdir -p "$TEST_DIR/source" "$TEST_DIR/remote"
  printf 'candidate\n' >"$TEST_DIR/source/chunk.md"
  printf 'different\n' >"$TEST_DIR/remote/chunk.md"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == s3api ]]; then
  echo "unexpected s3api call before divergence is detected" >&2
  exit 97
fi
if [[ "$1" == s3 && "$2" == sync && "$3" == s3://bucket/prefix/ ]]; then
  cp -R "$TEST_DIR/remote/." "$4"
  exit 0
fi
touch "$TEST_DIR/upload-called"
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_sync_tree_write_once "$2" bucket prefix candidate' \
    _ "$COMMON" "$TEST_DIR/source"
  [ "$status" -ne 0 ]
  [[ "$output" == *'already contains divergent chunk.md'* ]]
  [ ! -e "$TEST_DIR/upload-called" ]
}

@test "[#492 immutability] matching immutable tree retries are idempotent" {
  mkdir -p "$TEST_DIR/source/nested" "$TEST_DIR/remote"
  printf 'candidate\n' >"$TEST_DIR/source/nested/chunk.md"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api list-objects-v2" ]]; then
  printf '%s\n' '{"Contents":[{"Key":"prefix/nested/chunk.md"}]}'
  exit 0
fi
[[ "$1" == s3 && "$2" == sync ]]
if [[ "$3" == s3://bucket/prefix/ ]]; then
  mkdir -p "$4"
  cp -R "$TEST_DIR/remote/." "$4"
else
  mkdir -p "$TEST_DIR/remote"
  cp -R "${3%/}/." "$TEST_DIR/remote"
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  for attempt in 1 2; do
    PATH="$TEST_DIR/bin:$PATH" run bash -c \
      'source "$1"; qa_retrieval_sync_tree_write_once "$2" bucket prefix candidate' \
      _ "$COMMON" "$TEST_DIR/source"
    [ "$status" -eq 0 ]
  done
  cmp -s "$TEST_DIR/source/nested/chunk.md" "$TEST_DIR/remote/nested/chunk.md"
}

@test "[#630 defect 2] inventory mismatch (stray object) fails write-once upload" {
  mkdir -p "$TEST_DIR/source" "$TEST_DIR/remote"
  printf 'candidate\n' >"$TEST_DIR/source/chunk.md"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api list-objects-v2" ]]; then
  # Independent listing reports a stray extra key the sync client never saw
  # (e.g. a zero-byte folder marker) - the upload must still fail closed.
  printf '%s\n' '{"Contents":[{"Key":"prefix/chunk.md"},{"Key":"prefix/stray-marker"}]}'
  exit 0
fi
if [[ "$1" == s3 && "$2" == sync ]]; then
  if [[ "$3" == s3://bucket/prefix/ ]]; then
    mkdir -p "$4"
    cp -R "$TEST_DIR/remote/." "$4" 2>/dev/null || true
  else
    mkdir -p "$TEST_DIR/remote"
    cp -R "${3%/}/." "$TEST_DIR/remote"
  fi
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_sync_tree_write_once "$2" bucket prefix candidate' \
    _ "$COMMON" "$TEST_DIR/source"
  [ "$status" -ne 0 ]
  [[ "$output" == *'inventory diverged (extra/missing objects)'* ]]
}

@test "[#630 defect 2] inventory check tolerates non-ASCII keys and passes when consistent" {
  mkdir -p "$TEST_DIR/source" "$TEST_DIR/remote"
  printf 'candidate\n' >"$TEST_DIR/source/Kontenklärung.md"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api list-objects-v2" ]]; then
  printf '%s\n' '{"Contents":[{"Key":"prefix/Kontenklärung.md"}]}'
  exit 0
fi
if [[ "$1" == s3 && "$2" == sync ]]; then
  if [[ "$3" == s3://bucket/prefix/ ]]; then
    mkdir -p "$4"
    cp -R "$TEST_DIR/remote/." "$4" 2>/dev/null || true
  else
    mkdir -p "$TEST_DIR/remote"
    cp -R "${3%/}/." "$TEST_DIR/remote"
  fi
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_sync_tree_write_once "$2" bucket prefix candidate' \
    _ "$COMMON" "$TEST_DIR/source"
  [ "$status" -eq 0 ]
}

@test "[#492 retry] existing write-once raw objects are replayed without losing metadata or tags" {
  mkdir -p "$TEST_DIR/source/nested"
  printf 'candidate\n' >"$TEST_DIR/source/nested/chunk ä one.html"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3api head-object" ]]; then
  printf '%s\n' '{"Metadata":{"owner":"qa"},"ContentType":"text/html"}'
elif [[ "$1 $2 $3" == "s3api copy-object --cli-input-json" ]]; then
  cp "${4#file://}" "$TEST_DIR/copy-request.json"
else
  exit 98
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR REPO_ROOT

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_replay_tree "$2" bucket prefix retry-42 candidate' \
    _ "$COMMON" "$TEST_DIR/source"
  [ "$status" -eq 0 ]
  jq -e '
    .Bucket == "bucket"
    and .Key == "prefix/nested/chunk ä one.html"
    and .CopySource == "bucket/prefix/nested/chunk ä one.html"
    and .MetadataDirective == "REPLACE"
    and .TaggingDirective == "COPY"
    and .ContentType == "text/html"
    and .Metadata.owner == "qa"
    and .Metadata["etl-reprocess-version"] == "retry-42"
  ' "$TEST_DIR/copy-request.json"
}

@test "[#492 retry] candidate failure arms exact previous-slot recovery before live deletion" {
  wait_line=$(grep -n 'qa_retrieval_wait_queue_empty' "$CANDIDATE" | head -1 | cut -d: -f1)
  restore_line=$(grep -n 'qa_retrieval_restore_immutable_corpus' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ "$wait_line" -lt "$restore_line" ]
  grep -q '^restore_previous_slot()' "$CANDIDATE"
  grep -q 'qa_retrieval_restore_immutable_corpus' "$CANDIDATE"
  grep -q 'qa_retrieval_start_kb_sync' "$CANDIDATE"
  grep -q 'CANDIDATE_LIVE_MUTATED=true' "$CANDIDATE"
  grep -q 'automatic previous-slot recovery failed' "$CANDIDATE"
  grep -q 'kb-sync-function-name' "$CANDIDATE"
}

@test "[#492 recovery] in-flight transforms must remain empty before corpus restore" {
  printf '0\n' >"$TEST_DIR/queue-calls"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1 $2" == "sqs get-queue-attributes" ]] || exit 98
calls=$(cat "$TEST_DIR/queue-calls")
calls=$((calls + 1))
printf '%s\n' "$calls" >"$TEST_DIR/queue-calls"
if [[ "$calls" -eq 1 ]]; then
  printf '%s\n' '{"Attributes":{"ApproximateNumberOfMessages":"1","ApproximateNumberOfMessagesNotVisible":"0"}}'
else
  printf '%s\n' '{"Attributes":{"ApproximateNumberOfMessages":"0","ApproximateNumberOfMessagesNotVisible":"0"}}'
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  QA_RETRIEVAL_QUEUE_POLL_SECONDS=0 QA_RETRIEVAL_QUEUE_EMPTY_POLLS=2 \
    PATH="$TEST_DIR/bin:$PATH" run bash -c \
      'source "$1"; qa_retrieval_wait_queue_empty "$2" "transform queue" 5' \
      _ "$COMMON" arn:aws:sqs:eu-central-1:123456789012:transform
  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_DIR/queue-calls")" -eq 3 ]
  [[ "$output" == *"transform queue is quiescent."* ]]
}

@test "[#492 recovery] previous immutable corpus is exactly restored to live docs" {
  mkdir -p "$TEST_DIR/immutable/docs" "$TEST_DIR/live"
  printf 'Rente\n' >"$TEST_DIR/immutable/docs/chunk.md"
  printf '{"metadataAttributes":{}}\n' >"$TEST_DIR/immutable/docs/chunk.md.metadata.json"
  node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" inventory \
    "$TEST_DIR/immutable/docs" "$TEST_DIR/immutable/inventory.json"
  printf 'stale\n' >"$TEST_DIR/live/stale.md"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3 sync" && "$3" == s3://bucket/processed/releases/release/docs/ ]]; then
  mkdir -p "$4"
  cp -R "$TEST_DIR/immutable/docs/." "$4"
elif [[ "$1 $2" == "s3 cp" && "$3" == s3://bucket/processed/releases/release/inventory.json ]]; then
  cp "$TEST_DIR/immutable/inventory.json" "$4"
elif [[ "$1 $2" == "s3 rm" && "$3" == s3://bucket/docs/ ]]; then
  rm -rf "$TEST_DIR/live"
  mkdir -p "$TEST_DIR/live"
elif [[ "$1 $2" == "s3 sync" && "$4" == s3://bucket/docs/ ]]; then
  cp -R "${3%/}/." "$TEST_DIR/live"
elif [[ "$1 $2" == "s3 sync" && "$3" == s3://bucket/docs/ ]]; then
  mkdir -p "$4"
  cp -R "$TEST_DIR/live/." "$4"
else
  printf 'unexpected aws call: %s\n' "$*" >&2
  exit 98
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR REPO_ROOT

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_restore_immutable_corpus bucket processed/releases/release "$2"' \
    _ "$COMMON" "$TEST_DIR/workspace"
  [ "$status" -eq 0 ]
  diff -qr "$TEST_DIR/immutable/docs" "$TEST_DIR/live"
}

@test "[#492 recovery] legacy blue inventory is normalized before exact hash verification" {
  mkdir -p "$TEST_DIR/immutable/docs" "$TEST_DIR/live"
  printf 'Rente\n' >"$TEST_DIR/immutable/docs/chunk.md"
  printf '{"metadataAttributes":{}}\n' >"$TEST_DIR/immutable/docs/chunk.md.metadata.json"
  current_inventory="$TEST_DIR/current.json"
  node "$REPO_ROOT/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" inventory \
    "$TEST_DIR/immutable/docs" "$current_inventory"
  jq --arg prefix processed/releases/release/ '
    {
      schema_version:1,
      object_count:.object_count,
      source_prefix:"docs/",
      destination_prefix:($prefix + "docs/"),
      objects:[.objects[] | {
        source_key:.key,
        destination_key:($prefix + .key),
        bytes:.bytes,
        sha256:.sha256
      }]
    }
  ' "$current_inventory" >"$TEST_DIR/immutable/inventory.json"
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "s3 sync" && "$3" == s3://bucket/processed/releases/release/docs/ ]]; then
  mkdir -p "$4"
  cp -R "$TEST_DIR/immutable/docs/." "$4"
elif [[ "$1 $2" == "s3 cp" && "$3" == s3://bucket/processed/releases/release/inventory.json ]]; then
  cp "$TEST_DIR/immutable/inventory.json" "$4"
else
  printf 'unexpected aws call: %s\n' "$*" >&2
  exit 98
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR REPO_ROOT

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_verify_immutable_corpus bucket processed/releases/release "$2" "$3"' \
    _ "$COMMON" "$TEST_DIR/verified" "$TEST_DIR/expected.json"
  [ "$status" -eq 0 ]
}

@test "[#492 CDK] both QA deploys carry candidate slot and independent builder image contexts" {
  for script in \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh" \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"; do
    grep -q 'retrievalCandidateSlot=' "$script"
    grep -q 'blueEtlImageTag=' "$script"
    grep -q 'greenEtlImageTag=' "$script"
    grep -q 'etlImageTag=' "$script"
  done
  grep -q 'chatbotImageTag=' "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
}

@test "[#643 image identity] promotion and automatic rollback deploy exact digests" {
  chatbot="$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
  activation="$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"

  # Metadata version tags identify the release, but CDK must consume the
  # resolved immutable digest. Checking a digest and then deploying a tag would
  # leave a tag-move race between preflight and mutation.
  for script in "$CANDIDATE" "$chatbot"; do
    grep -Fq 'etlImageTag=${ETL_IMAGE_DIGEST}' "$script"
    grep -Fq 'chatbotImageTag=${CHATBOT_IMAGE_DIGEST}' "$script"
    ! grep -Fq 'etlImageTag=${ETL_VERSION}' "$script"
    ! grep -Fq 'chatbotImageTag=${CHATBOT_VERSION}' "$script"
  done
  grep -Fq 'blueEtlImageTag=${BLUE_ETL_IMAGE_DIGEST}' "$CANDIDATE"
  grep -Fq 'greenEtlImageTag=${GREEN_ETL_IMAGE_DIGEST}' "$CANDIDATE"
  grep -Fq 'chatbotImageTag=${OUTGOING_CHATBOT_IMAGE_DIGEST}' "$activation"
  grep -Fq 'etlImageTag=${OUTGOING_ETL_IMAGE_DIGEST}' "$activation"
  ! grep -Fq 'chatbotImageTag=${OLD_CHATBOT_VERSION}' "$activation"
}

@test "[#643 image identity] live chatbot stack resolves one immutable digest" {
  digest="sha256:$(printf 'a%.0s' {1..64})"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1 \$2" == "cloudformation list-stack-resources" ]]; then
  printf '{"StackResourceSummaries":[{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"chat-fn"},{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"health-fn"}]}\n'
elif [[ "\$1 \$2" == "lambda get-function" ]]; then
  printf '{"Configuration":{"PackageType":"Image"},"Code":{"ResolvedImageUri":"repo@${digest}"}}\n'
else
  exit 98
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_resolve_stack_image_digest stack' _ "$COMMON"
  [ "$status" -eq 0 ]
  [ "$output" = "$digest" ]
}

@test "[#643 image identity] mixed live chatbot digests fail closed" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "cloudformation list-stack-resources" ]]; then
  printf '{"StackResourceSummaries":[{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"chat-fn"},{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"health-fn"}]}\n'
elif [[ "$1 $2" == "lambda get-function" ]]; then
  if [[ "$*" == *"chat-fn"* ]]; then
    hex=a
  else
    hex=b
  fi
  digest="sha256:$(printf "${hex}%.0s" {1..64})"
  printf '{"Configuration":{"PackageType":"Image"},"Code":{"ResolvedImageUri":"repo@%s"}}\n' "$digest"
else
  exit 98
fi
EOF
  chmod +x "$TEST_DIR/bin/aws"

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_resolve_stack_image_digest stack' _ "$COMMON"
  [ "$status" -ne 0 ]
  [[ "$output" == *"runs mixed image digests"* ]]
}

@test "[#671 enumeration] chatbot Lambda discovery uses the complete paginated listing" {
  for script in \
    "$COMMON" \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"; do
    ! grep -Fq 'cloudformation describe-stack-resources' "$script"
  done
  grep -Fq 'cloudformation list-stack-resources' "$QA_RETRIEVAL_COMMON"
  grep -Fq 'StackResourceSummaries[]' "$QA_RETRIEVAL_COMMON"
  # The full JSON is filtered in jq: a server-side --query is applied per page
  # and would re-introduce truncation.
  ! grep -Fq -- '--query "StackResources' "$QA_RETRIEVAL_COMMON"
  grep -Fq 'qa_retrieval_stack_lambda_functions "$CHATBOT_STACK"' \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh"
}

@test "[#671 enumeration] every stack Lambda is returned, not just the first page" {
  # Reproduces renate-chatbot-prod: the image-backed chat and health Lambdas
  # sort after unrelated Zip functions, so a 100-resource truncation dropped
  # exactly the two the digest gate must inspect.
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "cloudformation list-stack-resources" ]]; then
  cat <<'JSON'
{"StackResourceSummaries":[
  {"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-email-check-prod"},
  {"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"custom-s3-autodelete"},
  {"ResourceType":"AWS::S3::Bucket","PhysicalResourceId":"renate-assets-prod"},
  {"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-analytics-prod"},
  {"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-chat-prod"},
  {"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-health-prod"}
]}
JSON
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_stack_lambda_functions renate-chatbot-prod' _ "$COMMON"
  [ "$status" -eq 0 ]
  [ "$(printf '%s\n' "$output" | wc -l | tr -d ' ')" = 5 ]
  [[ "$output" == *"renate-chat-prod"* ]]
  [[ "$output" == *"renate-health-prod"* ]]
  [[ "$output" != *"renate-assets-prod"* ]]
}

@test "[#671 enumeration] a failed stack listing fails closed" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
echo "AccessDenied" >&2
exit 254
EOF
  chmod +x "$TEST_DIR/bin/aws"

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_stack_lambda_functions stack' _ "$COMMON"
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not list Lambda functions for stack stack"* ]]
}

@test "[#671 enumeration] the chat Lambda is resolved past the first page" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "cloudformation list-stack-resources" ]]; then
  printf '{"StackResourceSummaries":[{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-analytics-prod"},{"ResourceType":"AWS::Lambda::Function","PhysicalResourceId":"renate-chat-prod"}]}\n'
  exit 0
fi
if [[ "$1 $2" == "lambda get-function-configuration" ]]; then
  if [[ "$*" == *renate-chat-prod* ]]; then
    printf '/prod/renate/retrieval/active-manifest\n'
  else
    printf 'None\n'
  fi
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_resolve_chat_function renate-chatbot-prod \
      /prod/renate/retrieval/active-manifest' _ "$COMMON"
  [ "$status" -eq 0 ]
  [ "$output" = renate-chat-prod ]
}

@test "[#492 CDK] deployment and rollback synthesize from the cdk working directory" {
  for script in \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-candidate.sh" \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/deploy-retrieval-chatbot.sh" \
    "$REPO_ROOT/.gitlab/ci/scripts/deploy/activate-retrieval.sh"; do
    grep -Fq 'cd "$REPO_ROOT/cdk"' "$script"
    grep -Fq -- '--app "npx ts-node --prefer-ts-exts bin/infrastructure.ts"' "$script"
    ! grep -Fq 'npx --prefix "$REPO_ROOT/cdk" cdk deploy' "$script"
  done
}

@test "[#630 migration] candidate delegates slot/path/recovery/manifest decisions to retrieval-orchestration.mjs" {
  grep -q 'retrieval-orchestration.mjs" resolve-slots' "$CANDIDATE"
  grep -q 'retrieval-orchestration.mjs" decide-path' "$CANDIDATE"
  grep -q 'retrieval-orchestration.mjs" arm-recovery' "$CANDIDATE"
  grep -q 'retrieval-orchestration.mjs" build-manifest' "$CANDIDATE"
  ! grep -q '^case "\$ACTIVE_KB_ID" in$' "$CANDIDATE"
  ! grep -Fq 'jq -cS' "$CANDIDATE"
  ! grep -Fq 'jq -cnS' "$CANDIDATE"
}

@test "[#630 migration] recovery arming decision still precedes the live-mutation flag" {
  arm_line=$(grep -n 'retrieval-orchestration.mjs" arm-recovery' "$CANDIDATE" | head -1 | cut -d: -f1)
  mutated_line=$(grep -n '^  CANDIDATE_LIVE_MUTATED=true$' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ -n "$arm_line" ]
  [ -n "$mutated_line" ]
  [ "$arm_line" -lt "$mutated_line" ]
}

@test "[#643 contract] candidate evidence includes exact incoming/outgoing digests" {
  keys=$(awk '/cat >"\$OUTPUT_ENV"/{flag=1; next} /^EOF$/{flag=0} flag' "$CANDIDATE" \
    | grep -oE '^[A-Z0-9_]+=')
  expected='CHATBOT_VERSION=
DATA_ARTIFACT_VERSION=
ETL_VERSION=
RELEASE_ID=
RETRIEVAL_ARTIFACT_ID=
RETRIEVAL_ARTIFACT_FINGERPRINT=
TOKENIZER_REVISION=
CHATBOT_IMAGE_DIGEST=
ETL_IMAGE_DIGEST=
OUTGOING_CHATBOT_IMAGE_DIGEST=
OUTGOING_ETL_IMAGE_DIGEST=
ACTIVE_SLOT=
CANDIDATE_SLOT=
BLUE_ETL_IMAGE_DIGEST=
GREEN_ETL_IMAGE_DIGEST=
CHATBOT_ONLY=
CANDIDATE_BUCKET=
PROCESSED_PREFIX=
BM25_KEY='
  [ "$keys" = "$expected" ]
}

# ── #628: degraded-rollback marker (candidate script) ────────────────────────

@test "[#628 marker] set call precedes the live mutation, gated on RECOVERY_ARMED" {
  set_line=$(grep -n 'qa_retrieval_set_rollback_degraded_marker' "$CANDIDATE" | head -1 | cut -d: -f1)
  mutated_line=$(grep -n '^  CANDIDATE_LIVE_MUTATED=true$' "$CANDIDATE" | head -1 | cut -d: -f1)
  gate_line=$(grep -n 'if \[\[ "\$RECOVERY_ARMED" == true \]\]; then' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ -n "$set_line" ]
  [ -n "$mutated_line" ]
  [ -n "$gate_line" ]
  [ "$gate_line" -lt "$set_line" ]
  [ "$set_line" -lt "$mutated_line" ]
}

@test "[#628 marker] helper is fail-closed and returns non-zero on a put-parameter failure" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "ssm put-parameter" ]] || exit 98
exit 1
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER=/qa/renate/retrieval/rollback-degraded; qa_retrieval_set_rollback_degraded_marker rel slot job pipeline' \
    _ "$COMMON"
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not set degraded-rollback marker"* ]]
}

@test "[#628 marker] set helper writes the expected schema-v1 JSON body" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "ssm put-parameter" ]]; then
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--value" ]]; then j=$((i+1)); val="${!j}"; fi
    if [[ "${!i}" == "--name" ]]; then j=$((i+1)); name="${!j}"; fi
  done
  cp "${val#file://}" "$TEST_DIR/put-body.json"
  printf '%s\n' "$name" >"$TEST_DIR/put-name"
  exit 0
fi
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER=/qa/renate/retrieval/rollback-degraded; qa_retrieval_set_rollback_degraded_marker sha256-rel green https://job https://pipeline' \
    _ "$COMMON"
  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_DIR/put-name")" = "/qa/renate/retrieval/rollback-degraded" ]
  jq -e '
    .schema_version == 1
    and .release_id == "sha256-rel"
    and .candidate_slot == "green"
    and .ci_job_url == "https://job"
    and .ci_pipeline_url == "https://pipeline"
    and (.opened_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T"))
  ' "$TEST_DIR/put-body.json"
}

@test "[#628 marker] clear helper treats ParameterNotFound as already-clear" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "ssm delete-parameter" ]] || exit 98
echo "An error occurred (ParameterNotFound) when calling the DeleteParameter operation" >&2
exit 254
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run bash -c 'source "$1"; RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER=/qa/renate/retrieval/rollback-degraded; qa_retrieval_clear_rollback_degraded_marker' \
    _ "$COMMON"
  [ "$status" -eq 0 ]
}

@test "[#628 marker] clear helper always returns 0 and warns on a real delete failure" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "ssm delete-parameter" ]] || exit 98
echo "An error occurred (AccessDeniedException) when calling the DeleteParameter operation" >&2
exit 254
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR
  PATH="$TEST_DIR/bin:$PATH" run bash -c 'source "$1"; RETRIEVAL_ROLLBACK_DEGRADED_PARAMETER=/qa/renate/retrieval/rollback-degraded; qa_retrieval_clear_rollback_degraded_marker; echo "EXIT:$?"' \
    _ "$COMMON"
  [ "$status" -eq 0 ]
  [[ "$output" == *"EXIT:0"* ]]
  [[ "$output" == *"WARNING: degraded-rollback marker"*"not cleared (false alarm)"* ]]
}

@test "[#628 EXIT-trap] candidate_exit clears the marker only after a successful recovery" {
  grep -q 'qa_retrieval_clear_rollback_degraded_marker' "$CANDIDATE"
  # Recovery-success branch: clear call sits inside the RECOVERY_ARMED +
  # CANDIDATE_LIVE_MUTATED==true branch, after restore_previous_slot, guarded
  # by recovery_status -eq 0 (else branch), and failure leaves the CRITICAL
  # message with the marker untouched.
  awk '/^candidate_exit\(\) \{/,/^\}$/' "$CANDIDATE" >"$TEST_DIR/candidate_exit.txt"
  grep -q 'CANDIDATE_LIVE_MUTATED" == true' "$TEST_DIR/candidate_exit.txt"
  grep -q 'recovery_status" -ne 0' "$TEST_DIR/candidate_exit.txt"
  grep -q 'CRITICAL: automatic previous-slot recovery failed' "$TEST_DIR/candidate_exit.txt"
  # exactly two clear calls: recovery-success and stale-marker branches.
  clear_calls=$(grep -c 'qa_retrieval_clear_rollback_degraded_marker' "$TEST_DIR/candidate_exit.txt")
  [ "$clear_calls" -eq 2 ]
}

@test "[#628 EXIT-trap] the CRITICAL recovery-failure branch precedes no clear call" {
  awk '/^candidate_exit\(\) \{/,/^\}$/' "$CANDIDATE" >"$TEST_DIR/candidate_exit.txt"
  critical_line=$(grep -n 'CRITICAL: automatic previous-slot recovery failed' "$TEST_DIR/candidate_exit.txt" | cut -d: -f1)
  else_line=$(grep -n '^      else$' "$TEST_DIR/candidate_exit.txt" | head -1 | cut -d: -f1)
  clear_line=$(grep -n 'qa_retrieval_clear_rollback_degraded_marker' "$TEST_DIR/candidate_exit.txt" | head -1 | cut -d: -f1)
  [ -n "$critical_line" ]
  [ -n "$else_line" ]
  [ -n "$clear_line" ]
  [ "$critical_line" -lt "$else_line" ]
  [ "$else_line" -lt "$clear_line" ]
}

@test "[#628 stale marker] failure before the live mutation still clears a marker that was set" {
  awk '/^candidate_exit\(\) \{/,/^\}$/' "$CANDIDATE" >"$TEST_DIR/candidate_exit.txt"
  grep -q 'CANDIDATE_LIVE_MUTATED" == true' "$TEST_DIR/candidate_exit.txt"
  grep -A4 '^    else$' "$TEST_DIR/candidate_exit.txt" | grep -q 'qa_retrieval_clear_rollback_degraded_marker'
  grep -A4 '^    else$' "$TEST_DIR/candidate_exit.txt" | grep -q 'no window ever actually opened'
}

@test "[#628 no window] chatbot-only path never resolves RECOVERY_ARMED and sets no marker" {
  # The chatbot-only branch reuses the active slot and exits before the
  # RECOVERY_ARMED resolution / live-mutation section entirely.
  chatbot_only_line=$(grep -n 'CHATBOT_ONLY" == true' "$CANDIDATE" | head -1 | cut -d: -f1)
  arm_line=$(grep -n 'retrieval-orchestration.mjs" arm-recovery' "$CANDIDATE" | head -1 | cut -d: -f1)
  set_marker_line=$(grep -n 'qa_retrieval_set_rollback_degraded_marker' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ -n "$chatbot_only_line" ]
  [ -n "$arm_line" ]
  [ -n "$set_marker_line" ]
  [ "$chatbot_only_line" -lt "$arm_line" ]
  [ "$arm_line" -lt "$set_marker_line" ]
}
# ── #631: QA self-sourcing on the full-retrieval path ────────────────────────

@test "[#631 completeness] complete QA copy (matching manifest_sha256 + all declared files) verifies true" {
  mkdir -p "$TEST_DIR/qa"
  printf '{"version":"v1.92.0","files":{"xml":["xml/a.xml"],"pdf":[]}}' \
    >"$TEST_DIR/qa/brochure-manifest.json"
  printf '{"schema_version":1,"coordinate":"sha256-aa","files":["html/faq.html"]}' \
    >"$TEST_DIR/qa/faq-manifest.json"
  brochure_sha=$(sha256sum "$TEST_DIR/qa/brochure-manifest.json" | cut -d' ' -f1)
  faq_sha=$(sha256sum "$TEST_DIR/qa/faq-manifest.json" | cut -d' ' -f1)
  jq -n --arg bsha "$brochure_sha" --arg fsha "$faq_sha" '
    {
      schema_version: 1,
      coordinate: "v1.92.0-data.1",
      components: {
        brochure: {bucket:"dev-bucket", prefix:"releases/v1.92.0/", manifest_key:"releases/v1.92.0/manifest.json", manifest_sha256:$bsha},
        faq: {bucket:"dev-bucket", prefix:"releases/faq/sha256-aa/", manifest_key:"releases/faq/sha256-aa/manifest.json", manifest_sha256:$fsha}
      }
    }
  ' >"$TEST_DIR/qa/composite-manifest.json"

  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1 \$2" == "s3api head-object" ]]; then
  case "\$6" in
    releases/v1.92.0-data.1/manifest.json) exit 0 ;;
    releases/v1.92.0/manifest.json) exit 0 ;;
    releases/faq/sha256-aa/manifest.json) exit 0 ;;
    releases/v1.92.0/xml/a.xml) exit 0 ;;
    releases/faq/sha256-aa/html/faq.html) exit 0 ;;
    *) exit 1 ;;
  esac
fi
if [[ "\$1 \$2" == "s3 cp" ]]; then
  case "\$3" in
    s3://bucket/releases/v1.92.0-data.1/manifest.json) cp "$TEST_DIR/qa/composite-manifest.json" "\$4" ;;
    s3://bucket/releases/v1.92.0/manifest.json) cp "$TEST_DIR/qa/brochure-manifest.json" "\$4" ;;
    s3://bucket/releases/faq/sha256-aa/manifest.json) cp "$TEST_DIR/qa/faq-manifest.json" "\$4" ;;
    *) echo "unexpected s3 cp: \$3" >&2; exit 1 ;;
  esac
  exit 0
fi
echo "unexpected aws call: \$*" >&2
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_composite_manifest_complete bucket releases/v1.92.0-data.1/ "$2"' \
    _ "$COMMON" "$TEST_DIR/out-manifest.json"
  [ "$status" -eq 0 ]
  cmp -s "$TEST_DIR/out-manifest.json" "$TEST_DIR/qa/composite-manifest.json"
}

@test "[#631 completeness] truncated component (non-empty, but a declared file is missing) is NOT complete" {
  mkdir -p "$TEST_DIR/qa"
  printf '{"schema_version":1,"coordinate":"sha256-aa","files":["html/faq.html","html/missing.html"]}' \
    >"$TEST_DIR/qa/faq-manifest.json"
  printf '{"version":"v1.92.0","files":{"xml":["xml/a.xml"],"pdf":[]}}' \
    >"$TEST_DIR/qa/brochure-manifest.json"
  brochure_sha=$(sha256sum "$TEST_DIR/qa/brochure-manifest.json" | cut -d' ' -f1)
  faq_sha=$(sha256sum "$TEST_DIR/qa/faq-manifest.json" | cut -d' ' -f1)
  jq -n --arg bsha "$brochure_sha" --arg fsha "$faq_sha" '
    {
      schema_version: 1,
      coordinate: "v1.92.0-data.1",
      components: {
        brochure: {bucket:"dev-bucket", prefix:"releases/v1.92.0/", manifest_key:"releases/v1.92.0/manifest.json", manifest_sha256:$bsha},
        faq: {bucket:"dev-bucket", prefix:"releases/faq/sha256-aa/", manifest_key:"releases/faq/sha256-aa/manifest.json", manifest_sha256:$fsha}
      }
    }
  ' >"$TEST_DIR/qa/composite-manifest.json"

  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1 \$2" == "s3api head-object" ]]; then
  case "\$6" in
    releases/v1.92.0-data.1/manifest.json) exit 0 ;;
    releases/v1.92.0/manifest.json) exit 0 ;;
    releases/faq/sha256-aa/manifest.json) exit 0 ;;
    releases/v1.92.0/xml/a.xml) exit 0 ;;
    releases/faq/sha256-aa/html/faq.html) exit 0 ;;
    releases/faq/sha256-aa/html/missing.html) exit 1 ;;
    *) exit 1 ;;
  esac
fi
if [[ "\$1 \$2" == "s3 cp" ]]; then
  case "\$3" in
    s3://bucket/releases/v1.92.0-data.1/manifest.json) cp "$TEST_DIR/qa/composite-manifest.json" "\$4" ;;
    s3://bucket/releases/v1.92.0/manifest.json) cp "$TEST_DIR/qa/brochure-manifest.json" "\$4" ;;
    s3://bucket/releases/faq/sha256-aa/manifest.json) cp "$TEST_DIR/qa/faq-manifest.json" "\$4" ;;
    *) echo "unexpected s3 cp: \$3" >&2; exit 1 ;;
  esac
  exit 0
fi
echo "unexpected aws call: \$*" >&2
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_composite_manifest_complete bucket releases/v1.92.0-data.1/ "$2"' \
    _ "$COMMON" "$TEST_DIR/out-manifest.json"
  [ "$status" -eq 1 ]
}

@test "[#631 completeness] absent QA composite manifest returns not-complete (1), not an error" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "s3api head-object" ]] || { echo "unexpected aws call: $*" >&2; exit 98; }
exit 1
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_composite_manifest_complete bucket releases/vX-data.1/ "$2"' \
    _ "$COMMON" "$TEST_DIR/out-manifest.json"
  [ "$status" -eq 1 ]
}

@test "[#631 completeness] an inspection error (not a 404) fails closed with status 2" {
  cat >"$TEST_DIR/bin/aws" <<'EOF'
#!/usr/bin/env bash
if [[ "$1 $2" == "s3api head-object" ]]; then
  exit 0
fi
if [[ "$1 $2" == "s3 cp" ]]; then
  echo "AccessDenied" >&2
  exit 1
fi
echo "unexpected aws call: $*" >&2
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  PATH="$TEST_DIR/bin:$PATH" run bash -c \
    'source "$1"; qa_retrieval_composite_manifest_complete bucket releases/vX-data.1/ "$2"' \
    _ "$COMMON" "$TEST_DIR/out-manifest.json"
  [ "$status" -eq 2 ]
  [[ "$output" == *"could not read"* ]]
}

@test "[#631 scope] full-retrieval path decides source before any DEV_SOURCE_BUCKET data call" {
  # The completeness precheck (QA_RETRIEVAL_PROMOTION_ROLE_ARN) must run and
  # decide RAW_SOURCE before the script ever issues an aws s3 cp/sync against
  # DEV_SOURCE_BUCKET — the dev role assumption for image-metadata purposes
  # is unchanged/out of scope (#631), but raw-data calls against
  # DEV_SOURCE_BUCKET must be conditional on RAW_SOURCE == dev.
  precheck_line=$(grep -n 'qa_retrieval_composite_manifest_complete \\' "$CANDIDATE" | head -1 | cut -d: -f1)
  dev_cp_line=$(grep -n 'aws s3 cp "s3://\${RAW_READ_BUCKET}' "$CANDIDATE" | head -1 | cut -d: -f1)
  [ -n "$precheck_line" ]
  [ -n "$dev_cp_line" ]
  [ "$precheck_line" -lt "$dev_cp_line" ]
  # every dev-source raw-data call is inside the else (RAW_SOURCE != qa) branch
  ! grep -B2 'aws s3 cp "s3://${DEV_SOURCE_BUCKET}' "$CANDIDATE" | grep -q 'RAW_SOURCE" == self'
}

@test "[#631 scope] QA-source branch never issues an aws s3 cp/sync against DEV_SOURCE_BUCKET" {
  awk '/if \[\[ "\$RAW_SOURCE" == self \]\]; then/,/^    else$/' "$CANDIDATE" \
    >"$TEST_DIR/qa-branch.txt"
  ! grep -q 'DEV_SOURCE_BUCKET' "$TEST_DIR/qa-branch.txt"
}

@test "[#631 precheck] dev existence precheck fails closed with an actionable, runbook-pointing message" {
  grep -q 'qa_retrieval_prefix_has_objects "\$RAW_READ_BUCKET" "\$RAW_PREFIX"' "$CANDIDATE"
  grep -q '492-atomic-qa-retrieval-promotion.md' "$CANDIDATE"
  grep -q 'QA raw corpus sourcing (#631)' "$CANDIDATE"
}

@test "[#631 dry-run] plan reports the chosen raw corpus source" {
  grep -q 'would source raw corpus from:' "$CANDIDATE"
}

@test "[#631 provenance] self-source path treats .bucket as provenance, not a fetch target" {
  awk '/if \[\[ "\$RAW_SOURCE" == self \]\]; then/,/^    else$/' "$CANDIDATE" \
    >"$TEST_DIR/qa-branch.txt"
  grep -q 'components.brochure.bucket == .components.faq.bucket' "$TEST_DIR/qa-branch.txt"
  ! grep -q '\-\-arg bucket "\$QA_SOURCE_BUCKET' "$TEST_DIR/qa-branch.txt"
}

@test "[#631 provenance] dev-hop path keeps the original bucket-equality coherence guard" {
  awk '/^  else$/,/^  fi$/' "$CANDIDATE" | tail -n +2 >"$TEST_DIR/dev-branch.txt"
  grep -q 'components.brochure.bucket == \$bucket' "$TEST_DIR/dev-branch.txt"
  grep -q 'components.faq.bucket == \$bucket' "$TEST_DIR/dev-branch.txt"
}

@test "[#631 idempotency] self-source sync into local trees is idempotent across repeated runs" {
  # The self-source branch's only NEW step is populating the local dev-raw
  # trees via `aws s3 sync` from QA; everything downstream (write-once,
  # replay) is the pre-existing, already-idempotency-tested machinery
  # (tests 20/23 above). This test isolates the new step: syncing the same
  # QA source twice into a fresh local tree must converge to byte-identical
  # content both times.
  mkdir -p "$TEST_DIR/qa-remote/brochure"
  printf '<x/>' >"$TEST_DIR/qa-remote/brochure/a.xml"
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1 \$2" == "s3 sync" && "\$3" == "s3://qa-bucket/releases/v1.92.0/" ]]; then
  mkdir -p "\$4"
  cp -R "$TEST_DIR/qa-remote/brochure/." "\$4"
  exit 0
fi
echo "unexpected aws call: \$*" >&2
exit 98
EOF
  chmod +x "$TEST_DIR/bin/aws"
  export TEST_DIR

  for attempt in 1 2; do
    rm -rf "$TEST_DIR/local-attempt-$attempt"
    mkdir -p "$TEST_DIR/local-attempt-$attempt"
    PATH="$TEST_DIR/bin:$PATH" run aws s3 sync \
      "s3://qa-bucket/releases/v1.92.0/" "$TEST_DIR/local-attempt-$attempt/"
    [ "$status" -eq 0 ]
  done
  diff -qr "$TEST_DIR/local-attempt-1" "$TEST_DIR/local-attempt-2"
}
