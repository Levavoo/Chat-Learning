"""Service layer for chat operations."""

from difflib import SequenceMatcher
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit, single_metric

from backend_orchestrator.agents.agent import create_agent, run_agent, run_agent_async
from backend_orchestrator.models.api_models import FEEDBACK_SCORE_SCHEMA, to_camel
from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.observability import ScoreEvent, post_langfuse_scores
from backend_orchestrator.repositories.conversation import RATING_DIALOG, RATING_FINAL, ConversationStore
from backend_orchestrator.services.feedback_rating import SCHEMA_VERSION, InternalRating, build_stored_map
from backend_orchestrator.utils.history_converter import extract_seed_sources, items_to_messages
from backend_orchestrator.utils.session_masking import mask_session_id
from backend_orchestrator.validators.guardrail_validator import validate_user_input_with_guardrail
from backend_orchestrator.validators.message_validator import validate_message_length

logger = Logger(child=True)

# Hard cap on user messages per conversation, same in every environment (#992, ADR-003 measure 6).
# Equal to DEFAULT_MAX_HISTORY_PAIRS, so the model always sees the whole conversation.
# Soft limit: counted from the history read, no atomic counter, so parallel requests at the
# boundary may let a few extra messages through. Blocked turns count too, they are stored rows.
MAX_MESSAGES_PER_CONVERSATION = 20


class ConversationLimitReachedError(Exception):
    """The conversation already holds MAX_MESSAGES_PER_CONVERSATION messages."""


def _find_stored_turn(history_items: list[ConversationItem], message_id: str | None) -> ConversationItem | None:
    """Return the stored turn with this message_id, if any.

    message_id is the DynamoDB sort key and put_item overwrites it, so a reused id never adds
    a row. Without this check a client could cycle a few ids and stay under the limit forever.
    """
    if not message_id:
        return None
    return next((item for item in history_items if item.message_id == message_id), None)


def _replay_stored_turn(item: ConversationItem, session_id: str) -> dict[str, Any]:
    """Answer a repeated message_id with the stored answer, without guardrail or model call.

    Also makes client retries (frontend retries 502/503/504 with the same id) idempotent.
    """
    logger.warning("Repeated message_id, replaying stored turn", extra={"session_id": mask_session_id(session_id)})
    return {
        "response_text": item.response_text,
        "used_chunks": item.sources or [],
        "message_id": item.message_id,
    }


def _enforce_conversation_limit(history_items: list[ConversationItem], session_id: str) -> None:
    """Reject the request if the conversation is full.

    The caller reads the history with get_history; a HistoryReadError there propagates, so
    without a reliable count the request is rejected before any model call (fail-closed).
    """
    if len(history_items) >= MAX_MESSAGES_PER_CONVERSATION:
        logger.warning(
            "Conversation limit reached",
            extra={
                "session_id": mask_session_id(session_id),
                "history_count": len(history_items),
                "limit": MAX_MESSAGES_PER_CONVERSATION,
            },
        )
        raise ConversationLimitReachedError


def _feedback_get(feedback: dict[str, Any], field: str) -> Any:
    if field in feedback:
        return feedback[field]
    return feedback.get(to_camel(field))


def _emit_feedback_written(*, producer: str, scope: str, schema_version: str) -> None:
    with single_metric(
        name="FeedbackWritten",
        unit=MetricUnit.Count,
        value=1,
        namespace="Renate/Backend",
    ) as metric:
        metric.add_dimension(name="Producer", value=producer)
        metric.add_dimension(name="Scope", value=scope)
        metric.add_dimension(name="SchemaVersion", value=schema_version)


def _rating_metadata(rating: InternalRating) -> dict[str, str]:
    return {"producer": rating.producer, "scope": rating.scope, "schema_version": SCHEMA_VERSION}


