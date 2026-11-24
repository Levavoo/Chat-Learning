#!/usr/bin/env bash
# validate-promotion-pin.sh <pin-file>
# Enforces the deliberately small three-line promotion contract.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN_FILE="${1:?Usage: validate-promotion-pin.sh <pin-file>}"

# shellcheck source=lib/deploy.sh disable=SC1091
source "${SCRIPT_DIR}/../lib/deploy.sh"

validate_promotion_pin "$PIN_FILE"
echo "Promotion pin validated: ${PIN_FILE}"
