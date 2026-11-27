"""Backward-compatibility shim; use validators subpackage for new code."""

from backend_orchestrator.validators.message_validator import validate_message_length

__all__ = ["extract_message_text", "validate_message_length"]


def extract_message_text(body: dict) -> str:
    """Extract message text from a chat request body."""
    message_obj = body.get("message", {})
    if isinstance(message_obj, dict):
        content_list = message_obj.get("content", [])
        return content_list[0].get("body", "") if content_list and isinstance(content_list, list) else ""
    return str(message_obj)
