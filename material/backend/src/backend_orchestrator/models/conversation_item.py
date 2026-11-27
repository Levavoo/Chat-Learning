from typing import Any

from pydantic import BaseModel, ConfigDict


class ConversationItem(BaseModel):
    """Model representing a conversation item stored in DynamoDB."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    message_id: str
    message: str
    response_text: str
    created_at: int | None = None
    sources: list[dict[str, Any]]
    feedback: dict[str, Any] | None = None
    blocked_by_guardrail: bool | None = None
    domain: str | None = None
    langfuse_trace_id: str | None = None
    # Written by the classify_topics.py batch script; None until classified.
    topic: str | None = None
    # DynamoDB TTL (epoch seconds). Review environments use 21 days, other
    # environments use CONVERSATION_TTL_DAYS (default 30). DynamoDB deletes
    # expired items within ~48h; read-time filtering ensures exact cutoff.
    ttl: int | None = None
