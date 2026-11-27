"""Controller layer for chat operations."""

from dataclasses import dataclass
from typing import Any

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, InternalServerError, ServiceError
from opentelemetry import baggage, context
from opentelemetry import trace as otel_trace
from opentelemetry.trace import format_span_id, format_trace_id

from backend_orchestrator.config import get_config
from backend_orchestrator.observability import set_langfuse_trace_context, set_langfuse_trace_output
from backend_orchestrator.repositories.conversation import HistoryReadError
from backend_orchestrator.response_parser import build_chat_response
from backend_orchestrator.services.chat_service import ChatService, ConversationLimitReachedError
from backend_orchestrator.services.feedback_rating import (
    FeedbackValidationError,
    InternalRating,
    is_external,
    validate_external,
    validate_internal,
)
from backend_orchestrator.utils.session_masking import mask_message_id, mask_session_id, sanitize_error_message
from backend_orchestrator.validation import extract_message_text

logger = Logger(child=True)
tracer = Tracer()
_otel_tracer = otel_trace.get_tracer(__name__)

# Caller-supplied Langfuse trace tags. The eval golden-run uses this to tag
# synthetic traffic (`golden-run`, `env:<env>`, `run:<run_name>`) so the
# Langfuse Traces view can separate it from real users. Hard caps below exist
# because tags land on a shared surface and arbitrary strings are noise.
_TRACE_TAGS_HEADER = "X-Langfuse-Trace-Tags"
_TRACE_TAGS_MAX_COUNT = 10
_TRACE_TAGS_MAX_LEN = 100

# Opt-in header for synthetic eval jobs (renate/scheduled/evaluation#14).
# When truthy, the response carries ``all_sources`` so DeepEval scorers see
# the full retrieved set, not just the cited subset. Omitted by default so
# frontend/mobile payloads stay unchanged.
_EVAL_MODE_HEADER = "X-Renate-Eval-Mode"

# Langfuse v4 Experiments OTel contract (digibro-monorepo#957): when the eval
# client provides all four, the chat trace is indexed as an experiment item
# run and shows up in GET /api/public/experiments + the Experiments UI.
# Three ride on baggage (experiment-level, every span inherits), one lands
# directly on the chat.request root span (item-level).
# https://langfuse.com/integrations/native/opentelemetry/experiments
_EXPERIMENT_ID_HEADER = "X-Renate-Experiment-Id"
_EXPERIMENT_NAME_HEADER = "X-Renate-Experiment-Name"
_EXPERIMENT_DATASET_ID_HEADER = "X-Renate-Experiment-Dataset-Id"
_EXPERIMENT_ITEM_ID_HEADER = "X-Renate-Experiment-Item-Id"

# Opt-in override for ``langfuse.user.id`` on synthetic eval traffic
# (renate/scheduled/evaluation#9). The default user_id is the Cognito ``sub``
# claim of the service user running the pipeline — which looks identical to
# real users in Langfuse dashboards. Golden-run sends e.g.
# ``synthetic:eval:pipeline-14390`` here to keep synthetic traffic out of
# "most frequent queries", latency p95, and the user.helpfulness correlation
# workbench. Gated by ``_eval_mode_enabled`` → hard-off in prod.
_USER_ID_OVERRIDE_HEADER = "X-Renate-User-Id"

# Response for a conversation that reached MAX_MESSAGES_PER_CONVERSATION (#992).
# 409 is used nowhere else in the API, so the frontend maps it 1:1 to its notice.
CONVERSATION_LIMIT_STATUS = 409
CONVERSATION_LIMIT_ERROR = "conversation_limit_reached"


def _resolve_trace_tags(app: APIGatewayRestResolver, review_tag: str) -> list[str] | None:
    """Merge the review-env tag with caller-supplied header tags.

    Returns ``None`` when both sources are empty so the OTel attribute is
    omitted entirely (``set_langfuse_trace_context`` writes it only when
    tags is truthy).
    """
    header = _lookup_header_ci(getattr(app.current_event, "headers", None), _TRACE_TAGS_HEADER)
    header_tags: list[str] = []
    if header:
        for raw in header.split(","):
            tag = raw.strip()
            if tag and len(tag) <= _TRACE_TAGS_MAX_LEN:
                header_tags.append(tag)
            if len(header_tags) >= _TRACE_TAGS_MAX_COUNT:
                break
    review_tags = [review_tag] if review_tag else []
    combined = review_tags + header_tags
    return combined or None


