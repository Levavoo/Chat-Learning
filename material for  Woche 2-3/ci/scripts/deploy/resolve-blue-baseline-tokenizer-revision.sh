#!/usr/bin/env bash
# Resolve the tokenizer probe emitted from an immutable deployed image.
#
# Current images declare their revision directly. The legacy 1.83.3 images
# predate TOKENIZER_REVISION, so they are accepted only when all three source
# files exactly match the implementation to which d1b7d67d later added
# TOKENIZER_REVISION="cistem-decompound-v1" without changing tokenization.
set -euo pipefail

PROBE="${1:-}"
LEGACY_CISTEM_DECOMPOUND_V1="legacy-source-sha256:7086817778eb7edc2cef7aea7961ccaccb5762054d44fd9b8ee842f4a96d625c:92fee32ec0ea36ade49eb01c0d281129a6a6025dc7ec0a2bf60d0d73a5e68604:827aa79c4dc95af582d7b5db8be31374a6e76e667212b8d1d9e5ab07001964cb"

case "$PROBE" in
  declared:*)
    REVISION="${PROBE#declared:}"
    ;;
  "$LEGACY_CISTEM_DECOMPOUND_V1")
    REVISION="cistem-decompound-v1"
    echo "Legacy tokenizer source fingerprint attested as ${REVISION}." >&2
    ;;
  legacy-source-sha256:*)
    echo "ERROR: unknown legacy tokenizer source fingerprint: ${PROBE}" >&2
    exit 1
    ;;
  *)
    echo "ERROR: malformed tokenizer probe: ${PROBE:-<empty>}" >&2
    exit 1
    ;;
esac

[[ "$REVISION" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || {
  echo "ERROR: probed tokenizer revision is invalid: '${REVISION}'" >&2
  exit 1
}
printf '%s\n' "$REVISION"
