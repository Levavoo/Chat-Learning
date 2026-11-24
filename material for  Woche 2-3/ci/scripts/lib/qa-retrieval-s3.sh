#!/usr/bin/env bash
# QA retrieval write-once, corpus, pinning, retention, and restore helpers.

# shellcheck source=qa-retrieval-common.sh disable=SC1091
source "${BASH_SOURCE[0]%/*}/qa-retrieval-common.sh"

qa_retrieval_put_write_once() {
  local bucket="$1" key="$2" body="$3" content_type="$4" existing
  local retention="${5:-unpinned}" enforce_existing_retention=false
  [[ "$#" -lt 5 ]] || enforce_existing_retention=true
  [[ "$retention" == pinned || "$retention" == unpinned ]] || {
    qa_retrieval_fail "invalid retention state ${retention} for s3://${bucket}/${key}"
    return 1
  }
  if aws s3api head-object --bucket "$bucket" --key "$key" >/dev/null 2>&1; then
    existing=$(mktemp)
    aws s3 cp "s3://${bucket}/${key}" "$existing" --only-show-errors
    cmp -s "$existing" "$body" || {
      rm -f "$existing"
      qa_retrieval_fail "write-once object s3://${bucket}/${key} already differs"
      return 1
    }
    rm -f "$existing"
    if [[ "$enforce_existing_retention" == true ]]; then
      qa_retrieval_set_object_retention "$bucket" "$key" "$retention"
    fi
    return 0
  fi
  aws s3api put-object \
    --bucket "$bucket" \
    --key "$key" \
    --body "$body" \
    --content-type "$content_type" \
    --checksum-algorithm SHA256 \
    --if-none-match '*' \
    --tagging "renate%3Aretention=${retention}" >/dev/null
}

# Update one immutable control object without scanning its entire release.
# Unrelated tags are preserved and the requested state is independently read
# back. Bulk immutable trees deliberately remain untagged: the S3 lifecycle
# rules expire only objects explicitly tagged `unpinned`, so a missing tag is
# fail-safe and cannot delete an active or rollback corpus.
qa_retrieval_set_object_retention() {
  local bucket="$1" key="$2" state="$3" tags next actual
  [[ "$state" == pinned || "$state" == unpinned ]] || {
    qa_retrieval_fail "invalid retention state ${state} for s3://${bucket}/${key}"
    return 1
  }
  tags=$(mktemp)
  next=$(mktemp)
  if ! aws s3api get-object-tagging --bucket "$bucket" --key "$key" >"$tags"; then
    rm -f "$tags" "$next"
    qa_retrieval_fail "could not read retention for s3://${bucket}/${key}"
    return 1
  fi
  actual=$(jq -r '.TagSet[]? | select(.Key == "renate:retention") | .Value' "$tags")
  if [[ "$actual" != "$state" ]]; then
    jq --arg state "$state" '
      {
        TagSet: (
          [.TagSet[]? | select(.Key != "renate:retention")]
          + [{Key:"renate:retention", Value:$state}]
        )
      }
    ' "$tags" >"$next"
    if ! aws s3api put-object-tagging --bucket "$bucket" --key "$key" \
      --tagging "file://${next}"; then
      rm -f "$tags" "$next"
      qa_retrieval_fail "could not set ${state} retention for s3://${bucket}/${key}"
      return 1
    fi
  fi
  if ! aws s3api get-object-tagging --bucket "$bucket" --key "$key" >"$tags"; then
    rm -f "$tags" "$next"
    qa_retrieval_fail "could not verify retention for s3://${bucket}/${key}"
    return 1
  fi
  actual=$(jq -r '.TagSet[]? | select(.Key == "renate:retention") | .Value' "$tags")
  rm -f "$tags" "$next"
  [[ "$actual" == "$state" ]] || {
    qa_retrieval_fail \
      "s3://${bucket}/${key} retention is ${actual:-missing}, expected ${state}"
    return 1
  }
}

qa_retrieval_assert_objects_pinned() {
  local bucket="$1" key tags actual
  shift
  tags=$(mktemp)
  for key in "$@"; do
    if ! aws s3api get-object-tagging --bucket "$bucket" --key "$key" >"$tags"; then
      rm -f "$tags"
      qa_retrieval_fail "could not verify pinned object s3://${bucket}/${key}"
      return 1
    fi
    actual=$(jq -r '.TagSet[]? | select(.Key == "renate:retention") | .Value' "$tags")
    if [[ "$actual" != pinned ]]; then
      rm -f "$tags"
      qa_retrieval_fail \
        "s3://${bucket}/${key} retention is ${actual:-missing}, expected pinned"
      return 1
    fi
  done
  rm -f "$tags"
}

