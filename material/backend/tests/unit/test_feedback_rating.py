"""Tests for classifying, validating and storing feedback requests."""

import pytest

from backend_orchestrator.services.feedback_rating import (
    FeedbackValidationError,
    build_stored_map,
    is_external,
    validate_external,
    validate_internal,
)

_ALL_RATING_FIELDS_NULL = {
    "technicalCorrectivity": None,
    "coverageLevel": None,
    "comprehensibility": None,
    "tonality": None,
    "utilityValue": None,
    "comparabilityToGoogleAi": None,
    "sourceMatching": None,
    "sourceQuality": None,
    "usedScenario": None,
    "goalAchievement": None,
    "dialogueSkills": None,
    "handlingCorrections": None,
    "furtherDevelopment": None,
    "goodToRecommend": None,
    "precision": None,
    "comment": "",
    "helpfulness": None,
}


def _frontend_body(**fields):
    """Body as the frontend on main builds it: every rating field, only the flag of the form."""
    return {**_ALL_RATING_FIELDS_NULL, **fields}


SINGLE_TURN = _frontend_body(
    isSingleturn=True,
    technicalCorrectivity="Yes",
    coverageLevel="Likely yes",
    tonality="Yes",
    comprehensibility="Yes",
    precision="Probably not",
    sourceMatching="Yes",
    sourceQuality="Cannot evaluate",
    comparabilityToGoogleAi="Equally good",
    comment="Quelle passt",
)
DIALOG = _frontend_body(
    isMultiturn=True,
    usedScenario=3,
    dialogueSkills="Probably not",
    goalAchievement="Yes",
)
FINAL = _frontend_body(isFinalFeedback=True, goodToRecommend="Likely yes")
TURN = {
    "isMultiturn": True,
    "isPerTurnFeedback": True,
    "usedScenario": 3,
    "technicalCorrectivity": "Likely yes",
    "technicalCorrectivityReason": "Abschläge fehlen",
    "comment": "",
}
EXTERNAL = {
    "comment": None,
    "helpfulness": "GOOD",
    "isFinalFeedback": False,
    "isFreeUserTest": False,
    "isMultiturn": False,
    "isSingleturn": False,
}


class TestIsExternal:
    def test_three_button_body_is_external(self):
        assert is_external(EXTERNAL)

    @pytest.mark.parametrize("body", [SINGLE_TURN, DIALOG, FINAL, TURN, {"producer": "internal_multi_turn"}])
    def test_internal_bodies_are_not_external(self, body):
        assert not is_external(body)


class TestValidateExternal:
    @pytest.mark.parametrize("value", ["GOOD", "NEUTRAL", "BAD", None])
    def test_accepts_frontend_values(self, value):
        validate_external({**EXTERNAL, "helpfulness": value})

    def test_accepts_old_thumbs_up_body(self):
        validate_external({"thumbsUp": "GOOD", "isMultiturn": False})

    def test_rejects_other_values(self):
        with pytest.raises(FeedbackValidationError):
            validate_external({**EXTERNAL, "helpfulness": "Yes"})


class TestDerivedForm:
    @pytest.mark.parametrize(
        ("body", "producer", "scope"),
        [
            (SINGLE_TURN, "internal_single_turn", "message"),
            (TURN, "internal_multi_turn", "turn"),
            (DIALOG, "internal_multi_turn", "dialog"),
            (FINAL, "internal_final_feedback", "test"),
        ],
    )
    def test_flags_map_to_producer_and_scope(self, body, producer, scope):
        rating = validate_internal(body, "s-1#a1")
        assert (rating.producer, rating.scope) == (producer, scope)

    def test_explicit_producer_and_scope_win_over_flags(self):
        body = {**FINAL, "isFinalFeedback": False, "producer": "internal_final_feedback", "scope": "test"}
        rating = validate_internal(body, None)
        assert (rating.producer, rating.scope) == ("internal_final_feedback", "test")

    def test_producer_without_scope_rejected(self):
        with pytest.raises(FeedbackValidationError, match="together"):
            validate_internal({**FINAL, "producer": "internal_final_feedback"}, None)

    def test_two_form_flags_rejected(self):
        with pytest.raises(FeedbackValidationError, match="exactly one"):
            validate_internal({**FINAL, "isSingleturn": True}, "s-1#a1")

    def test_free_user_test_rejected(self):
        with pytest.raises(FeedbackValidationError, match="exactly one"):
            validate_internal(_frontend_body(isFreeUserTest=True, utilityValue="Yes"), "s-1#a1")

    def test_disallowed_pair_rejected(self):
        body = {**SINGLE_TURN, "producer": "internal_single_turn", "scope": "dialog"}
        with pytest.raises(FeedbackValidationError, match="not allowed"):
            validate_internal(body, "s-1#a1")