def _build_score_events(
    values: dict[str, Any],
    *,
    id_prefix: str,
    comment: str | None,
    reasons: dict[str, str] | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> list[ScoreEvent]:
    """Build one Langfuse score per filled field of FEEDBACK_SCORE_SCHEMA.

    Scores go to the session if ``session_id`` is set, else to the trace. A score's comment
    is the reason of its criterion; the form comment is added to the first score.
    """
    reasons = reasons or {}
    comment_attached = comment is None
    events: list[ScoreEvent] = []
    for field, (score_name, data_type) in FEEDBACK_SCORE_SCHEMA.items():
        raw = values.get(field)
        if raw is None:
            continue
        if field == "used_scenario":
            value: Any = str(raw)
        else:
            if not isinstance(raw, str) or not raw:
                continue
            value = raw

        parts = [reasons.get(field)]
        if not comment_attached:
            parts.append(comment)
            comment_attached = True
        score_comment = "\n\n".join(part for part in parts if part) or None
        event: ScoreEvent = {
            "name": score_name,
            "value": value,
            "data_type": data_type,
            "comment": score_comment,
            "id": f"{id_prefix}#{field}",
        }
        if session_id is not None:
            event["session_id"] = session_id
        elif trace_id is not None:
            event["trace_id"] = trace_id
        if metadata:
            event["metadata"] = metadata
        events.append(event)
    return events


class ChatService:
    """Service for handling chat business logic."""

    def __init__(self):
        """Initialize chat service with pydantic-ai agent."""
        try:
            self.conversation_store = ConversationStore()
            self._agent = create_agent()
            logger.info("ChatService initialized")
        except Exception as e:
            logger.exception("Failed to initialize agent", extra={"error_type": type(e).__name__})
            raise RuntimeError(f"ChatService initialization failed: {e}") from e

    def process_message(
        self,
        message: str,
        session_id: str,
        request_time_epoch: int | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Process a user message. Raises ValueError on validation failure."""
        agent = self._agent

        is_valid, error_message = validate_message_length(message)
        if not is_valid:
            logger.warning(f"Validation failed: {error_message}")
            raise ValueError(error_message)

        # History anchors the guardrail's classification of follow-ups.
        # A read error raises HistoryReadError (fail-closed, #992).
        history_items = self.conversation_store.get_history(session_id)
        stored_turn = _find_stored_turn(history_items, message_id)
        if stored_turn is not None:
            return _replay_stored_turn(stored_turn, session_id)
        _enforce_conversation_limit(history_items, session_id)

        guardrail_result = validate_user_input_with_guardrail(message, history_items)
        if not guardrail_result.allowed and guardrail_result.response:
            self.conversation_store.store_conversation(
                session_id=session_id,
                message=message,
                response_text=guardrail_result.response,
                sources=[],
                request_time_epoch=request_time_epoch,
                message_id=message_id,
                blocked_by_guardrail=True,
                domain="blocked",
                langfuse_trace_id=trace_id,
            )
            return {
                "response_text": guardrail_result.response,
                "used_chunks": [],
                "message_id": message_id,
            }

        message_history = items_to_messages(history_items, include_tool_calls=True) if history_items else None
        seed_sources = extract_seed_sources(history_items) if history_items else None

        logger.info(
            "Processing message",
            extra={
                "session_id": mask_session_id(session_id),
                "msg_len": len(message),
                "history_count": len(history_items),
            },
        )

        agent_message = message
        if guardrail_result.correction_instruction:
            agent_message = (
                "[HINWEIS: Die Nutzereingabe enthält möglicherweise eine falsche Annahme oder"
                " drückt Frustration aus. Korrigiere die falsche Annahme höflich, dann beantworte"
                " die Frage sachlich.]\n\n" + message
            )

        agent_result = run_agent(agent, agent_message, message_history=message_history, seed_sources=seed_sources)

        # all_sources = everything retrieved; sources = what the model actually cited.
        all_docs = agent_result.all_sources
        used_chunks = agent_result.sources

        if not all_docs and history_items:
            history_sources = _find_matching_history_sources(history_items, agent_result.result)
            logger.info("No agent sources, falling back to history", extra={"history_sources": len(history_sources)})
            all_docs = history_sources
            used_chunks = history_sources

        logger.info(
            "Message processed",
            extra={
                "session_id": mask_session_id(session_id),
                "response_length": len(agent_result.result),
                "all_docs_count": len(all_docs),
                "used_chunks_count": len(used_chunks),
            },
        )

        # Persist only cited sources: all-chunk persistence produced 40-120KB items near the 400KB cap.
        if message_id:
            classified_domain = next((d.get("domainClassified") for d in all_docs if d.get("domainClassified")), None)
            self.conversation_store.store_conversation(
                session_id=session_id,
                message=message,
                response_text=agent_result.result,
                sources=used_chunks,
                request_time_epoch=request_time_epoch,
                message_id=message_id,
                domain=classified_domain,
                langfuse_trace_id=trace_id,
            )

        return {
            "response_text": agent_result.result,
            "used_chunks": used_chunks,
            # Full retrieved set; controller forwards only on X-Renate-Eval-Mode. Not persisted.
            "all_sources": all_docs,
            "message_id": message_id,
        }

    # Async path (FastAPI / local_dev). Mirrors process_message minus retry logic and trace id,
    # which the Lambda controller plumbs through on the sync path.
    async def process_message_async(
        self,
        message: str,
        session_id: str,
        request_time_epoch: int | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Async version of process_message for FastAPI/async contexts."""
        if not message_id:
            raise ValueError("message_id is required")
        is_valid, error_message = validate_message_length(message)
        if not is_valid:
            raise ValueError(error_message)

        history_items = self.conversation_store.get_history(session_id)
        stored_turn = _find_stored_turn(history_items, message_id)
        if stored_turn is not None:
            return _replay_stored_turn(stored_turn, session_id)
        _enforce_conversation_limit(history_items, session_id)

        guardrail_result = validate_user_input_with_guardrail(message, history_items)
        if not guardrail_result.allowed and guardrail_result.response:
            self.conversation_store.store_conversation(
                session_id=session_id,
                message=message,
                response_text=guardrail_result.response,
                sources=[],
                request_time_epoch=request_time_epoch,
                message_id=message_id,
                blocked_by_guardrail=True,
                domain="blocked",
            )
            return {
                "response_text": guardrail_result.response,
                "used_chunks": [],
                "message_id": message_id,
            }

        message_history = items_to_messages(history_items, include_tool_calls=True) if history_items else None
        seed_sources = extract_seed_sources(history_items) if history_items else None

        logger.info(
            "Processing message (async)",
            extra={
                "session_id": mask_session_id(session_id),
                "msg_len": len(message),
                "history_count": len(history_items),
            },
        )

        agent_message = message
        if guardrail_result.correction_instruction:
            agent_message = (
                "[HINWEIS: Die Nutzereingabe enthält möglicherweise eine falsche Annahme oder"
                " drückt Frustration aus. Korrigiere die falsche Annahme höflich, dann beantworte"
                " die Frage sachlich.]\n\n" + message
            )

        agent_result = await run_agent_async(
            self._agent, agent_message, message_history=message_history, seed_sources=seed_sources
        )

        all_docs = agent_result.all_sources
        used_chunks = agent_result.sources

        if not all_docs and history_items:
            history_sources = _find_matching_history_sources(history_items, agent_result.result)
            logger.info("No agent sources, falling back to history", extra={"history_sources": len(history_sources)})
            all_docs = history_sources
            used_chunks = history_sources

        logger.info(
            "Message processed",
            extra={
                "session_id": mask_session_id(session_id),
                "all_docs_count": len(all_docs),
                "used_chunks_count": len(used_chunks),
            },
        )

        self.conversation_store.store_conversation(
            session_id=session_id,
            message=message,
            response_text=agent_result.result,
            sources=used_chunks,
            request_time_epoch=request_time_epoch,
            message_id=message_id,
            domain=next((d.get("domainClassified") for d in all_docs if d.get("domainClassified")), None),
        )

        return {
            "response_text": agent_result.result,
            "used_chunks": used_chunks,
            "all_sources": all_docs,
            "message_id": message_id,
        }

    def store_feedback(
        self,
        session_id: str,
        message_id: str,
        feedback: dict[str, Any],
    ) -> bool:
        """Store the 3-button rating of an answer unchanged and send it to Langfuse. Returns True on success."""
        result = self.conversation_store.update_feedback(session_id, message_id, feedback)
        if result:
            _emit_feedback_written(producer="external_3button", scope="message", schema_version="v1_en_3value")

        item = self.conversation_store.get_message(session_id, message_id)
        if not (item and item.langfuse_trace_id):
            return result

        raw_comment = _feedback_get(feedback, "comment")
        comment = raw_comment if isinstance(raw_comment, str) and raw_comment else None
        values = {field: _feedback_get(feedback, field) for field in FEEDBACK_SCORE_SCHEMA}
        post_langfuse_scores(
            _build_score_events(values, trace_id=item.langfuse_trace_id, id_prefix=message_id, comment=comment)
        )
        return result

    def store_rating(
        self,
        session_id: str,
        message_id: str | None,
        rating: InternalRating,
        user_id: str | None,
    ) -> bool:
        """Store a rating of a tester form and send it to Langfuse.

        Ratings of one answer go on the answer row and its trace. Dialog ratings and
        final feedback go on their own row and on the Langfuse session.
        """
        stored = build_stored_map(rating, user_id)
        if rating.rates_answer:
            if not message_id:
                return False
            return self._store_answer_rating(session_id, message_id, rating, stored)
        return self._store_conversation_rating(session_id, rating, stored)

    def _store_answer_rating(
        self, session_id: str, message_id: str, rating: InternalRating, stored: dict[str, Any]
    ) -> bool:
        if not self.conversation_store.update_feedback(session_id, message_id, stored):
            return False
        _emit_feedback_written(producer=rating.producer, scope=rating.scope, schema_version=SCHEMA_VERSION)

        item = self.conversation_store.get_message(session_id, message_id)
        if not (item and item.langfuse_trace_id):
            return True
        post_langfuse_scores(
            _build_score_events(
                {**rating.ratings, "used_scenario": rating.used_scenario},
                trace_id=item.langfuse_trace_id,
                id_prefix=message_id,
                comment=rating.comment,
                reasons=rating.reasons,
                metadata=_rating_metadata(rating),
            )
        )
        return True

    def _store_conversation_rating(self, session_id: str, rating: InternalRating, stored: dict[str, Any]) -> bool:
        sort_key = RATING_DIALOG if rating.scope == "dialog" else RATING_FINAL
        if not self.conversation_store.put_rating_row(session_id, sort_key, stored):
            return False
        _emit_feedback_written(producer=rating.producer, scope=rating.scope, schema_version=SCHEMA_VERSION)

        post_langfuse_scores(
            _build_score_events(
                {**rating.ratings, "used_scenario": rating.used_scenario},
                session_id=session_id,
                id_prefix=f"{session_id}#{sort_key}",
                comment=rating.comment,
                reasons=rating.reasons,
                metadata=_rating_metadata(rating),
            )
        )
        return True


_MIN_SIMILARITY = 0.3


def _find_matching_history_sources(
    items: list[ConversationItem],
    response_text: str,
) -> list[dict[str, Any]]:
    """Find the history turn whose response best matches and return its sources."""
    best_ratio = 0.0
    best_sources: list[dict[str, Any]] = []
    for item in items:
        if not item.sources:
            continue
        ratio = SequenceMatcher(None, item.response_text, response_text).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_sources = item.sources
    return best_sources if best_ratio > _MIN_SIMILARITY else []