qa_retrieval_sync_tree_write_once() {
  local source_dir="${1%/}" bucket="$2" prefix="${3%/}/" label="$4"
  local existing_dir verify_dir existing_file relative expected_keys listed_keys
  [[ -d "$source_dir" ]] || {
    qa_retrieval_fail "${label} source directory ${source_dir} is missing"
    return 1
  }

  existing_dir=$(mktemp -d)
  verify_dir=$(mktemp -d)
  if ! aws s3 sync "s3://${bucket}/${prefix}" "$existing_dir/" --only-show-errors; then
    rm -rf "$existing_dir" "$verify_dir"
    qa_retrieval_fail "could not inspect existing ${label} tree"
    return 1
  fi

  while IFS= read -r -d '' existing_file; do
    relative=${existing_file#"${existing_dir}/"}
    if [[ ! -f "${source_dir}/${relative}" ]] || \
      ! cmp -s "$existing_file" "${source_dir}/${relative}"; then
      rm -rf "$existing_dir" "$verify_dir"
      qa_retrieval_fail \
        "write-once tree s3://${bucket}/${prefix} already contains divergent ${relative}"
      return 1
    fi
  done < <(find "$existing_dir" -type f -print0)

  if ! aws s3 sync "$source_dir/" "s3://${bucket}/${prefix}" --only-show-errors; then
    rm -rf "$existing_dir" "$verify_dir"
    qa_retrieval_fail "could not upload ${label} tree"
    return 1
  fi
  if ! aws s3 sync "s3://${bucket}/${prefix}" "$verify_dir/" --only-show-errors; then
    rm -rf "$existing_dir" "$verify_dir"
    qa_retrieval_fail "could not verify ${label} tree"
    return 1
  fi
  if ! diff -qr "$source_dir" "$verify_dir" >/dev/null; then
    rm -rf "$existing_dir" "$verify_dir"
    qa_retrieval_fail "uploaded ${label} tree failed exact byte verification"
    return 1
  fi

  # #630 defect 2: qa_retrieval_sync_tree_write_once cannot use S3
  # --if-none-match (tree syncs, not single-object puts), so exclusion rests
  # on the deploy-qa resource_group alone. The read-back above trusts the
  # sync client's own view; independently list the prefix (paginated,
  # metadata-only) and compare the full key set to the source tree so a stray
  # or partial object (e.g. a zero-byte folder marker `s3 sync` silently
  # skips) is still detected. Defense-in-depth, not a replacement for the
  # resource_group lock.
  expected_keys=$(cd "$source_dir" && find . -type f | sed 's#^\./##' | sort)
  listed_keys=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix "$prefix" \
    --output json | jq -r '.Contents[]?.Key' | sed "s#^${prefix}##" | sort)
  if ! diff <(printf '%s\n' "$expected_keys") <(printf '%s\n' "$listed_keys") >/dev/null; then
    rm -rf "$existing_dir" "$verify_dir"
    qa_retrieval_fail \
      "uploaded ${label} tree inventory diverged (extra/missing objects) at s3://${bucket}/${prefix}"
    return 1
  fi

  rm -rf "$existing_dir" "$verify_dir"
}

qa_retrieval_prefix_has_objects() {
  local bucket="$1" prefix="$2" count
  count=$(aws s3api list-objects-v2 \
    --bucket "$bucket" \
    --prefix "$prefix" \
    --max-keys 1 \
    --query KeyCount \
    --output text)
  [[ "$count" =~ ^[0-9]+$ ]] || {
    qa_retrieval_fail "could not inspect s3://${bucket}/${prefix}"
    return 2
  }
  [[ "$count" -gt 0 ]]
}

