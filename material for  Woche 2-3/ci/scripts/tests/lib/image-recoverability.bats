#!/usr/bin/env bats
# #643 — image recoverability must distinguish "the image is gone" from "this
# role may not look". Conflating them made every qa promotion fail closed, since
# no CI role holds ecr:DescribeImages on the dev repos today.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../../../../.." && pwd)"
LIB="$REPO_ROOT/.gitlab/ci/scripts/lib/qa-retrieval.sh"
DIGEST="sha256:$(printf 'a%.0s' {1..64})"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"
}
teardown() { rm -rf "$TEST_DIR"; }

# Stub aws so `ecr describe-images` emits the given stderr and exit code.
_stub_aws() {
  cat >"$TEST_DIR/bin/aws" <<EOF
#!/usr/bin/env bash
if [[ "\$*" == *"describe-images"* ]]; then
  echo "$1" >&2
  exit ${2:-255}
fi
exit 0
EOF
  chmod +x "$TEST_DIR/bin/aws"
}

_run_check() {
  PATH="$TEST_DIR/bin:$PATH" RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID=831926590742 \
    run bash -c 'source "$1"; qa_retrieval_assert_image_recoverable "incoming chatbot" renate-chat-lambda "$2"' \
    _ "$LIB" "$DIGEST"
}

@test "[#643 recoverability] present image → verified" {
  _stub_aws "" 0
  _run_check
  [ "$status" -eq 0 ]
  [[ "$output" == *"recoverable:"* ]]
}

@test "[#643 recoverability] ImageNotFoundException → hard fail" {
  _stub_aws "An error occurred (ImageNotFoundException) when calling the DescribeImages operation: not found"
  _run_check
  [ "$status" -ne 0 ]
  [[ "$output" == *"not recoverable"* ]]
  [[ "$output" == *"could not be rolled back"* ]]
}

@test "[#643 recoverability] AccessDenied → UNVERIFIED, does not block" {
  # This is the case that broke live qa: no CI role can describe the dev repos,
  # and a missing grant must not masquerade as a missing image.
  _stub_aws "An error occurred (AccessDeniedException) when calling the DescribeImages operation: User: arn:aws:sts::1:assumed-role/x is not authorized to perform: ecr:DescribeImages"
  _run_check
  [ "$status" -eq 0 ]
  [[ "$output" == *"UNVERIFIED"* ]]
  [[ "$output" != *"not recoverable"* ]]
}

@test "[#643 recoverability] unexpected error → fails closed" {
  _stub_aws "An error occurred (ThrottlingException) when calling the DescribeImages operation: slow down"
  _run_check
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not determine"* ]]
}

@test "[#643 recoverability] malformed digest → hard fail before any API call" {
  _stub_aws "" 0
  PATH="$TEST_DIR/bin:$PATH" RETRIEVAL_IMAGE_METADATA_ACCOUNT_ID=831926590742 \
    run bash -c 'source "$1"; qa_retrieval_assert_image_recoverable l r "sha256:nope"' _ "$LIB"
  [ "$status" -ne 0 ]
  [[ "$output" == *"malformed"* ]]
}
