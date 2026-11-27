"""Tests for API models."""

import pytest
from pydantic import ValidationError

from backend_orchestrator.models import (
    ChatInput,
    ChatInputMessage,
    ChatOutput,
    ChatOutputMessage,
    MessageChunk,
    MessageContent,
    MessageFeedback,
)


class TestMessageContent:
    def test_valid_message_content(self):
        content = MessageContent(content_type="text", body="Hello")
        assert content.content_type == "text"
        assert content.body == "Hello"

    def test_serialization_uses_alias(self):
        content = MessageContent(content_type="text", body="Hello")
        data = content.model_dump(by_alias=True)
        assert "contentType" in data
        assert "content_type" not in data

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            MessageContent(content_type="text")  # type: ignore[call-arg]  # ty: ignore[missing-argument]


class TestMessageFeedback:
    def test_valid_singleturn_feedback(self):
        feedback = MessageFeedback(
            is_multiturn=False,
            is_singleturn=True,
            is_free_user_test=False,
            is_final_feedback=False,
            is_per_turn_feedback=False,
            technical_correctivity="Yes",
            coverage_level="Probably not",
            precision="Yes",
            comprehensibility="Yes",
            tonality="Yes",
            comparability_to_google_ai="Worse",
            source_matching="Yes",
            source_quality="Likely yes",
            comment="Good answer",
        )
        assert feedback.is_singleturn is True
        assert feedback.technical_correctivity == "Yes"
        assert feedback.comparability_to_google_ai == "Worse"

    def test_valid_multiturn_feedback(self):
        feedback = MessageFeedback(
            is_multiturn=True,
            is_singleturn=False,
            is_free_user_test=False,
            is_final_feedback=False,
            is_per_turn_feedback=False,
            used_scenario=3,
            goal_achievement="Yes",
            dialogue_skills="Probably not",
            further_development="Yes",
        )
        assert feedback.is_multiturn is True
        assert feedback.used_scenario == 3

    def test_valid_free_user_test_feedback(self):
        feedback = MessageFeedback(
            is_multiturn=False,
            is_singleturn=False,
            is_free_user_test=True,
            is_final_feedback=False,
            is_per_turn_feedback=False,
            utility_value="Yes",
        )
        assert feedback.is_free_user_test is True
        assert feedback.utility_value == "Yes"

    def test_valid_final_feedback(self):
        feedback = MessageFeedback(
            is_multiturn=False,
            is_singleturn=False,
            is_free_user_test=False,
            is_final_feedback=True,
            is_per_turn_feedback=False,
            good_to_recommend="Yes",
            technical_correctivity="No",
            comment="Great tool",
        )
        assert feedback.is_final_feedback is True
        assert feedback.good_to_recommend == "Yes"

    def test_optional_fields_default_to_none(self):
        feedback = MessageFeedback(
            is_multiturn=False,
            is_singleturn=False,
            is_free_user_test=False,
            is_final_feedback=False,
            is_per_turn_feedback=False,
        )
        assert feedback.technical_correctivity is None
        assert feedback.coverage_level is None
        assert feedback.comprehensibility is None
        assert feedback.precision is None
        assert feedback.tonality is None
        assert feedback.utility_value is None
        assert feedback.comparability_to_google_ai is None
        assert feedback.source_matching is None
        assert feedback.source_quality is None
        assert feedback.used_scenario is None
        assert feedback.goal_achievement is None
        assert feedback.dialogue_skills is None
        assert feedback.further_development is None
        assert feedback.good_to_recommend is None
        assert feedback.technical_correctivity is None
        assert feedback.comment is None
        assert feedback.helpfulness is None

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MessageFeedback(
                is_multiturn=False,
                is_singleturn=False,
                is_free_user_test=False,
                is_final_feedback=False,
                is_per_turn_feedback=False,
                unknown_field="bad",  # type: ignore[call-arg] # ty: ignore
            )

    _LIKERT_FIELDS = (
        "technical_correctivity",
        "coverage_level",
        "comprehensibility",
        "precision",
        "tonality",
        "source_matching",
        "source_quality",
        "goal_achievement",
        "dialogue_skills",
        "handling_corrections",
        "good_to_recommend",
    )

    @staticmethod
    def _feedback(**overrides) -> MessageFeedback:
        return MessageFeedback(
            is_multiturn=False,
            is_singleturn=False,
            is_free_user_test=False,
            is_final_feedback=False,
            is_per_turn_feedback=False,
            **overrides,
        )

    @pytest.mark.parametrize(
        ("field", "legacy_value"),
        [
            ("technical_correctivity", "Teilweise"),
            ("coverage_level", "Ja"),
            ("source_quality", "Nein"),
            ("comparability_to_google_ai", "Besser"),
            ("comparability_to_google_ai", "Gleich"),
            ("comparability_to_google_ai", "Schlechter"),
        ],
    )
    def test_literal_rejects_legacy_german_values(self, field, legacy_value):
        """Pre-!1311 German strings must not pass validation (#909)."""
        with pytest.raises(ValidationError):
            self._feedback(**{field: legacy_value})

    def test_literal_rejects_arbitrary_strings(self):
        with pytest.raises(ValidationError):
            self._feedback(precision="whatever")
        with pytest.raises(ValidationError):
            self._feedback(comparability_to_google_ai="whatever")

    @pytest.mark.parametrize("value", ["GOOD", "NEUTRAL", "BAD"])
    def test_helpfulness_accepts_frontend_enum(self, value):
        """Helpfulness carries the UserFeedback enum values the frontend posts (#941)."""
        feedback = self._feedback(helpfulness=value)
        assert feedback.helpfulness == value

    @pytest.mark.parametrize("value", ["Yes", "good", "gut", ""])
    def test_helpfulness_rejects_non_enum_values(self, value):
        """Helpfulness is NOT a Likert field — reject Likert values and anything else (#941)."""
        with pytest.raises(ValidationError):
            self._feedback(helpfulness=value)

    @pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 5, 6])
    def test_used_scenario_accepts_full_option_range(self, value):
        """UsedScenario accepts 0 (free test mode) and the scenarios 1..6."""
        feedback = self._feedback(used_scenario=value)
        assert feedback.used_scenario == value

    @pytest.mark.parametrize("value", [7, -1, 999])
    def test_used_scenario_rejects_out_of_range_ints(self, value):
        """UsedScenario rejects ints outside 0..6."""
        with pytest.raises(ValidationError):
            self._feedback(used_scenario=value)

    @pytest.mark.parametrize("field", _LIKERT_FIELDS)
    def test_literal_accepts_none_for_unanswered_fields(self, field):
        feedback = self._feedback(**{field: None})
        assert getattr(feedback, field) is None

    def test_handling_corrections_accepts_valid_rating(self):
        feedback = self._feedback(handling_corrections="Likely yes")
        assert feedback.handling_corrections == "Likely yes"

    def test_missing_flags_default_to_false(self):
        """Internal forms send only their own flag."""
        feedback = MessageFeedback.model_validate({"isSingleturn": True, "technicalCorrectivity": "Yes"})
        assert feedback.is_singleturn is True
        assert feedback.is_multiturn is False
        assert feedback.is_free_user_test is False
        assert feedback.is_final_feedback is False
        assert feedback.is_per_turn_feedback is False

    def test_producer_and_scope_accepted(self):
        feedback = MessageFeedback.model_validate({"producer": "internal_multi_turn", "scope": "dialog"})
        assert feedback.producer == "internal_multi_turn"
        assert feedback.scope == "dialog"

    @pytest.mark.parametrize(
        "body",
        [{"producer": "internal_free_user_test"}, {"scope": "conversation"}],
    )
    def test_unknown_producer_or_scope_rejected(self, body):
        with pytest.raises(ValidationError):
            MessageFeedback.model_validate(body)

    def test_reason_fields_use_camel_case(self):
        feedback = MessageFeedback.model_validate({
            "technicalCorrectivity": "Probably not",
            "technicalCorrectivityReason": "Abschläge fehlen",
        })
        assert feedback.technical_correctivity_reason == "Abschläge fehlen"


