#!/usr/bin/env bash
set -euo pipefail
# smoke-eval-preprod.sh — thin wrapper; delegates to smoke-eval-env.sh.
exec "$(dirname "${BASH_SOURCE[0]}")/smoke-eval-env.sh" preprod "$@"
