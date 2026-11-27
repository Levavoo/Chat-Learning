#!/usr/bin/env bash
set -euo pipefail

# publish-deployment-page.sh — TKT-DDP-03
#
# Upsert the rendered deployment Markdown (from TKT-DDP-02) to the GitLab Wiki
# via the Wiki API. One page per environment under `Deployments/<env>`. See:
#   docs/architecture/rfc/rfc-deployment-dashboard.md
#   docs/tickets/ci_cd/03-deployment-detail-page.md  (TKT-DDP-03)
#
# The Wiki is a separate git repo: writing to it never touches `master`, never
# triggers a pipeline, and needs no `ci.skip`. This script performs NO git
# operations — it talks to the GitLab API only, mirroring the `curl` + GL_TOKEN
# pattern from open-qa-mr.sh.
#
# Idempotent upsert: GET the page; PUT to update if it exists, POST to create if
# it does not. If the remote content already equals the new content, the API
# write is skipped so the Wiki history is not polluted with empty revisions.
#
# Usage: publish-deployment-page.sh <env> [markdown-file]
#   <env>            environment label, e.g. dev or qa (required)
#   [markdown-file]  path to the rendered Markdown; if omitted, read from stdin
#
# Required environment:
#   GL_TOKEN         GitLab token with `api` scope
#   CI_API_V4_URL    e.g. https://gitlab.example.com/api/v4
#   CI_PROJECT_ID    numeric project id

err() { printf '%s\n' "$*" >&2; }

ENV_LABEL="${1:-}"
[[ -n "$ENV_LABEL" ]] \
  || { err "Usage: publish-deployment-page.sh <env> [markdown-file]"; exit 1; }

: "${GL_TOKEN:?GL_TOKEN is required}"
: "${CI_API_V4_URL:?CI_API_V4_URL is required}"
: "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"

# Read the page content from the given file, or from stdin when no path is given.
MD_FILE="${2:-}"
if [[ -n "$MD_FILE" ]]; then
  [[ -f "$MD_FILE" ]] || { err "markdown file not found: $MD_FILE"; exit 1; }
  CONTENT="$(cat "$MD_FILE")"
else
  CONTENT="$(cat)"
fi
[[ -n "$CONTENT" ]] || { err "refusing to publish empty content"; exit 1; }

# Page identity follows the DDP-00 layout: one page per env under Deployments/.
TITLE="Deployments/${ENV_LABEL}"
SLUG="$TITLE"
# Slug must be URL-path-encoded; the only reserved char in our slugs is `/`.
SLUG_ENCODED="${SLUG//\//%2F}"

WIKIS_URL="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/wikis"
PAGE_URL="${WIKIS_URL}/${SLUG_ENCODED}"

# api METHOD URL [curl-args...]
# Runs an authenticated GitLab API call, prints the HTTP status code to stdout,
# and writes the response body to the file named by the API_BODY_FILE global.
# Uses `-w` for the status and `-o` for the body so the two never interleave;
# does NOT use `-f`, because we need to inspect non-2xx bodies/codes ourselves.
api() {
  local method="$1" url="$2"
  shift 2
  curl -sS --connect-timeout 10 --max-time 30 -X "$method" \
    -H "PRIVATE-TOKEN: $GL_TOKEN" \
    -H "Content-Type: application/json" \
    -o "$API_BODY_FILE" \
    -w '%{http_code}' \
    "$@" "$url"
}

API_BODY_FILE="$(mktemp)"
trap 'rm -f "$API_BODY_FILE" "${PAYLOAD_FILE:-}"' EXIT

# Look up the current page (if any). 200 → exists, 404 → create, else → error.
GET_STATUS="$(api GET "$PAGE_URL")"

if [[ "$GET_STATUS" == "200" ]]; then
  REMOTE_CONTENT="$(jq -r '.content' "$API_BODY_FILE")"
  if [[ "$REMOTE_CONTENT" == "$CONTENT" ]]; then
    err "Wiki page '$TITLE' already up to date — skipping write"
    exit 0
  fi
  METHOD="PUT"
  TARGET_URL="$PAGE_URL"
  ACTION="Updated"
elif [[ "$GET_STATUS" == "404" ]]; then
  METHOD="POST"
  TARGET_URL="$WIKIS_URL"
  ACTION="Created"
else
  err "Wiki GET failed for '$TITLE' (HTTP $GET_STATUS):"
  err "$(cat "$API_BODY_FILE")"
  exit 1
fi

# Build the payload with jq so the Markdown content is correctly JSON-escaped.
PAYLOAD_FILE="$(mktemp)"
jq -n \
  --arg title "$TITLE" \
  --arg content "$CONTENT" \
  '{title: $title, content: $content, format: "markdown"}' \
  >"$PAYLOAD_FILE"

WRITE_STATUS="$(api "$METHOD" "$TARGET_URL" --data "@$PAYLOAD_FILE")"

if [[ "$WRITE_STATUS" != 2* ]]; then
  err "Wiki $METHOD failed for '$TITLE' (HTTP $WRITE_STATUS):"
  err "$(cat "$API_BODY_FILE")"
  exit 1
fi

err "$ACTION Wiki page '$TITLE' (HTTP $WRITE_STATUS)"