@dataclass(frozen=True)
class _ExperimentContext:
    """Four values that together link one chat request to a Langfuse experiment item."""

    experiment_id: str
    experiment_name: str
    dataset_id: str
    item_id: str


def _resolve_experiment_context(app: APIGatewayRestResolver) -> _ExperimentContext | None:
    """Read the four X-Renate-Experiment-* headers; all four required or None.

    Only honoured when ``_eval_mode_enabled`` is true, which is hard-off in prod.
    Partial headers (e.g. the client sends name but omits dataset-id) are treated
    as absent — a partially-tagged trace confuses the Experiments UI more than an
    untagged one, so refuse rather than best-effort.
    """
    if not _eval_mode_enabled(app):
        return None
    headers = getattr(app.current_event, "headers", None)
    exp_id = _lookup_header_ci(headers, _EXPERIMENT_ID_HEADER)
    exp_name = _lookup_header_ci(headers, _EXPERIMENT_NAME_HEADER)
    dataset_id = _lookup_header_ci(headers, _EXPERIMENT_DATASET_ID_HEADER)
    item_id = _lookup_header_ci(headers, _EXPERIMENT_ITEM_ID_HEADER)
    values = [v.strip() if v else "" for v in (exp_id, exp_name, dataset_id, item_id)]
    if not all(values):
        return None
    return _ExperimentContext(
        experiment_id=values[0],
        experiment_name=values[1],
        dataset_id=values[2],
        item_id=values[3],
    )


def _resolve_user_id_override(app: APIGatewayRestResolver) -> str | None:
    """Eval-only override for the Cognito-derived ``user_id``.

    Lets golden-run tag its traces with a synthetic marker (e.g.
    ``synthetic:eval:pipeline-14390``) so dashboards and the user.helpfulness
    correlation workbench can filter real users from automated traffic.
    Gated by ``_eval_mode_enabled`` — hard-off in prod regardless of header.
    Empty/whitespace values are treated as absent (defensive).
    """
    if not _eval_mode_enabled(app):
        return None
    raw = _lookup_header_ci(getattr(app.current_event, "headers", None), _USER_ID_OVERRIDE_HEADER)
    if not raw:
        return None
    stripped = raw.strip()
    return stripped or None


def _eval_mode_enabled(app: APIGatewayRestResolver) -> bool:
    """Return whether the caller requested the eval-mode response shape.

    Hard-off in production: a prod chat response must never surface
    ``all_sources`` or the internal retrieval signals (``sectionTitle``,
    ``domainTier``) regardless of what header the caller sends. The eval
    job runs against DEV/QA only — see renate/scheduled/evaluation#14.
    """
    if getattr(get_config(), "environment", "") == "prod":
        return False
    raw = _lookup_header_ci(getattr(app.current_event, "headers", None), _EVAL_MODE_HEADER)
    if not raw:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _lookup_header_ci(headers: dict[str, str] | None, name: str) -> str | None:
    """Case-insensitive single-header lookup.

    REST API Gateway preserves header casing as the client sent it, so a
    client sending ``x-langfuse-trace-tags`` would not match a plain
    ``headers.get("X-Langfuse-Trace-Tags")``. Powertools' deprecated
    ``get_header_value(case_sensitive=False)`` did this fold internally.
    """
    if not headers:
        return None
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return value
    return None


def _parse_chat_body(body: dict[str, Any]) -> tuple[str, str, str | None]:
    """Return (message, session_id, message_id) from a chat body. Raises ValueError on a bad message.

    session_id is "" when absent or not a string; message_id may sit in the message or at top level.
    """
    message = extract_message_text(body)
    session_id = body.get("conversationId", body.get("conversation_id", "")) or ""
    if not isinstance(session_id, str):
        session_id = ""
    message_id = None
    message_payload = body.get("message")
    if isinstance(message_payload, dict):
        message_id = message_payload.get("messageId") or message_payload.get("message_id")
    message_id = message_id or body.get("message_id") or body.get("messageId")
    return message, session_id, message_id


