"""Classify and validate a feedback request, and build the map stored in DynamoDB."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend_orchestrator.models.api_models import MessageFeedback, to_camel

SCHEMA_VERSION = "v2_en_4plus1"

# (producer, scope) → (required criteria, optional criteria)
FORM_CRITERIA: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {
    ("internal_single_turn", "message"): (
        (
            "technical_correctivity",
            "coverage_level",
            "tonality",
            "comprehensibility",
            "precision",
            "source_matching",
            "source_quality",
            "comparability_to_google_ai",
        ),
        (),
    ),
    ("internal_multi_turn", "turn"): (("technical_correctivity",), ()),
    ("internal_multi_turn", "dialog"): (("dialogue_skills", "goal_achievement"), ("handling_corrections",)),
    ("internal_final_feedback", "test"): (("good_to_recommend",), ()),
}

RATING_FIELDS = (
    "technical_correctivity",
    "coverage_level",
    "comprehensibility",
    "precision",
    "tonality",
    "utility_value",
    "comparability_to_google_ai",
    "source_matching",
    "source_quality",
    "goal_achievement",
    "dialogue_skills",
    "handling_corrections",
    "further_development",
    "good_to_recommend",
    "helpfulness",
)

_FLAGS = ("is_multiturn", "is_singleturn", "is_free_user_test", "is_final_feedback", "is_per_turn_feedback")


class FeedbackValidationError(ValueError):
    """The request is not a valid rating. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class InternalRating:
    """A validated rating from one of the tester forms."""

    producer: str
    scope: str
    ratings: dict[str, str]
    reasons: dict[str, str]
    comment: str | None
    used_scenario: int | None

    @property
    def rates_answer(self) -> bool:
        """Return True if the rating is stored on an answer row."""
        return self.scope in ("message", "turn")


def _get(body: dict[str, Any], field: str) -> Any:
    if field in body:
        return body[field]
    return body.get(to_camel(field))


def is_external(body: dict[str, Any]) -> bool:
    """Return True for the 3-button rating: no producer and no is_* flag set to true."""
    return _get(body, "producer") is None and not any(_get(body, flag) is True for flag in _FLAGS)


def _derive_producer_scope(feedback: MessageFeedback) -> tuple[str, str]:
    if feedback.producer is not None or feedback.scope is not None:
        if feedback.producer is None or feedback.scope is None:
            raise FeedbackValidationError(["producer and scope must be sent together"])
        return feedback.producer, feedback.scope
    if feedback.is_per_turn_feedback:
        return "internal_multi_turn", "turn"
    forms = {
        ("internal_multi_turn", "dialog"): feedback.is_multiturn,
        ("internal_single_turn", "message"): feedback.is_singleturn,
        ("internal_final_feedback", "test"): feedback.is_final_feedback,
    }
    chosen = [form for form, flag in forms.items() if flag]
    if len(chosen) != 1:
        raise FeedbackValidationError(["exactly one of isMultiturn, isSingleturn and isFinalFeedback must be true"])
    return chosen[0]


def _collect_criteria(
    feedback: MessageFeedback, required: tuple[str, ...], optional: tuple[str, ...]
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return the ratings and reasons of the form, and an error for each missing or foreign criterion."""
    allowed = set(required) | set(optional)
    errors: list[str] = []
    ratings: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for field in RATING_FIELDS:
        value = getattr(feedback, field) or None
        reason = getattr(feedback, f"{field}_reason", None) or None
        if field not in allowed:
            if value is not None:
                errors.append(f"{to_camel(field)} is not a criterion of this form")
            if reason is not None:
                errors.append(f"{to_camel(field)}Reason is not a criterion of this form")
            continue
        if value is not None:
            ratings[field] = value
        elif field in required:
            errors.append(f"{to_camel(field)} is required")
        if reason is not None:
            reasons[field] = reason
    return ratings, reasons, errors


def validate_internal(body: dict[str, Any], message_id: str | None) -> InternalRating:
    """Validate a rating from a tester form against MessageFeedback and the rules of its form."""
    try:
        feedback = MessageFeedback.model_validate(body)
    except ValidationError as e:
        raise FeedbackValidationError([
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in e.errors()
        ]) from e

    producer, scope = _derive_producer_scope(feedback)
    if (producer, scope) not in FORM_CRITERIA:
        raise FeedbackValidationError([f"producer {producer} with scope {scope} is not allowed"])
    ratings, reasons, errors = _collect_criteria(feedback, *FORM_CRITERIA[(producer, scope)])

    if scope == "dialog" and feedback.used_scenario is None:
        errors.append("usedScenario is required")
    if scope in ("message", "turn") and not message_id:
        errors.append("messageId is required")
    if errors:
        raise FeedbackValidationError(errors)

    return InternalRating(
        producer=producer,
        scope=scope,
        ratings=ratings,
        reasons=reasons,
        comment=feedback.comment or None,
        used_scenario=feedback.used_scenario if scope in ("dialog", "turn") else None,
    )


def validate_external(body: dict[str, Any]) -> None:
    """Check the only rated field of the 3-button rating."""
    helpfulness = _get(body, "helpfulness")
    if helpfulness not in (None, "GOOD", "NEUTRAL", "BAD"):
        raise FeedbackValidationError(["helpfulness must be GOOD, NEUTRAL, BAD or null"])


def build_stored_map(rating: InternalRating, user_id: str | None) -> dict[str, Any]:
    """Return the map for the column ``feedback``. Empty values are left out."""
    stored: dict[str, Any] = {
        "producer": rating.producer,
        "scope": rating.scope,
        "schema_version": SCHEMA_VERSION,
        "ratings": rating.ratings,
    }
    if rating.reasons:
        stored["reasons"] = rating.reasons
    if rating.comment:
        stored["comment"] = rating.comment
    if rating.used_scenario is not None:
        stored["used_scenario"] = rating.used_scenario
    if user_id:
        stored["user_id"] = user_id
    return stored
