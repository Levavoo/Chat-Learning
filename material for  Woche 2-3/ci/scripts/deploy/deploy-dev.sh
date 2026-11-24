#!/usr/bin/env bash
set -euo pipefail
# deploy-dev.sh — thin wrapper; delegates to deploy-env.sh.
exec "$(dirname "${BASH_SOURCE[0]}")/deploy-env.sh" dev "$@"