class TestChatInput:
    def test_valid_chat_input(self):
        chat_input = ChatInput(
            conversation_id="conv-123",
            message=ChatInputMessage(
                content=[MessageContent(content_type="text", body="Hello")],
            ),
        )
        assert chat_input.conversation_id == "conv-123"
        assert chat_input.message.content[0].body == "Hello"


class TestChatOutput:
    def test_valid_chat_output(self):
        output = ChatOutput(
            conversation_id="conv-123",
            message=ChatOutputMessage(
                role="assistant",
                content=[MessageContent(content_type="text", body="Hi!")],
                feedback=None,
                used_chunks=None,
                parent="123456",
            ),
            create_time=1234567890,
        )
        assert output.conversation_id == "conv-123"
        assert output.create_time == 1234567890

    def test_serialization_uses_aliases(self):
        output = ChatOutput(
            conversation_id="conv-123",
            message=ChatOutputMessage(
                role="assistant",
                content=[MessageContent(content_type="text", body="Hi!")],
                feedback=None,
                used_chunks=None,
                parent="123456",
            ),
            create_time=1234567890,
        )
        data = output.model_dump(by_alias=True)
        assert "conversationId" in data
        assert "createTime" in data
        assert "conversation_id" not in data

    def test_message_chunk_document_fields_are_optional(self):
        chunk = MessageChunk(
            content="basic chunk",
            content_type="text",
            rank=1,
        )
        assert chunk.source_name is None
        assert chunk.page_number is None
        assert chunk.source_index is None
        assert chunk.retrieval_release_id is None

    def test_message_chunk_reports_retrieval_release_id(self):
        release_id = f"sha256-{'a' * 64}"
        chunk = MessageChunk.model_validate({
            "content": "release chunk",
            "contentType": "text",
            "source": "s3://bucket/docs/a.md",
            "rank": 1,
            "retrievalReleaseId": release_id,
        })

        assert chunk.retrieval_release_id == release_id
        assert chunk.model_dump(by_alias=True)["retrievalReleaseId"] == release_id

    def test_message_chunk_surfaces_section_title_and_domain_tier(self):
        chunk = MessageChunk.model_validate({
            "content": "ranked chunk",
            "contentType": "text",
            "rank": 2,
            "sectionTitle": "§ 5 Rente",
            "domainTier": "S",
        })

        assert chunk.section_title == "§ 5 Rente"
        assert chunk.domain_tier == "S"
        wire = chunk.model_dump(by_alias=True)
        assert wire["sectionTitle"] == "§ 5 Rente"
        assert wire["domainTier"] == "S"

    def test_message_chunk_section_title_and_domain_tier_default_none(self):
        chunk = MessageChunk(content="x", content_type="text", rank=1)
        assert chunk.section_title is None
        assert chunk.domain_tier is None

    def test_chat_output_message_all_sources_defaults_to_none(self):
        msg = ChatOutputMessage(
            role="assistant",
            content=[MessageContent(content_type="text", body="hi")],
            feedback=None,
            used_chunks=None,
            parent="p",
        )
        assert msg.all_sources is None


