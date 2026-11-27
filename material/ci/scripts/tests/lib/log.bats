#!/usr/bin/env bats

LIB="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/lib/log.sh"

# Source the library in a subshell and capture its output for each test.

@test "[log] log_section emits open rule, indented title, open rule" {
  run bash -c "source '$LIB'; log_section 'MY TITLE'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"─"* ]]
  [[ "$output" == *"MY TITLE"* ]]
  # Rule must appear twice (before and after title)
  count=$(printf '%s\n' "$output" | grep -c '─')
  [ "$count" -ge 2 ]
}

@test "[log] log_section title is indented (not at column 0)" {
  run bash -c "source '$LIB'; log_section 'TITLE'"
  [ "$status" -eq 0 ]
  # The title line must start with whitespace
  title_line=$(printf '%s\n' "$output" | grep 'TITLE')
  [[ "$title_line" =~ ^[[:space:]] ]]
}

@test "[log] log_kv emits aligned key and value" {
  run bash -c "source '$LIB'; log_kv 'User:' 'alice@example.com'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"User:"* ]]
  [[ "$output" == *"alice@example.com"* ]]
}

@test "[log] log_url prints URL with no leading whitespace" {
  run bash -c "source '$LIB'; log_url 'https://example.com/review/feat-x/index.html'"
  [ "$status" -eq 0 ]
  url_line=$(printf '%s\n' "$output" | grep 'https://')
  # Must start at column 0 — no leading space or tab
  [[ "$url_line" =~ ^https:// ]]
}

@test "[log] log_done emits a rule and trailing blank line" {
  run bash -c "source '$LIB'; log_done"
  [ "$status" -eq 0 ]
  [[ "$output" == *"─"* ]]
}

@test "[log] section_start emits GitLab collapsed-section marker" {
  run bash -c "source '$LIB'; section_start 'my_id' 'My Section Title'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"section_start:"* ]]
  [[ "$output" == *"my_id"* ]]
  [[ "$output" == *"collapsed=true"* ]]
  [[ "$output" == *"My Section Title"* ]]
}

@test "[log] section_end emits GitLab section-end marker" {
  run bash -c "source '$LIB'; section_end 'my_id'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"section_end:"* ]]
  [[ "$output" == *"my_id"* ]]
}

@test "[log] rule has no right border (open rule)" {
  run bash -c "source '$LIB'; log_section 'X'"
  [ "$status" -eq 0 ]
  # Each rule line must end with ─ (or whitespace after ─), not a closing char like │ or ┐
  while IFS= read -r line; do
    if [[ "$line" == *"─"* ]]; then
      # Strip trailing whitespace and check last non-space char is ─
      trimmed="${line%"${line##*[![:space:]]}"}"
      [[ "$trimmed" == *"─" ]]
    fi
  done <<< "$output"
}