class TestFormRules:
    def test_single_turn_keeps_all_ratings_and_comment(self):
        rating = validate_internal(SINGLE_TURN, "s-1#a1")
        assert len(rating.ratings) == 8
        assert rating.ratings["comparability_to_google_ai"] == "Equally good"
        assert rating.comment == "Quelle passt"
        assert rating.used_scenario is None

    def test_missing_required_criterion_rejected(self):
        with pytest.raises(FeedbackValidationError, match="tonality is required"):
            validate_internal({**SINGLE_TURN, "tonality": None}, "s-1#a1")

    def test_criterion_of_other_form_rejected(self):
        with pytest.raises(FeedbackValidationError, match="goodToRecommend is not a criterion"):
            validate_internal({**DIALOG, "goodToRecommend": "Yes"}, None)

    def test_reason_of_other_form_rejected(self):
        with pytest.raises(FeedbackValidationError, match="goodToRecommendReason is not a criterion"):
            validate_internal({**DIALOG, "goodToRecommendReason": "gut"}, None)

    def test_reasons_are_optional_and_kept(self):
        rating = validate_internal(TURN, "s-1#a1")
        assert rating.reasons == {"technical_correctivity": "Abschläge fehlen"}
        assert validate_internal(SINGLE_TURN, "s-1#a1").reasons == {}

    def test_dialog_optional_criterion(self):
        rating = validate_internal({**DIALOG, "handlingCorrections": "No"}, None)
        assert rating.ratings["handling_corrections"] == "No"
        assert "handling_corrections" not in validate_internal(DIALOG, None).ratings

    def test_dialog_requires_used_scenario(self):
        with pytest.raises(FeedbackValidationError, match="usedScenario is required"):
            validate_internal({**DIALOG, "usedScenario": None}, None)

    def test_used_scenario_kept_for_dialog_and_turn(self):
        assert validate_internal(DIALOG, None).used_scenario == 3
        assert validate_internal(TURN, "s-1#a1").used_scenario == 3
        assert validate_internal({**SINGLE_TURN, "usedScenario": 2}, "s-1#a1").used_scenario is None

    def test_free_test_mode_zero_is_kept(self):
        assert validate_internal({**DIALOG, "usedScenario": 0}, None).used_scenario == 0
        assert validate_internal({**TURN, "usedScenario": 0}, "s-1#a1").used_scenario == 0

    @pytest.mark.parametrize("body", [SINGLE_TURN, TURN])
    def test_answer_ratings_require_message_id(self, body):
        with pytest.raises(FeedbackValidationError, match="messageId is required"):
            validate_internal(body, None)

    @pytest.mark.parametrize("body", [DIALOG, FINAL])
    def test_dialog_and_final_need_no_message_id(self, body):
        validate_internal(body, None)

    def test_german_value_rejected(self):
        with pytest.raises(FeedbackValidationError, match="goodToRecommend"):
            validate_internal({**FINAL, "goodToRecommend": "Ja"}, None)

    def test_unknown_field_rejected(self):
        with pytest.raises(FeedbackValidationError, match="technicalAccuracy"):
            validate_internal({**TURN, "technicalAccuracy": None}, "s-1#a1")

    def test_all_errors_are_listed(self):
        with pytest.raises(FeedbackValidationError) as exc:
            validate_internal({**SINGLE_TURN, "tonality": None, "precision": None}, None)
        assert len(exc.value.errors) == 3


class TestBuildStoredMap:
    def test_dialog_map(self):
        stored = build_stored_map(validate_internal({**DIALOG, "comment": "Test"}, None), "user-1")
        assert stored == {
            "producer": "internal_multi_turn",
            "scope": "dialog",
            "schema_version": "v2_en_4plus1",
            "ratings": {"dialogue_skills": "Probably not", "goal_achievement": "Yes"},
            "comment": "Test",
            "used_scenario": 3,
            "user_id": "user-1",
        }

    def test_free_test_mode_zero_stored(self):
        stored = build_stored_map(validate_internal({**DIALOG, "usedScenario": 0}, None), None)
        assert stored["used_scenario"] == 0

    def test_empty_values_left_out(self):
        stored = build_stored_map(validate_internal(FINAL, None), None)
        assert stored == {
            "producer": "internal_final_feedback",
            "scope": "test",
            "schema_version": "v2_en_4plus1",
            "ratings": {"good_to_recommend": "Likely yes"},
        }

    def test_reasons_stored(self):
        stored = build_stored_map(validate_internal(TURN, "s-1#a1"), None)
        assert stored["reasons"] == {"technical_correctivity": "Abschläge fehlen"}
