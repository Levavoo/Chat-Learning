#!/usr/bin/env bash
set -euo pipefail

# get-stack-outputs.sh — Get CDK stack outputs from CloudFormation
#
# This is a fallback utility to retrieve stack outputs from CloudFormation
# when the CDK --outputs-file flag doesn't work as expected.
#
# Usage: get-stack-outputs.sh <stack-name> [output-file]
#   <stack-name>   CloudFormation stack name (e.g., renate-chatbot-dev)
#   [output-file]  Optional path to write JSON output (default: stdout)

err() { printf '%s\n' "$*" >&2; }

STACK_NAME="${1:-}"
OUTPUT_FILE="${2:-}"

[[ -n "$STACK_NAME" ]] || { err "Usage: get-stack-outputs.sh <stack-name> [output-file]"; exit 1; }

# Describe the stack and extract outputs
if ! STACK_DESC=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json); then
  err "Failed to retrieve CloudFormation outputs for stack: $STACK_NAME"
  exit 1
fi

# Convert CloudFormation output format to CDK format
# CloudFormation: [{"OutputKey": "key", "OutputValue": "value"}, ...]
# CDK: {"stack-name": {"key": "value", ...}}
JSON_OUTPUT=$(jq -n \
  --arg stack "$STACK_NAME" \
  --argjson outputs "$STACK_DESC" \
  '{($stack): (($outputs // []) | map({(.OutputKey): .OutputValue}) | add // {})}'
)

if [[ -n "$OUTPUT_FILE" ]]; then
  printf '%s\n' "$JSON_OUTPUT" > "$OUTPUT_FILE"
else
  printf '%s\n' "$JSON_OUTPUT"
fi
