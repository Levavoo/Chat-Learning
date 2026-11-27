"""API request/response models for OpenAPI generation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Rating value sets must mirror the exact strings the frontend form writes
# (feedback-internal-constants.ts / feedback-prod-constants.ts). Also the
# single source of truth consumed by the Langfuse Score Config sync
# (backend/scripts/sync_langfuse_score_configs.py).
_LikertRating = Literal["Yes", "Likely yes", "Probably not", "No", "Cannot evaluate"]
_ComparabilityRating = Literal["Better", "Equally good", "Equally bad", "Worse", "Cannot evaluate"]
# Helpfulness uses the UserFeedback enum from the frontend, not the Likert set.
_HelpfulnessRating = Literal["GOOD", "NEUTRAL", "BAD"]
# 0 is the free test mode ("Freie Vertestung"), 1 to 6 are scenarios.
_UsedScenario = Literal[0, 1, 2, 3, 4, 5, 6]
Producer = Literal["internal_single_turn", "internal_multi_turn", "internal_final_feedback", "external_3button"]
Scope = Literal["message", "turn", "dialog", "test"]


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split("_")
    return components[0] + "".join(word.capitalize() for word in components[1:])


class MessageContent(BaseModel):
    """Content block within a message."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    content_type: str
    body: str


class MessageFeedback(BaseModel):
    """User feedback on a message."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    producer: Producer | None = None
    scope: Scope | None = None
    # Without producer and scope, the backend derives both from these flags.
    is_multiturn: bool = False
    is_singleturn: bool = False
    is_free_user_test: bool = False
    is_final_feedback: bool = False
    is_per_turn_feedback: bool = False
    technical_correctivity: _LikertRating | None = None
    coverage_level: _LikertRating | None = None
    comprehensibility: _LikertRating | None = None
    precision: _LikertRating | None = None
    tonality: _LikertRating | None = None
    # utility_value and further_development remain `str | None`: the form group
    # declares them but feedback-prod-constants.ts only exposes an empty-string
    # placeholder option, so a Literal would 422 the first real submission if
    # the UI ever enabled them. Tracked for cleanup separately.
    # utility_value and further_development remain `str | None`: the form group
    # declares them but feedback-prod-constants.ts only exposes an empty-string
    # placeholder option, so a Literal would 422 the first real submission.
    utility_value: str | None = None
    comparability_to_google_ai: _ComparabilityRating | None = None
    source_matching: _LikertRating | None = None
    source_quality: _LikertRating | None = None
    used_scenario: _UsedScenario | None = None
    goal_achievement: _LikertRating | None = None
    dialogue_skills: _LikertRating | None = None
    handling_corrections: _LikertRating | None = None
    further_development: str | None = None
    good_to_recommend: _LikertRating | None = None
    comment: str | None = None
    helpfulness: _HelpfulnessRating | None = None
    technical_correctivity_reason: str | None = None
    coverage_level_reason: str | None = None
    comprehensibility_reason: str | None = None
    precision_reason: str | None = None
    tonality_reason: str | None = None
    comparability_to_google_ai_reason: str | None = None
    source_matching_reason: str | None = None
    source_quality_reason: str | None = None
    goal_achievement_reason: str | None = None
    dialogue_skills_reason: str | None = None
    handling_corrections_reason: str | None = None
    good_to_recommend_reason: str | None = None


# MessageFeedback field → (Langfuse score name, Langfuse dataType). Every filled field
# becomes one score, in this order. Not scores: comment (added to the first score),
# <criterion>_reason (comment of its score), producer, scope and the is_* flags.
FEEDBACK_SCORE_SCHEMA: dict[str, tuple[str, str]] = {
    "technical_correctivity": ("user.technical_correctivity", "CATEGORICAL"),
    "coverage_level": ("user.coverage_level", "CATEGORICAL"),
    "comprehensibility": ("user.comprehensibility", "CATEGORICAL"),
    "precision": ("user.precision", "CATEGORICAL"),
    "tonality": ("user.tonality", "CATEGORICAL"),
    "utility_value": ("user.utility_value", "CATEGORICAL"),
    "comparability_to_google_ai": ("user.comparability_to_google_ai", "CATEGORICAL"),
    "source_matching": ("user.source_matching", "CATEGORICAL"),
    "source_quality": ("user.source_quality", "CATEGORICAL"),
    "goal_achievement": ("user.goal_achievement", "CATEGORICAL"),
    "dialogue_skills": ("user.dialogue_skills", "CATEGORICAL"),
    "handling_corrections": ("user.handling_corrections", "CATEGORICAL"),
    "further_development": ("user.further_development", "CATEGORICAL"),
    "good_to_recommend": ("user.good_to_recommend", "CATEGORICAL"),
    "used_scenario": ("user.used_scenario", "CATEGORICAL"),
    "helpfulness": ("user.helpfulness", "CATEGORICAL"),
}


class MessageChunk(BaseModel):
    """Knowledge base chunk used in response.

    Shared between KB chunks and related documents (optional fields populated for
    the related-document case). Deliberately excludes the underlying S3 URI: it
    must never reach the API response or DynamoDB storage. ``document_id`` is
    a non-sensitive, stable identifier shared by every chunk of the same source
    document, used by the frontend to group related chunks under one citation.
    """

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

    content: str
    content_type: str
    rank: int
    title: str | None = None
    source_name: str | None = None
    document_id: str | None = None
    page_number: str | int | None = None
    source_index: int | None = None
    brochure_url: str | None = None
    brochure_number: str | None = None
    publishing_date: str | None = None
    category: str | None = None
    retrieval_release_id: str | None = None
    section_title: str | None = None
    domain_tier: str | None = None


class ChatInputMessage(BaseModel):
    """Message within a chat input request."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    content: list[MessageContent]
    message_id: str | None = None


