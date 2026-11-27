"""Guardrail validation: Bedrock hard filters + lightweight classification agent."""

from dataclasses import dataclass

import boto3
from aws_lambda_powertools import Logger
from opentelemetry import trace

from backend_orchestrator.config import get_config
from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.utils.history_converter import drop_blocked_turns
from backend_orchestrator.validators.guardrail_agent import (
    CLARIFY_RESPONSE,
    STANDARD_RESPONSE_1,
    STANDARD_RESPONSE_2,
    GuardrailCategory,
    classify_user_input,
)

logger = Logger(child=True)

# Two turns are enough to anchor a follow-up to its topic; the user message and
# response are truncated because only the topic matters for classification.
_CONTEXT_MAX_TURNS = 2
_CONTEXT_MAX_RESPONSE_CHARS = 300
# Bound the attacker-controlled user message before it reaches the classifier.
_CONTEXT_MAX_USER_CHARS = 500


def _get_tracer():
    return trace.get_tracer(__name__)


@dataclass
class GuardrailResult:
    """Result of the two-layer guardrail validation."""

    allowed: bool
    response: str | None = None
    correction_instruction: str | None = None


def _extract_triggered_filters(assessments: list) -> str:
    """Extract which Bedrock guardrail filters triggered from assessments."""
    triggered = []
    for assessment in assessments:
        for policy_key, policy_val in assessment.items():
            if not isinstance(policy_val, dict):
                continue
            for f in policy_val.get("filters", []):
                if f.get("action") == "BLOCKED":
                    triggered.append(f"{policy_key}:{f.get('type', 'unknown')}")
            for t in policy_val.get("topics", []):
                if t.get("action") == "BLOCKED":
                    triggered.append(f"topic:{t.get('name', 'unknown')}")
            for p in policy_val.get("piiEntities", []):
                if p.get("action") == "BLOCKED":
                    # A Bedrock PII match contains the user's raw text; keep
                    # only the controlled entity type in OTel metadata.
                    triggered.append(f"pii:{p.get('type', 'unknown')}")
    return ", ".join(triggered) or "unknown"


def _validate_with_bedrock_guardrail(user_message: str) -> str | None:
    """Validate user input against Bedrock hard guardrails.

    Returns a blocked message if a violation is detected, else None.
    """
    config = get_config()

    if not config.bedrock_guardrail_id:
        return None

    with _get_tracer().start_as_current_span("guardrail.bedrock") as span:
        span.set_attribute("guardrail.layer", "bedrock")
        try:
            client = boto3.client("bedrock-runtime", region_name=config.aws_region)

            response = client.apply_guardrail(
                guardrailIdentifier=config.bedrock_guardrail_id,
                guardrailVersion=config.bedrock_guardrail_version,
                source="INPUT",
                content=[{"text": {"text": user_message}}],
            )

            action = response.get("action")
            span.set_attribute("guardrail.action", action or "NONE")

            if action == "GUARDRAIL_INTERVENED":
                assessments = response.get("assessments", [])
                span.set_attribute("guardrail.blocked", True)
                span.set_attribute("guardrail.triggered_filters", _extract_triggered_filters(assessments))
                logger.warning(
                    "Bedrock guardrail blocked user input",
                    extra={
                        "assessments": assessments,
                        "guardrail_layer": "bedrock",
                        "guardrail_category": "BEDROCK_BLOCKED",
                    },
                )
                return STANDARD_RESPONSE_1

            span.set_attribute("guardrail.blocked", False)

        except Exception as e:
            span.set_attribute("guardrail.error", "validation_failed")
            logger.exception("Bedrock guardrail validation failed, failing closed", extra={"error": str(e)})
            return "Es ist ein technischer Fehler aufgetreten. Bitte versuchen Sie es erneut."

    return None


def _format_conversation_context(history_items: list[ConversationItem] | None) -> str | None:
    """Render the most recent real turns as a compact transcript for the classifier.

    Guardrail-blocked turns are dropped: a canned refusal is not real dialogue,
    and replaying an attacker's blocked-then-rephrased message as "ongoing
    conversation" would nudge the classifier toward lenient follow-up handling.
    Both user and response strings are length-bounded. Returns None when there
    is no real prior dialogue.
    """
    real = drop_blocked_turns(history_items or [])
    if not real:
        return None
    lines: list[str] = []
    for item in real[-_CONTEXT_MAX_TURNS:]:
        message = (item.message or "").strip()
        if len(message) > _CONTEXT_MAX_USER_CHARS:
            message = message[:_CONTEXT_MAX_USER_CHARS] + " …"
        lines.append(f"Nutzer: {message}")
        response = (item.response_text or "").strip()
        if len(response) > _CONTEXT_MAX_RESPONSE_CHARS:
            response = response[:_CONTEXT_MAX_RESPONSE_CHARS] + " …"
        lines.append(f"Renate: {response}")
    return "\n".join(lines)


def validate_user_input_with_guardrail(
    user_message: str,
    history_items: list[ConversationItem] | None = None,
) -> GuardrailResult:
    """Two-layer guardrail validation: Bedrock hard filters, then classification agent.

    Args:
        user_message: The raw user message to validate
        history_items: Recent conversation turns; lets the classification agent judge
            follow-ups in context instead of blocking them as vague/off-topic.
    """
    # Layer 1: Bedrock hard guardrail judges the raw message only, deliberately
    # without context.
    bedrock_blocked = _validate_with_bedrock_guardrail(user_message)
    if bedrock_blocked:
        return GuardrailResult(allowed=False, response=bedrock_blocked)

    # Layer 2: nuanced topic filtering. Context is computed once and reused for
    # the CLARIFY downgrade below so "is there context?" means the same in both.
    conversation_context = _format_conversation_context(history_items)
    classification = classify_user_input(user_message, conversation_context)

    logger.info(
        "Guardrail agent classification",
        extra={
            "guardrail_category": classification.category.value,
            "guardrail_reason": classification.reason,
            "guardrail_has_context": bool(conversation_context),
        },
    )

    if classification.category == GuardrailCategory.ALLOW:
        return GuardrailResult(allowed=True)

    if classification.category == GuardrailCategory.ALLOW_WITH_CORRECTION:
        return GuardrailResult(allowed=True, correction_instruction=classification.reason)

    if classification.category == GuardrailCategory.CLARIFY:
        # Mid-conversation a vague message is almost always a follow-up; the
        # main agent can ask a better clarifying question than the canned one.
        # A session of only blocked turns is not "mid-conversation".
        if conversation_context:
            return GuardrailResult(allowed=True)
        return GuardrailResult(allowed=False, response=CLARIFY_RESPONSE)

    if classification.category == GuardrailCategory.BLOCK_STANDARD_2:
        return GuardrailResult(allowed=False, response=STANDARD_RESPONSE_2)

    return GuardrailResult(allowed=False, response=STANDARD_RESPONSE_1)
