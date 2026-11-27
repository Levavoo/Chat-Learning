"""Log-masking helpers for session identifiers.

session_id is a bearer-like value: possessing it lets a caller act as that
session, so full IDs must not reach CloudWatch. Langfuse traces are internal
and keep the full ID for debugging.
"""


def mask_session_id(session_id: str | None) -> str:
    """Return the first 8 chars plus '...' for safe CloudWatch logging.

    Empty or None returns '' so Insights aggregations do not collapse unrelated
    sessions into a single bucket. Short IDs (<8 chars) still get an ellipsis
    suffix so the value is visibly a masked prefix, not a full ID.
    """
    if not session_id:
        return ""
    return session_id[:8] + "..."


def sanitize_error_message(error_msg: str, session_id: str | None) -> str:
    """Strip a session_id substring from an error message before it reaches the client.

    Session ids shorter than nine chars round-trip verbatim under prefix-masking
    (the mask `sid[:8] + "..."` contains the whole short id), so those cases
    collapse to a static message instead of the raw string.
    """
    if not isinstance(session_id, str) or not session_id or session_id not in error_msg:
        return error_msg
    if len(session_id) > 8:
        return error_msg.replace(session_id, mask_session_id(session_id))
    return "Bad request"


def mask_message_id(message_id: str | None) -> str:
    """Mask everything before the LAST `#` of a `{sessionId}#{uuid}` message id.

    The frontend builds message ids as `${sessionId}#${uuidv4()}`, so the uuid
    is always the segment after the final `#`. Splitting on the last `#` is
    defensive against session ids that themselves contain a `#` (custom fallback
    ids, review-env namespacing, forwarded/concatenated payloads). If the id has
    no `#` at all, fall back to plain session-id masking.
    """
    if not message_id:
        return ""
    prefix, sep, uuid = message_id.rpartition("#")
    if not sep:
        return mask_session_id(uuid)
    return f"{mask_session_id(prefix)}#{uuid}"
