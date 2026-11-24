#!/usr/bin/env bash
# Compatibility facade for the QA retrieval helper modules.
#
# Existing Bats suites may continue to source this file. Executable callers
# should source the common helper and the concrete modules they use directly.

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
# shellcheck source=qa-retrieval-common.sh disable=SC1091
source "${SCRIPT_DIR}/qa-retrieval-common.sh"
# shellcheck source=qa-retrieval-auth.sh disable=SC1091
source "${SCRIPT_DIR}/qa-retrieval-auth.sh"
# shellcheck source=qa-retrieval-polling.sh disable=SC1091
source "${SCRIPT_DIR}/qa-retrieval-polling.sh"
# shellcheck source=qa-retrieval-s3.sh disable=SC1091
source "${SCRIPT_DIR}/qa-retrieval-s3.sh"
# shellcheck source=qa-retrieval-validation.sh disable=SC1091
source "${SCRIPT_DIR}/qa-retrieval-validation.sh"
