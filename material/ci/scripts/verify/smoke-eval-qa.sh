#!/usr/bin/env bash
set -euo pipefail
exec bash "$(dirname "$0")/smoke-eval.sh" "$CDK_DEPLOY_ROLE_ARN_QA" renate-chatbot-qa qa