# #631 — verify a component's declared file set is present in `bucket`, using
# the manifest_sha256 already pinned in the composite manifest as the
# integrity anchor. A non-empty prefix alone is not "complete": a first
# promotion aborted mid-`s3 sync` can leave a truncated component tree that
# is non-empty yet missing files. Returns 1 (not complete/not found — caller
# falls back) vs 2 (inspection error — caller fails closed), mirroring
# qa_retrieval_prefix_has_objects's exit-code convention.
qa_retrieval_component_manifest_complete() {
  local bucket="$1" component_json="$2" component_manifest="$3"
  local prefix manifest_key expected_sha actual_sha files_type file rel_path

  prefix=$(jq -r '.prefix' <<<"$component_json")
  manifest_key=$(jq -r '.manifest_key' <<<"$component_json")
  expected_sha=$(jq -r '.manifest_sha256' <<<"$component_json")
  [[ -n "$prefix" && "$prefix" != null ]] || return 1
  [[ -n "$manifest_key" && "$manifest_key" != null ]] || return 1
  [[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || return 1

  if ! aws s3api head-object --bucket "$bucket" --key "$manifest_key" \
      >/dev/null 2>/dev/null; then
    return 1
  fi
  if ! aws s3 cp "s3://${bucket}/${manifest_key}" "$component_manifest" \
      --only-show-errors 2>/dev/null; then
    qa_retrieval_fail "could not read s3://${bucket}/${manifest_key}"
    return 2
  fi
  actual_sha=$(_qa_retrieval_sha256_file "$component_manifest") || {
    qa_retrieval_fail "could not hash ${component_manifest}"
    return 2
  }
  [[ "$actual_sha" == "$expected_sha" ]] || return 1

  files_type=$(jq -r '.files | type' "$component_manifest")
  case "$files_type" in
    object)
      # Brochure component: {xml:[...], pdf:[...]} — relative paths within
      # the component prefix.
      while IFS= read -r rel_path; do
        [[ -n "$rel_path" ]] || continue
        aws s3api head-object --bucket "$bucket" \
          --key "${prefix}${rel_path}" >/dev/null 2>/dev/null || return 1
      done < <(jq -r '.files | to_entries[] | .value[]' "$component_manifest")
      ;;
    array)
      # FAQ component: ["html/faq.html", ...] — relative paths within the
      # component prefix.
      while IFS= read -r rel_path; do
        [[ -n "$rel_path" ]] || continue
        aws s3api head-object --bucket "$bucket" \
          --key "${prefix}${rel_path}" >/dev/null 2>/dev/null || return 1
      done < <(jq -r '.files[]' "$component_manifest")
      ;;
    *)
      return 1
      ;;
  esac
  return 0
}

_qa_retrieval_sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# #631 — decide whether `bucket` already holds a COMPLETE raw release for the
# coordinate at `raw_prefix` (e.g. "releases/<coordinate>/"). Writes the
# composite manifest to `output_manifest` whenever it exists (even if
# incomplete, so callers can inspect it) and returns 0 only when both the
# brochure and FAQ components verify complete. Returns 1 for
# absent/incomplete (caller falls back to the other source) and 2 for an
# inspection error (caller fails closed) — never silently treats "could not
# tell" as "absent".
qa_retrieval_composite_manifest_complete() {
  local bucket="$1" raw_prefix="$2" output_manifest="$3"
  local manifest_key="${raw_prefix}manifest.json" brochure_manifest faq_manifest status

  if ! aws s3api head-object --bucket "$bucket" --key "$manifest_key" \
      >/dev/null 2>/dev/null; then
    return 1
  fi
  if ! aws s3 cp "s3://${bucket}/${manifest_key}" "$output_manifest" \
      --only-show-errors 2>/dev/null; then
    qa_retrieval_fail "could not read s3://${bucket}/${manifest_key}"
    return 2
  fi
  jq -e '.schema_version == 1 and (.components.brochure) and (.components.faq)' \
    "$output_manifest" >/dev/null 2>/dev/null || return 1

  brochure_manifest=$(mktemp)
  faq_manifest=$(mktemp)
  qa_retrieval_component_manifest_complete "$bucket" \
    "$(jq -c '.components.brochure' "$output_manifest")" "$brochure_manifest"
  status=$?
  if [[ "$status" -eq 0 ]]; then
    qa_retrieval_component_manifest_complete "$bucket" \
      "$(jq -c '.components.faq' "$output_manifest")" "$faq_manifest"
    status=$?
  fi
  rm -f "$brochure_manifest" "$faq_manifest"
  return "$status"
}