class TestCamelCaseAliasing:
    def test_message_chunk_accepts_camel_case_input(self):
        camel_case_input = {
            "content": "chunk content",
            "contentType": "text",
            "source": "kb-source",
            "rank": 1,
            "sourceName": "Test Document",
            "sourceLink": "s3://bucket/file.md",
            "sourceIndex": 1,
        }
        chunk = MessageChunk.model_validate(camel_case_input)
        assert chunk.content_type == "text"
        assert chunk.source_name == "Test Document"
        assert chunk.source_index == 1

    def test_message_chunk_round_trip(self):
        camel_case_input = {
            "content": "test",
            "contentType": "text",
            "source": "src",
            "rank": 1,
            "sourceName": "name",
            "pageNumber": 5,
            "sourceIndex": 2,
        }
        chunk = MessageChunk.model_validate(camel_case_input)
        output = chunk.model_dump(by_alias=True)

        assert output["contentType"] == "text"
        assert output["sourceName"] == "name"
        assert output["pageNumber"] == 5
        assert output["sourceIndex"] == 2

    def test_chat_input_accepts_camel_case(self):
        camel_case_input = {
            "conversationId": "conv-123",
            "message": {
                "content": [{"contentType": "text", "body": "Hello"}],
                "messageId": "msg-456",
            },
        }
        chat_input = ChatInput.model_validate(camel_case_input)
        assert chat_input.conversation_id == "conv-123"
        assert chat_input.message.message_id == "msg-456"
        assert chat_input.message.content[0].content_type == "text"

    def test_chat_output_round_trip(self):
        output = ChatOutput(
            conversation_id="conv-1",
            message=ChatOutputMessage(
                role="assistant",
                content=[MessageContent(content_type="text", body="Hi")],
                feedback=MessageFeedback(
                    is_multiturn=False,
                    is_singleturn=True,
                    is_free_user_test=False,
                    is_final_feedback=False,
                    is_per_turn_feedback=False,
                ),
                used_chunks=[
                    MessageChunk(
                        content="chunk",
                        content_type="text",
                        rank=1,
                        source_index=1,
                    )
                ],
                parent="parent-id",
                message_id="msg-1",
            ),
            create_time=123,
        )
        data = output.model_dump(by_alias=True)

        assert "conversationId" in data
        assert "createTime" in data

        assert data["message"]["messageId"] == "msg-1"
        assert data["message"]["usedChunks"][0]["sourceIndex"] == 1

        assert data["message"]["feedback"]["isSingleturn"] is True

    def test_snake_case_input_still_works(self):
        snake_case_input = {
            "content": "test",
            "content_type": "text",
            "rank": 1,
            "source_index": 55,
            "source_name": "name",
        }
        chunk = MessageChunk.model_validate(snake_case_input)
        assert chunk.content_type == "text"
        assert chunk.source_index == 55
        assert chunk.source_name == "name"

    def test_ignore_extra_fields(self):
        input_data = {
            "content": "test",
            "contentType": "text",
            "source": "src",
            "rank": 1,
            "unknownField": "should be ignored",
        }
        chunk = MessageChunk.model_validate(input_data)
        assert chunk.content == "test"
        assert not hasattr(chunk, "unknownField")