def _parse_feedback_body(body: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Return the message id and the feedback, which is either nested or the flat body."""
    message_id = body.get("message_id") or body.get("messageId")
    feedback = body.get("feedback")
    if feedback is None:
        feedback = {key: value for key, value in body.items() if key not in {"message_id", "messageId"}}
    if not feedback:
        raise BadRequestError("feedback is required")
    return message_id, feedback


def _validate_feedback(feedback: dict[str, Any], message_id: str | None) -> InternalRating | None:
    """Return the validated tester rating, or None for the 3-button rating. Raise 422 on errors."""
    try:
        if is_external(feedback):
            validate_external(feedback)
            return None
        return validate_internal(feedback, message_id)
    except FeedbackValidationError as e:
        raise ServiceError(422, str(e)) from e


class ChatController:
    """Controller for handling chat API requests."""

    def __init__(self, service: ChatService):
        """Initialize controller with service dependency."""
        self.service = service

    def _extract_user_context(self, event) -> tuple[str | None, str | None]:
        """Extract user ID and username from event context.

        Args:
            event: API Gateway event

        Returns:
            Tuple of (user_id, username)

        """
        user_id = None
        username = None
        if hasattr(event, "request_context"):
            authorizer = getattr(event.request_context, "authorizer", None)
            if authorizer:
                claims = authorizer.get("claims", {})
                user_id = claims.get("sub")
                username = claims.get("cognito:username")
        return user_id, username

    @tracer.capture_method(capture_response=False)
    def handle_chat_request(self, app: APIGatewayRestResolver) -> dict[str, Any]:
        """Handle the chat request from API Gateway.

        Args:
            app: The APIGatewayRestResolver instance containing the current event

        Returns:
            API Gateway response dictionary

        """
        session_id = ""  # json_body decoding can raise ValueError; keep defined for the error sanitizer below
        try:
            message, session_id, message_id = _parse_chat_body(app.current_event.json_body)
            user_id, username = self._extract_user_context(app.current_event)

            # Eval-only: let golden-run swap in a synthetic marker so its
            # traces are separable from real users in Langfuse. username stays
            # the Cognito-side value so backend logs still identify the
            # service user that initiated the run.
            user_id_override = _resolve_user_id_override(app)
            if user_id_override is not None:
                user_id = user_id_override

            if not session_id and user_id:
                session_id = user_id
            if not message_id:
                raise BadRequestError("message_id is required")  # noqa: TRY301

            logger.info(
                "Chat request - START",
                extra={
                    "username": username,
                    "user_id": user_id,
                    "session_id": mask_session_id(session_id),
                    "message_length": len(message),
                },
            )

            request_time_epoch = (
                app.current_event.request_context.request_time_epoch
                if hasattr(app.current_event, "request_context")
                else None
            )

            result, trace_id, root_span_id = self._process_traced(
                app,
                message=message,
                session_id=session_id,
                message_id=message_id,
                user_id=user_id,
                request_time_epoch=request_time_epoch,
            )

            logger.info(
                "Chat request - END",
                extra={
                    "session_id": mask_session_id(session_id),
                    "response_len": len(result.get("response_text", "")),
                },
            )

            eval_mode = _eval_mode_enabled(app)
            return build_chat_response(
                session_id=session_id,
                response_text=result["response_text"],
                used_chunks=result["used_chunks"],
                request_time_epoch=request_time_epoch,
                message_id=result.get("message_id"),
                trace_id=trace_id,
                all_sources=result.get("all_sources") if eval_mode else None,
                root_span_id=root_span_id if eval_mode else None,
                eval_mode=eval_mode,
            )

        except ValueError as e:
            logger.warning(f"Validation error: {e}")
            raise BadRequestError(sanitize_error_message(str(e), session_id)) from e

        except ConversationLimitReachedError:
            # Own status so the frontend can show "start a new conversation" (#992).
            raise ServiceError(CONVERSATION_LIMIT_STATUS, CONVERSATION_LIMIT_ERROR) from None
        except HistoryReadError:
            # Fail-closed: no reliable message count, so no model call. 503 lets the frontend retry.
            raise ServiceError(503, "Conversation history unavailable") from None

        except (BadRequestError, InternalServerError):
            raise
        except Exception:
            logger.exception("Error processing chat request")
            raise InternalServerError("Internal server error") from None

    def _process_traced(
        self,
        app: APIGatewayRestResolver,
        *,
        message: str,
        session_id: str,
        message_id: str,
        user_id: str | None,
        request_time_epoch: int | None,
    ) -> tuple[dict[str, Any], str, str]:
        """Run the service inside the chat.request span; return (result, trace_id, root_span_id)."""
        # Attach trace-level identifiers to baggage so the baggage span
        # processor stamps them onto every child span (ours + pydantic-ai).
        # Needed for Langfuse v4 events_only + direct, where server-side
        # attribute propagation is dropped. Detach in finally to prevent
        # leaking across Lambda invocations.
        ctx = baggage.set_baggage("langfuse.session.id", session_id)
        ctx = baggage.set_baggage("langfuse.user.id", user_id or "", context=ctx)
        exp_ctx = _resolve_experiment_context(app)
        if exp_ctx is not None:
            ctx = baggage.set_baggage("langfuse.experiment.id", exp_ctx.experiment_id, context=ctx)
            ctx = baggage.set_baggage("langfuse.experiment.name", exp_ctx.experiment_name, context=ctx)
            ctx = baggage.set_baggage("langfuse.experiment.dataset.id", exp_ctx.dataset_id, context=ctx)
        baggage_token = context.attach(ctx)
        try:
            with _otel_tracer.start_as_current_span("chat.request") as span:
                config = get_config()
                set_langfuse_trace_context(
                    span,
                    session_id=session_id,
                    user_id=user_id or "",
                    input_text=message,
                    model=config.bedrock_model_id,
                    message_id=message_id or "",
                    environment=config.langfuse_environment,
                    tags=_resolve_trace_tags(app, config.langfuse_review_tag),
                    experiment_item_id=exp_ctx.item_id if exp_ctx is not None else None,
                )
                trace_id = format_trace_id(span.get_span_context().trace_id)
                root_span_id = format_span_id(span.get_span_context().span_id)
                # Item context (per v4 docs §3) must ride on Baggage as well so
                # child spans — pydantic-ai LLM calls, retrieval, guardrail —
                # carry the item identity, not just the chat.request root.
                # root_observation_id is the root span's own span id, so this
                # attach has to happen AFTER the span has started (not with the
                # experiment-level baggage up front).
                item_token = None
                if exp_ctx is not None:
                    item_ctx = baggage.set_baggage("langfuse.experiment.item.id", exp_ctx.item_id)
                    item_ctx = baggage.set_baggage(
                        "langfuse.experiment.item.root_observation_id",
                        root_span_id,
                        context=item_ctx,
                    )
                    item_token = context.attach(item_ctx)
                try:
                    result = self.service.process_message(
                        message,
                        session_id,
                        request_time_epoch,
                        message_id,
                        trace_id=trace_id,
                    )
                finally:
                    if item_token is not None:
                        context.detach(item_token)
                set_langfuse_trace_output(span, result.get("response_text", ""))
        finally:
            context.detach(baggage_token)
        return result, trace_id, root_span_id

    @tracer.capture_method(capture_response=False)
    def handle_feedback_request(self, app: APIGatewayRestResolver, session_id: str) -> dict[str, Any]:
        """Handle feedback requests for a conversation entry."""
        try:
            if not session_id:
                raise BadRequestError("session_id is required")  # noqa: TRY301
            message_id, feedback = _parse_feedback_body(app.current_event.json_body or {})
            rating = _validate_feedback(feedback, message_id)

            user_id, username = self._extract_user_context(app.current_event)

            logger.info(
                "Feedback request",
                extra={
                    "username": username,
                    "user_id": user_id,
                    "session_id": mask_session_id(session_id),
                    "message_id": mask_message_id(message_id),
                },
            )

            if rating is None:
                if not message_id:
                    raise BadRequestError("message_id is required")  # noqa: TRY301
                if user_id:
                    feedback["user_id"] = user_id
                success = self.service.store_feedback(
                    session_id=session_id,
                    message_id=message_id,
                    feedback=feedback,
                )
            else:
                success = self.service.store_rating(
                    session_id=session_id,
                    message_id=message_id,
                    rating=rating,
                    user_id=user_id,
                )
        except ServiceError:
            raise
        except Exception:
            logger.exception("Error processing feedback request")
            raise InternalServerError("Internal server error") from None
        else:
            return {"success": success}