# Re-emit an already-uploaded write-once source tree without changing its
# bytes or tags. CopyObject metadata changes generate fresh ObjectCreated
# events, which makes a canceled QA promotion retryable even though its raw
# inputs already exist and the normal write-once upload correctly skips them.
qa_retrieval_replay_tree() {
  local source_dir="${1%/}" bucket="$2" prefix="${3%/}/" replay_id="$4" label="$5"
  local file relative key head_file request_file replayed=0
  [[ -d "$source_dir" ]] || {
    qa_retrieval_fail "${label} source directory ${source_dir} is missing"
    return 1
  }

  head_file=$(mktemp)
  request_file=$(mktemp)
  while IFS= read -r -d '' file; do
    relative=${file#"${source_dir}/"}
    key="${prefix}${relative}"
    aws s3api head-object --bucket "$bucket" --key "$key" >"$head_file" || {
      rm -f "$head_file" "$request_file"
      qa_retrieval_fail "cannot replay missing ${label} object s3://${bucket}/${key}"
      return 1
    }
    # Pass CopySource as an unescaped bucket/key. Botocore's S3 handler URL-
    # encodes it exactly once; pre-encoding makes non-ASCII keys such as
    # "Kontenklärung" become double-encoded and S3 returns NoSuchKey.
    jq -n \
      --arg bucket "$bucket" \
      --arg key "$key" \
      --arg source "${bucket}/${key}" \
      --arg replay "$replay_id" \
      --arg replayed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --slurpfile head "$head_file" '
        ($head[0]) as $h
        | {
            Bucket: $bucket,
            Key: $key,
            CopySource: $source,
            MetadataDirective: "REPLACE",
            TaggingDirective: "COPY",
            ChecksumAlgorithm: "SHA256",
            Metadata: (($h.Metadata // {}) + {
              "etl-reprocess-version": $replay,
              "etl-reprocessed-at": $replayed_at
            })
          }
        + if $h.ContentType then {ContentType:$h.ContentType} else {} end
        + if $h.ContentEncoding then {ContentEncoding:$h.ContentEncoding} else {} end
        + if $h.ContentLanguage then {ContentLanguage:$h.ContentLanguage} else {} end
        + if $h.ContentDisposition then {ContentDisposition:$h.ContentDisposition} else {} end
        + if $h.CacheControl then {CacheControl:$h.CacheControl} else {} end
        + if $h.Expires then {Expires:$h.Expires} else {} end
        + if $h.WebsiteRedirectLocation then {WebsiteRedirectLocation:$h.WebsiteRedirectLocation} else {} end
      ' >"$request_file"
    aws s3api copy-object --cli-input-json "file://${request_file}" >/dev/null || {
      rm -f "$head_file" "$request_file"
      qa_retrieval_fail "could not replay ${label} object s3://${bucket}/${key}"
      return 1
    }
    replayed=$((replayed + 1))
  done < <(find "$source_dir" -type f -print0)
  rm -f "$head_file" "$request_file"
  [[ "$replayed" -gt 0 ]] || {
    qa_retrieval_fail "${label} contains no objects to replay"
    return 1
  }
  printf 'Replayed %d existing %s object(s).\n' "$replayed" "$label"
}

qa_retrieval_verify_immutable_corpus() {
  local bucket="$1" processed_prefix="${2%/}/" output_dir="${3%/}"
  local expected_inventory="$4" observed_inventory
  observed_inventory=$(mktemp)
  rm -rf "$output_dir"
  mkdir -p "$output_dir"
  aws s3 sync "s3://${bucket}/${processed_prefix}docs/" \
    "$output_dir/" --only-show-errors
  aws s3 cp "s3://${bucket}/${processed_prefix}inventory.json" \
    "$expected_inventory" --only-show-errors
  node "${REPO_ROOT}/.gitlab/ci/scripts/lib/node/retrieval-release.mjs" inventory \
    "$output_dir" "$observed_inventory"
  if ! jq -ne --arg prefix "$processed_prefix" \
      --slurpfile expected "$expected_inventory" \
      --slurpfile observed "$observed_inventory" '
        ($expected[0]) as $e | ($observed[0]) as $o
        | if $e.schema_version == 2 then
            $e == $o
          elif $e.schema_version == 1 then
            $e.object_count == $o.object_count
            and ($e.objects | length) == $o.object_count
            and all($e.objects[];
              .destination_key == ($prefix + .source_key))
            and ([$e.objects[] | {
              key:.source_key,
              bytes:.bytes,
              sha256:.sha256
            }] == $o.objects)
          else false end
      ' >/dev/null; then
    rm -f "$observed_inventory"
    qa_retrieval_fail \
      "immutable corpus inventory mismatch at s3://${bucket}/${processed_prefix}"
    return 1
  fi
  rm -f "$observed_inventory"
}

qa_retrieval_restore_immutable_corpus() {
  local bucket="$1" processed_prefix="${2%/}/" workspace="${3%/}"
  local source_dir="$workspace/source" verify_dir="$workspace/verify"
  local expected_inventory="$workspace/inventory.json"
  rm -rf "$workspace"
  mkdir -p "$workspace"
  qa_retrieval_verify_immutable_corpus \
    "$bucket" "$processed_prefix" "$source_dir" "$expected_inventory" || return 1
  aws s3 rm "s3://${bucket}/docs/" --recursive --only-show-errors || return 1
  aws s3 sync "$source_dir/" "s3://${bucket}/docs/" \
    --only-show-errors || return 1
  mkdir -p "$verify_dir"
  aws s3 sync "s3://${bucket}/docs/" "$verify_dir/" \
    --only-show-errors || return 1
  diff -qr "$source_dir" "$verify_dir" >/dev/null || {
    qa_retrieval_fail "restored live corpus failed exact verification"
    return 1
  }
}

