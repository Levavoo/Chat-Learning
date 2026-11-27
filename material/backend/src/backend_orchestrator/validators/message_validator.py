"""Message validation utilities for length and character constraints."""

import re

from backend_orchestrator.config import get_config

_WHITESPACE_RE = re.compile(r"\s+")
# Anything that is not a letter (incl. unicode), digit, or whitespace is "special".
_SPECIAL_CHAR_RE = re.compile(r"[^\w\s]", re.UNICODE)


def validate_message_length(message: str) -> tuple[bool, str | None]:
    """Validate message length, word-length, and special-character constraints.

    Returns:
        Tuple of (is_valid, error_message)
    """
    config = get_config()

    if not message:
        return False, "Message is required"

    if len(message) < config.min_message_length:
        return False, f"Message must be at least {config.min_message_length} characters"

    if len(message) > config.max_message_length:
        return False, f"Message exceeds maximum length of {config.max_message_length} characters"

    longest_word = max((len(word) for word in _WHITESPACE_RE.split(message.strip()) if word), default=0)
    if longest_word > config.max_word_length:
        return False, f"Message contains a word exceeding maximum length of {config.max_word_length} characters"

    special_char_count = len(_SPECIAL_CHAR_RE.findall(message))
    special_char_ratio = special_char_count / len(message)
    if special_char_ratio > config.max_special_char_ratio:
        return (
            False,
            f"Message exceeds maximum special character ratio of {config.max_special_char_ratio}",
        )

    return True, None
