#!/usr/bin/env bash
# Shared CI log formatting. Source this file; do not execute it directly.
# Designed for GitLab CI runners (no TTY, no ANSI color).
# Box-drawing glyph (─) is confined here — single locale-guard point if needed.
#
# Functions exported:
#   log_section "TITLE"          — open rule + indented title + open rule
#   log_kv      "Key:" "value"   — aligned key/value (ASCII keys only)
#   log_url     "https://..."    — URL flush-left at column 0 (copy-clean)
#   log_done                     — closing rule + blank line
#   section_start      "id" "title"   — GitLab collapsible section open (collapsed by default)
#   section_start_open "id" "title"   — GitLab section open, expanded in the log viewer
#   section_end        "id"           — GitLab section close
#   log_error_banner   "id" "msg"     — expanded single-line error section (grep-anchor + visibility)

# Open rule: 2-space indent, no right border (avoids display-width/multibyte math).
RULE="  $(printf '─%.0s' {1..60})"

log_section() {
  printf '\n%s\n   %s\n%s\n' "$RULE" "$1" "$RULE"
}

log_kv() {
  printf '     %-12s %s\n' "$1" "$2"
}

log_url() {
  printf '%s\n' "$1"
}

log_done() {
  printf '%s\n\n' "$RULE"
}

# GitLab CI collapsible sections.
# Uses \033 (not \e) for portability across CI images.
# The [collapsed=true] flag means sections are folded by default in the GitLab log viewer.
section_start() {
  local id="$1" title="$2"
  printf '\033[0Ksection_start:%s:%s[collapsed=true]\r\033[0K%s\n' \
    "$(date +%s)" "$id" "$title"
}

section_start_open() {
  local id="$1" title="$2"
  printf '\033[0Ksection_start:%s:%s\r\033[0K%s\n' \
    "$(date +%s)" "$id" "$title"
}

section_end() {
  local id="$1"
  printf '\033[0Ksection_end:%s:%s\r\033[0K' "$(date +%s)" "$id"
}

# Uncollapsed GitLab section wrapping one loud ERROR line.
# Visible by default in the job tab; grep-friendly (the message is printed verbatim).
# Usage: log_error_banner "unique-id" "ERROR: <message>"
log_error_banner() {
  local id="$1" msg="$2"
  section_start_open "$id" "$msg"
  section_end "$id"
}