class ChatInput(BaseModel):
    """Request body for /chat endpoint."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    conversation_id: str
    message: ChatInputMessage


class ChatOutputMessage(BaseModel):
    """Message within a chat output response."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    role: str
    content: list[MessageContent]
    feedback: MessageFeedback | None
    used_chunks: list[MessageChunk] | None = None
    # Full retrieved set (not just cited). Opt-in via X-Renate-Eval-Mode to keep
    # the default payload size unchanged; DynamoDB persistence stays cited-only.
    all_sources: list[MessageChunk] | None = None
    # Chat.request root span id, hex-encoded (OTel 16-char lowercase). Opt-in via
    # X-Renate-Eval-Mode: eval score posts need (traceId, observationId) =
    # (root trace, root span) to attach per-item scores to the root observation
    # per Langfuse v4. Hard-closed in prod before the controller gate ever fires.
    root_span_id: str | None = None
    parent: str
    message_id: str | None = None


class ChatOutput(BaseModel):
    """Response body from /chat endpoint."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    conversation_id: str
    message: ChatOutputMessage
    create_time: int
    trace_id: str | None = None


class DomainCount(BaseModel):
    """Count of messages per domain."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    domain: str
    count: int


class SourceCount(BaseModel):
    """Count of source usage."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_name: str
    count: int


class AnalyticsResponse(BaseModel):
    """Response body from /api/analytics endpoint."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_sessions: int
    total_messages: int
    avg_messages_per_session: float
    top_domains: list[DomainCount]
    top_sources: list[SourceCount]
    feedback_thumbs_up_rate: float | None
    blocked_rate: float
    feedback_good_count: int = 0
    feedback_neutral_count: int = 0
    feedback_bad_count: int = 0
    top_topics: list["TopicCount"] = []
    topic_time_series: list["TopicTimeSeriesEntry"] = []


class TopicCount(BaseModel):
    """Count of messages per sub-topic.

    `domain` is the taxonomy display-domain (rente/reha/versicherung/sonstiges/service),
    NOT the DynamoDB `domain` partition key value.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    topic: str
    domain: str
    count: int


class WeekDataPoint(BaseModel):
    """Count for a single ISO calendar week."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    week_start: str
    count: int


class TopicTimeSeriesEntry(BaseModel):
    """Weekly count time series for a single topic."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    topic: str
    data_points: list[WeekDataPoint]


class DocumentInventoryItem(BaseModel):
    """Single document entry from the Agent-Search-Index."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    doc_id: str
    title: str
    edition: str | None = None
    published: str | None = None
    category: str | None = None
    section_count: int


class DocumentInventoryResponse(BaseModel):
    """Response body from /api/analytics/documents endpoint."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_documents: int
    documents: list[DocumentInventoryItem]