class TestFeedbackScoreSchema:
    """FEEDBACK_SCORE_SCHEMA contract (RFC-0026 Phase 1, ticket #880)."""

    _EXPECTED_FIELDS = frozenset({
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
        "used_scenario",
        "helpfulness",
    })

    # Explicitly deferred per RFC-0026 "Offene Fragen". Changing this set is a scope
    # decision — the test fails loud so it is reviewed, not drifted.
    _DEFERRED_FIELDS = frozenset({
        "comment",
        "is_multiturn",
        "is_singleturn",
        "is_free_user_test",
        "is_final_feedback",
    })

    _VALID_LANGFUSE_DATA_TYPES = frozenset({"NUMERIC", "CATEGORICAL", "BOOLEAN", "TEXT"})

    def test_schema_covers_expected_fields(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA

        assert set(FEEDBACK_SCORE_SCHEMA) == self._EXPECTED_FIELDS

    def test_score_names_are_user_prefixed(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA

        for field, (score_name, _) in FEEDBACK_SCORE_SCHEMA.items():
            assert score_name.startswith("user."), f"{field!r} score name must start with user."

    def test_data_types_are_valid_langfuse_types(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA

        for field, (_, data_type) in FEEDBACK_SCORE_SCHEMA.items():
            assert data_type in self._VALID_LANGFUSE_DATA_TYPES, f"{field!r} has unknown Langfuse dataType"

    def test_helpfulness_is_categorical(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA

        assert FEEDBACK_SCORE_SCHEMA["helpfulness"] == ("user.helpfulness", "CATEGORICAL")

    def test_deferred_fields_are_not_in_schema(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA

        for deferred in self._DEFERRED_FIELDS:
            assert deferred not in FEEDBACK_SCORE_SCHEMA, (
                f"{deferred!r} is deferred (RFC-0026 Offene Fragen) — must not be in FEEDBACK_SCORE_SCHEMA v1"
            )

    def test_every_scored_field_exists_on_message_feedback(self):
        from backend_orchestrator.models import FEEDBACK_SCORE_SCHEMA, MessageFeedback

        model_fields = set(MessageFeedback.model_fields)
        for field in FEEDBACK_SCORE_SCHEMA:
            assert field in model_fields, f"{field!r} in schema but missing on MessageFeedback"
