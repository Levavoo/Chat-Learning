#!/usr/bin/env bats

SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/release/publish-deployment-page.sh"

setup() {
  TEST_DIR="$(mktemp -d)"
  mkdir -p "$TEST_DIR/bin"

  export PATH="$TEST_DIR/bin:$PATH"
  export GL_TOKEN="test-token"
  export CI_API_V4_URL="https://gitlab.test/api/v4"
  export CI_PROJECT_ID="123"

  PAGE_MD="$TEST_DIR/page.md"
  printf '# Deployment outputs — dev\n\nrenate-chatbot-dev.ApiUrl = https://x.example.com/prod/\n' >"$PAGE_MD"

  # Mock state, overridable per test:
  #   get_code  — HTTP status the GET lookup returns (404 = page missing)
  #   get_body  — JSON body the GET returns (only read on 200)
  #   write_code — HTTP status the POST/PUT write returns
  echo "404" >"$TEST_DIR/get_code"
  : >"$TEST_DIR/get_body"
  echo "201" >"$TEST_DIR/write_code"

  # curl mock: records every call to curl_calls, honours -o (body) and -w
  # (status code on stdout), and captures the write payload (--data @file).
  cat >"$TEST_DIR/bin/curl" <<EOF
#!/bin/bash
out=""; method="GET"; data=""
args=("\$@")
for ((i=0; i<\${#args[@]}; i++)); do
  case "\${args[i]}" in
    -X) method="\${args[i+1]}" ;;
    -o) out="\${args[i+1]}" ;;
    --data) data="\${args[i+1]}" ;;
  esac
done
url="\${args[\${#args[@]}-1]}"
echo "\$method \$url" >>"$TEST_DIR/curl_calls"
if [ "\$method" = "GET" ]; then
  [ -n "\$out" ] && cat "$TEST_DIR/get_body" >"\$out"
  cat "$TEST_DIR/get_code"
else
  echo "\$method" >"$TEST_DIR/write_method"
  if [[ "\$data" == @* ]]; then cp "\${data#@}" "$TEST_DIR/write_payload"; fi
  [ -n "\$out" ] && echo '{}' >"\$out"
  cat "$TEST_DIR/write_code"
fi
EOF
  chmod +x "$TEST_DIR/bin/curl"
}

teardown() {
  rm -rf "$TEST_DIR"
}

@test "[publish-deployment-page] missing env arg → exit 1 with usage" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "[publish-deployment-page] missing GL_TOKEN → exit non-zero" {
  unset GL_TOKEN
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -ne 0 ]
  [[ "$output" == *"GL_TOKEN"* ]]
}

@test "[publish-deployment-page] missing markdown file → exit 1" {
  run bash "$SCRIPT" dev "$TEST_DIR/nope.md"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not found"* ]]
}

@test "[publish-deployment-page] empty content → exit 1, no write" {
  : >"$TEST_DIR/empty.md"
  run bash "$SCRIPT" dev "$TEST_DIR/empty.md"
  [ "$status" -eq 1 ]
  [[ "$output" == *"empty"* ]]
  [ ! -f "$TEST_DIR/write_method" ]
}

@test "[publish-deployment-page] create path: page missing → POST to wikis, exit 0" {
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_DIR/write_method")" = "POST" ]
  grep -q "POST https://gitlab.test/api/v4/projects/123/wikis$" "$TEST_DIR/curl_calls"
  [[ "$output" == *"Created Wiki page 'Deployments/dev'"* ]]
}

@test "[publish-deployment-page] update path: page exists with different content → PUT to slug" {
  echo "200" >"$TEST_DIR/get_code"
  echo '{"content":"old stale content"}' >"$TEST_DIR/get_body"
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_DIR/write_method")" = "PUT" ]
  grep -q "PUT https://gitlab.test/api/v4/projects/123/wikis/Deployments%2Fdev$" "$TEST_DIR/curl_calls"
  [[ "$output" == *"Updated Wiki page 'Deployments/dev'"* ]]
}

@test "[publish-deployment-page] slug/title use Deployments/<env> layout for qa" {
  run bash "$SCRIPT" qa "$PAGE_MD"
  [ "$status" -eq 0 ]
  grep -q "GET https://gitlab.test/api/v4/projects/123/wikis/Deployments%2Fqa$" "$TEST_DIR/curl_calls"
  [ "$(jq -r '.title' "$TEST_DIR/write_payload")" = "Deployments/qa" ]
}

@test "[publish-deployment-page] payload is valid JSON with correctly escaped content" {
  printf 'line with "quotes"\nand\ttab and a \\ backslash\n' >"$TEST_DIR/tricky.md"
  run bash "$SCRIPT" dev "$TEST_DIR/tricky.md"
  [ "$status" -eq 0 ]
  # Payload parses as JSON and round-trips to the exact source content.
  jq -e . "$TEST_DIR/write_payload" >/dev/null
  [ "$(jq -r '.format' "$TEST_DIR/write_payload")" = "markdown" ]
  run jq -r '.content' "$TEST_DIR/write_payload"
  [[ "$output" == *'line with "quotes"'* ]]
  [[ "$output" == *'backslash'* ]]
}

@test "[publish-deployment-page] content read from stdin when no file given" {
  run bash -c "printf 'piped body line\n' | bash '$SCRIPT' dev"
  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_DIR/write_method")" = "POST" ]
  [ "$(jq -r '.content' "$TEST_DIR/write_payload")" = "piped body line" ]
}

@test "[publish-deployment-page] no-op: existing content identical → skip write, exit 0" {
  echo "200" >"$TEST_DIR/get_code"
  jq -n --arg c "$(cat "$PAGE_MD")" '{content:$c}' >"$TEST_DIR/get_body"
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -eq 0 ]
  [ ! -f "$TEST_DIR/write_method" ]
  [[ "$output" == *"already up to date"* ]]
}

@test "[publish-deployment-page] GET non-2xx/404 → exit non-zero with clear message" {
  echo "500" >"$TEST_DIR/get_code"
  echo '{"message":"boom"}' >"$TEST_DIR/get_body"
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Wiki GET failed"* ]]
  [[ "$output" == *"500"* ]]
  [ ! -f "$TEST_DIR/write_method" ]
}

@test "[publish-deployment-page] write non-2xx → exit non-zero with clear message" {
  echo "400" >"$TEST_DIR/write_code"
  run bash "$SCRIPT" dev "$PAGE_MD"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Wiki POST failed"* ]]
  [[ "$output" == *"400"* ]]
}
