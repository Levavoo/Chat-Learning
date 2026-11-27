"""Unit tests for ChatService."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.repositories.conversation import ConversationStore, HistoryReadError
from backend_orchestrator.services.chat_service import (
    MAX_MESSAGES_PER_CONVERSATION,
    ChatService,
    ConversationLimitReachedError,
    _find_matching_history_sources,
)
from backend_orchestrator.services.feedback_rating import validate_internal
from backend_orchestrator.utils.history_converter import DEFAULT_MAX_HISTORY_PAIRS
from backend_orchestrator.validators.guardrail_validator import GuardrailResult


class TestChatService:
    @pytest.fixture
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent") as mock:
            agent = MagicMock()
            mock.return_value = agent
            yield mock

    def test_init_creates_agent(self, mock_create_agent):
        service = ChatService()
        assert hasattr(service, "_agent")
        mock_create_agent.assert_called_once()

    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_validation_fail(self, mock_validate, mock_create_agent):
        mock_validate.return_value = (False, "Too short")
        service = ChatService()

        with pytest.raises(ValueError, match="Too short"):
            service.process_message("hi", "session", message_id="session#uuid")

        mock_validate.assert_called_with("hi")

    @pytest.mark.usefixtures("no_dynamodb_history")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_success(self, mock_validate, mock_run_agent, mock_create_agent):
        mock_validate.return_value = (True, "")

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Agent response text with citation [1]"
        mock_agent_output.sources = [{"sourceId": "doc1", "sourceName": "Document 1", "sourceIndex": 1}]
        mock_agent_output.all_sources = [
            {"sourceId": "doc1", "sourceName": "Document 1", "sourceIndex": 1},
            {"sourceId": "doc2", "sourceName": "Document 2", "sourceIndex": 2},
        ]
        mock_run_agent.return_value = mock_agent_output

        service = ChatService()
        result = service.process_message("Hello", "session-123", message_id="session-123#uuid")

        mock_run_agent.assert_called_once()
        call_args = mock_run_agent.call_args
        assert call_args[0][1] == "Hello"

        assert result["response_text"] == "Agent response text with citation [1]"
        assert result["used_chunks"] == [{"sourceId": "doc1", "sourceName": "Document 1", "sourceIndex": 1}]

    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_stores_conversation_with_message_id(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_create_agent
    ):
        mock_validate.return_value = (True, "")

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Test response"
        mock_agent_output.sources = [{"sourceId": "doc1", "sourceName": "Document 1"}]
        mock_agent_output.all_sources = [
            {"sourceId": "doc1", "sourceName": "Document 1"},
            {"sourceId": "doc2", "sourceName": "Document 2"},
        ]
        mock_run_agent.return_value = mock_agent_output

        mock_store_instance = MagicMock()
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        result = service.process_message(
            message="Hello test",
            session_id="test-session-123",
            request_time_epoch=1640995200000,
            message_id="test-session-123#msg-456",
        )

        mock_store_instance.store_conversation.assert_called_once()
        call_kwargs = mock_store_instance.store_conversation.call_args[1]
        assert call_kwargs["session_id"] == "test-session-123"
        assert call_kwargs["message"] == "Hello test"
        assert call_kwargs["response_text"] == "Test response"
        assert call_kwargs["message_id"] == "test-session-123#msg-456"
        assert call_kwargs["domain"] is None
        assert result["message_id"] == "test-session-123#msg-456"

    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_skips_storage_without_message_id(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_create_agent
    ):
        mock_validate.return_value = (True, "")

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Test response"
        mock_agent_output.sources = []
        mock_agent_output.all_sources = []
        mock_run_agent.return_value = mock_agent_output

        mock_store_instance = MagicMock()
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        result = service.process_message("Hello test", "test-session")

        mock_store_instance.store_conversation.assert_not_called()
        assert result["message_id"] is None

    @pytest.mark.asyncio
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent_async")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    async def test_process_message_async_stores_conversation(
        self, mock_validate, mock_run_agent_async, mock_conversation_store, mock_create_agent
    ):
        mock_validate.return_value = (True, "")

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Async test response"
        mock_agent_output.sources = [{"sourceId": "async_doc", "sourceName": "Async Document"}]
        mock_agent_output.all_sources = [
            {"sourceId": "async_doc", "sourceName": "Async Document"},
            {"sourceId": "async_doc2", "sourceName": "Async Document 2"},
        ]
        mock_run_agent_async.return_value = mock_agent_output

        mock_store_instance = MagicMock()
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        result = await service.process_message_async(
            message="Hello async test",
            session_id="async-session-789",
            request_time_epoch=1640995300000,
            message_id="async-session-789#async-msg-123",
        )

        mock_store_instance.store_conversation.assert_called_once()
        call_kwargs = mock_store_instance.store_conversation.call_args[1]
        assert call_kwargs["session_id"] == "async-session-789"
        assert call_kwargs["message"] == "Hello async test"
        assert call_kwargs["response_text"] == "Async test response"
        assert call_kwargs["message_id"] == "async-session-789#async-msg-123"
        assert call_kwargs["domain"] is None

        assert result["message_id"] == "async-session-789#async-msg-123"

    @pytest.mark.asyncio
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    async def test_process_message_async_requires_message_id(self, mock_validate, mock_create_agent):
        mock_validate.return_value = (True, "")
        service = ChatService()

        with pytest.raises(ValueError, match="message_id is required"):
            await service.process_message_async("Hello", "session")

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_store_feedback_calls_conversation_store(
        self, mock_conversation_store, mock_post_scores, mock_create_agent
    ):
        mock_store_instance = MagicMock()
        mock_store_instance.update_feedback.return_value = True
        mock_store_instance.get_message.return_value = None
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        feedback_data = {"rating": 5, "comment": "Great response!"}

        result = service.store_feedback(
            session_id="feedback-session-123", message_id="feedback-session-123#msg-789", feedback=feedback_data
        )

        mock_store_instance.update_feedback.assert_called_once_with(
            "feedback-session-123", "feedback-session-123#msg-789", feedback_data
        )
        mock_post_scores.assert_not_called()
        assert result is True

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_store_feedback_returns_false_on_failure(
        self, mock_conversation_store, mock_post_scores, mock_create_agent
    ):
        mock_store_instance = MagicMock()
        mock_store_instance.update_feedback.return_value = False
        mock_store_instance.get_message.return_value = None
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        result = service.store_feedback(
            session_id="failed-session", message_id="failed-session#msg-999", feedback={"rating": 1}
        )
        mock_post_scores.assert_not_called()
        assert result is False


class _FeedbackLoopFixture:
    """Shared setup for the schema-driven feedback-loop tests (#881)."""

    SESSION = "sess-1"
    MESSAGE = "sess-1#msg-1"
    TRACE_ID = "trace-xyz"

    @staticmethod
    def _make_store(trace_id: str | None = TRACE_ID) -> MagicMock:
        store = MagicMock()
        store.update_feedback.return_value = True
        item = MagicMock()
        item.langfuse_trace_id = trace_id
        store.get_message.return_value = item
        return store


class TestStoreFeedbackSchemaLoop:
    """store_feedback writes every filled FEEDBACK_SCORE_SCHEMA field (#881)."""

    @pytest.fixture
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent") as mock:
            mock.return_value = MagicMock()
            yield mock

    def _run(self, mock_conversation_store, feedback: dict) -> None:
        store = _FeedbackLoopFixture._make_store()
        mock_conversation_store.return_value = store
        ChatService().store_feedback(
            session_id=_FeedbackLoopFixture.SESSION,
            message_id=_FeedbackLoopFixture.MESSAGE,
            feedback=feedback,
        )

    @staticmethod
    def _events(mock_post) -> list[dict]:
        """store_feedback issues exactly one batched POST; this returns its events list."""
        mock_post.assert_called_once()
        return list(mock_post.call_args.args[0])

    @pytest.mark.parametrize("value", ["GOOD", "NEUTRAL", "BAD"])
    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_posts_helpfulness_as_categorical(self, mock_store, mock_post, mock_create_agent, value):
        self._run(mock_store, {"helpfulness": value})
        assert self._events(mock_post) == [
            {
                "trace_id": "trace-xyz",
                "name": "user.helpfulness",
                "value": value,
                "data_type": "CATEGORICAL",
                "comment": None,
                "id": "sess-1#msg-1#helpfulness",
            }
        ]

    @pytest.mark.parametrize("value", ["Yes", "Likely yes", "Probably not", "No", "Cannot evaluate"])
    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_handling_corrections_populates_langfuse_score(self, mock_store, mock_post, mock_create_agent, value):
        """handling_corrections is forwarded as user.handling_corrections CATEGORICAL score (#909)."""
        self._run(mock_store, {"handling_corrections": value})
        assert self._events(mock_post) == [
            {
                "trace_id": "trace-xyz",
                "name": "user.handling_corrections",
                "value": value,
                "data_type": "CATEGORICAL",
                "comment": None,
                "id": "sess-1#msg-1#handling_corrections",
            }
        ]

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_accepts_camelcase_helpfulness(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"helpfulness": "GOOD"})
        [event] = self._events(mock_post)
        assert event["name"] == "user.helpfulness"
        assert event["value"] == "GOOD"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_attaches_comment_to_helpfulness(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"helpfulness": "GOOD", "comment": "nice"})
        [event] = self._events(mock_post)
        assert event["name"] == "user.helpfulness"
        assert event["comment"] == "nice"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_legacy_thumbs_up_is_ignored(self, mock_store, mock_post, mock_create_agent):
        """Historic DynamoDB rows still carry thumbsUp pre-migration; must emit no score."""
        self._run(mock_store, {"thumbs_up": "up"})
        mock_post.assert_called_once_with([])

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_attaches_comment_to_first_filled_score_when_no_thumbs(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"technical_correctivity": "trifft_zu", "comment": "nice"})
        [event] = self._events(mock_post)
        assert event["name"] == "user.technical_correctivity"
        assert event["comment"] == "nice"
        assert event["id"] == "sess-1#msg-1#technical_correctivity"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_batches_multiple_fields_into_one_call(self, mock_store, mock_post, mock_create_agent):
        """Three filled fields → one batched POST with three events (user-latency contract)."""
        self._run(
            mock_store,
            {
                "helpfulness": "GOOD",
                "technical_correctivity": "trifft_zu",
                "tonality": "gut",
            },
        )
        events = self._events(mock_post)
        assert len(events) == 3
        by_name = {e["name"]: e for e in events}
        assert set(by_name) == {"user.helpfulness", "user.technical_correctivity", "user.tonality"}
        assert by_name["user.technical_correctivity"]["value"] == "trifft_zu"
        assert by_name["user.technical_correctivity"]["data_type"] == "CATEGORICAL"
        assert by_name["user.technical_correctivity"]["comment"] is None
        assert by_name["user.technical_correctivity"]["id"] == "sess-1#msg-1#technical_correctivity"
        assert by_name["user.tonality"]["id"] == "sess-1#msg-1#tonality"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_coerces_used_scenario_to_str(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"used_scenario": 3})
        [event] = self._events(mock_post)
        assert event["value"] == "3"
        assert event["data_type"] == "CATEGORICAL"
        assert event["id"] == "sess-1#msg-1#used_scenario"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_free_test_mode_zero_sent_as_str(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"used_scenario": 0})
        [event] = self._events(mock_post)
        assert event["value"] == "0"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_handles_camelcase_likert_field(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"technicalCorrectivity": "trifft_zu"})
        [event] = self._events(mock_post)
        assert event["name"] == "user.technical_correctivity"
        assert event["value"] == "trifft_zu"

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_snake_none_does_not_fall_through_to_camel(self, mock_store, mock_post, mock_create_agent):
        """Snake-cased key present-but-None short-circuits; camel-cased sibling is not read."""
        self._run(mock_store, {"helpfulness": None, "helpfulness_alias": "GOOD"})
        mock_post.assert_called_once_with([])

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_skips_langfuse_when_trace_id_missing(self, mock_store, mock_post, mock_create_agent):
        store = _FeedbackLoopFixture._make_store(trace_id=None)
        mock_store.return_value = store
        result = ChatService().store_feedback(
            session_id="sess-1",
            message_id="sess-1#msg-1",
            feedback={"helpfulness": "GOOD", "tonality": "gut"},
        )
        store.update_feedback.assert_called_once()
        mock_post.assert_not_called()
        assert result is True

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_skips_deferred_and_injected_fields(self, mock_store, mock_post, mock_create_agent):
        self._run(
            mock_store,
            {
                "is_multiturn": True,
                "is_singleturn": True,
                "is_free_user_test": False,
                "is_final_feedback": True,
                "comment": "orphan",
                "user_id": "u-1",
            },
        )
        mock_post.assert_called_once_with([])

    @patch("backend_orchestrator.services.chat_service.post_langfuse_scores")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    def test_skips_empty_strings(self, mock_store, mock_post, mock_create_agent):
        self._run(mock_store, {"helpfulness": "", "coverage_level": "", "tonality": "sideways"})
        [event] = self._events(mock_post)
        assert event["name"] == "user.tonality"
        assert event["value"] == "sideways"
        assert event["data_type"] == "CATEGORICAL"


class TestChatServiceHistory:
    @pytest.fixture
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent") as mock:
            mock.return_value = MagicMock()
            yield mock

    @patch("backend_orchestrator.services.chat_service.items_to_messages")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_fetches_history(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_items_to_messages, mock_create_agent
    ):
        mock_validate.return_value = (True, "")

        mock_store_instance = MagicMock()
        mock_history_items = [MagicMock(), MagicMock()]
        mock_store_instance.get_history.return_value = mock_history_items
        mock_conversation_store.return_value = mock_store_instance

        mock_messages = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_items_to_messages.return_value = mock_messages

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Response with history"
        mock_agent_output.sources = []
        mock_agent_output.all_sources = []
        mock_run_agent.return_value = mock_agent_output

        service = ChatService()
        service.process_message("Follow-up question", "session-123", message_id="session-123#uuid")

        mock_store_instance.get_history.assert_called_once_with("session-123")
        mock_items_to_messages.assert_called_once_with(mock_history_items, include_tool_calls=True)

        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["message_history"] == mock_messages

    @patch("backend_orchestrator.services.chat_service.items_to_messages")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_no_history(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_items_to_messages, mock_create_agent
    ):
        mock_validate.return_value = (True, "")

        mock_store_instance = MagicMock()
        mock_store_instance.get_history.return_value = []
        mock_conversation_store.return_value = mock_store_instance

        mock_agent_output = MagicMock()
        mock_agent_output.result = "First response"
        mock_agent_output.sources = []
        mock_agent_output.all_sources = []
        mock_run_agent.return_value = mock_agent_output

        service = ChatService()
        service.process_message("First question", "new-session", message_id="new-session#uuid")

        mock_items_to_messages.assert_not_called()
        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["message_history"] is None
        assert call_kwargs["seed_sources"] is None

    @patch("backend_orchestrator.services.chat_service.extract_seed_sources")
    @patch("backend_orchestrator.services.chat_service.items_to_messages")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_passes_seed_sources(
        self,
        mock_validate,
        mock_run_agent,
        mock_conversation_store,
        mock_items_to_messages,
        mock_extract_seeds,
        mock_create_agent,
    ):
        mock_validate.return_value = (True, "")

        mock_store_instance = MagicMock()
        mock_store_instance.get_history.return_value = [MagicMock()]
        mock_conversation_store.return_value = mock_store_instance

        mock_items_to_messages.return_value = [MagicMock()]
        seeds = [{"sourceIndex": 1, "title": "Altersrente"}]
        mock_extract_seeds.return_value = seeds

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Follow-up response"
        mock_agent_output.sources = []
        mock_agent_output.all_sources = []
        mock_run_agent.return_value = mock_agent_output

        service = ChatService()
        service.process_message("und wenn ich Lehrer bin?", "session-123", message_id="session-123#uuid")

        mock_extract_seeds.assert_called_once_with(mock_store_instance.get_history.return_value)
        assert mock_run_agent.call_args[1]["seed_sources"] == seeds

    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_guardrail_receives_history(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_guardrail, mock_create_agent
    ):
        mock_validate.return_value = (True, "")
        mock_guardrail.return_value = GuardrailResult(allowed=True)

        mock_store_instance = MagicMock()
        history_items = [MagicMock()]
        mock_store_instance.get_history.return_value = history_items
        mock_conversation_store.return_value = mock_store_instance

        mock_agent_output = MagicMock()
        mock_agent_output.result = "Response"
        mock_agent_output.sources = []
        mock_agent_output.all_sources = []
        mock_run_agent.return_value = mock_agent_output

        service = ChatService()
        service.process_message("warum?", "session-123", message_id="session-123#uuid")

        mock_guardrail.assert_called_once_with("warum?", history_items)

    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_stores_cited_sources_not_all(
        self, mock_validate, mock_run_agent, mock_conversation_store, mock_create_agent
    ):
        """Only cited sources (used_chunks) are persisted, not every retrieved chunk."""
        mock_validate.return_value = (True, "")

        cited = [{"sourceId": "doc1", "sourceIndex": 1}]
        mock_agent_output = MagicMock()
        mock_agent_output.result = "Antwort [1]"
        mock_agent_output.sources = cited
        mock_agent_output.all_sources = cited + [{"sourceId": f"doc{i}", "sourceIndex": i} for i in range(2, 30)]
        mock_run_agent.return_value = mock_agent_output

        mock_store_instance = MagicMock()
        mock_store_instance.get_history.return_value = []
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        service.process_message("Frage", "session-123", message_id="session-123#uuid")

        call_kwargs = mock_store_instance.store_conversation.call_args[1]
        assert call_kwargs["sources"] == cited


class TestChatServiceAsyncParity:
    """process_message_async must mirror the sync path: history, context-aware guardrail, seeding."""

    @pytest.fixture
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent") as mock:
            mock.return_value = MagicMock()
            yield mock

    @pytest.mark.asyncio
    @patch("backend_orchestrator.services.chat_service.extract_seed_sources")
    @patch("backend_orchestrator.services.chat_service.items_to_messages")
    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.run_agent_async", new_callable=AsyncMock)
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    async def test_async_path_uses_history_guardrail_context_and_seeds(
        self,
        mock_validate,
        mock_conversation_store,
        mock_run_async,
        mock_guardrail,
        mock_items_to_messages,
        mock_extract_seeds,
        mock_create_agent,
    ):
        mock_validate.return_value = (True, "")
        mock_guardrail.return_value = GuardrailResult(allowed=True)

        history_items = [MagicMock()]
        mock_store_instance = MagicMock()
        mock_store_instance.get_history.return_value = history_items
        mock_conversation_store.return_value = mock_store_instance

        mock_messages = [MagicMock()]
        mock_items_to_messages.return_value = mock_messages
        seeds = [{"sourceIndex": 1, "title": "Altersrente"}]
        mock_extract_seeds.return_value = seeds

        cited = [{"sourceId": "doc1", "sourceIndex": 1}]
        agent_output = MagicMock()
        agent_output.result = "Antwort [1]"
        agent_output.sources = cited
        agent_output.all_sources = cited
        mock_run_async.return_value = agent_output

        service = ChatService()
        result = await service.process_message_async(
            message="warum?", session_id="sess-async", request_time_epoch=1, message_id="sess-async#m1"
        )

        mock_store_instance.get_history.assert_called_once_with("sess-async")
        mock_guardrail.assert_called_once_with("warum?", history_items)
        mock_items_to_messages.assert_called_once_with(history_items, include_tool_calls=True)
        mock_extract_seeds.assert_called_once_with(history_items)

        call_kwargs = mock_run_async.call_args[1]
        assert call_kwargs["message_history"] == mock_messages
        assert call_kwargs["seed_sources"] == seeds

        store_kwargs = mock_store_instance.store_conversation.call_args[1]
        assert store_kwargs["sources"] == cited
        assert result["used_chunks"] == cited

    @pytest.mark.asyncio
    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.run_agent_async", new_callable=AsyncMock)
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    async def test_async_path_blocks_and_persists_blocked_turn(
        self, mock_validate, mock_conversation_store, mock_run_async, mock_guardrail, mock_create_agent
    ):
        """A blocked message short-circuits the async path and is persisted with the audit flag."""
        mock_validate.return_value = (True, "")
        mock_guardrail.return_value = GuardrailResult(allowed=False, response="Blocked")

        mock_store_instance = MagicMock()
        mock_store_instance.get_history.return_value = []
        mock_conversation_store.return_value = mock_store_instance

        service = ChatService()
        result = await service.process_message_async(
            message="off-topic", session_id="sess-async", request_time_epoch=1, message_id="sess-async#m1"
        )

        assert result["response_text"] == "Blocked"
        mock_run_async.assert_not_called()
        assert mock_store_instance.store_conversation.call_args[1]["blocked_by_guardrail"] is True


class TestFindMatchingHistorySources:
    def test_returns_empty_when_no_history_items(self):
        result = _find_matching_history_sources([], "Some response text")
        assert result == []

    def test_returns_empty_when_no_items_have_sources(self):
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="Q1",
                response_text="Response 1 with very similar text",
                sources=[],
            ),
        ]
        result = _find_matching_history_sources(items, "Response with very similar text")
        assert result == []

    def test_returns_empty_when_similarity_below_threshold(self):
        """Below the _MIN_SIMILARITY threshold (0.3)."""
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="Q",
                response_text="xyz",
                sources=[{"sourceId": "doc1"}],
            ),
        ]
        result = _find_matching_history_sources(items, "abcdefghijklmnopqrstuvw")
        assert result == []

    def test_returns_sources_from_most_similar_match(self):
        sources_2 = [{"sourceId": "doc2"}]
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="Q1",
                response_text="This is about cats and dogs",
                sources=[{"sourceId": "doc1"}],
            ),
            ConversationItem(
                session_id="s1",
                message_id="m2",
                message="Q2",
                response_text="The weather is sunny today with clear skies",
                sources=sources_2,
            ),
        ]
        result = _find_matching_history_sources(items, "The weather is sunny today with clear blue skies")
        assert result == sources_2

    def test_ignores_items_without_sources_when_finding_match(self):
        sources_with_data = [{"sourceId": "doc1"}]
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="Q1",
                response_text="The capital of France is Paris",
                sources=[],
            ),
            ConversationItem(
                session_id="s1",
                message_id="m2",
                message="Q2",
                response_text="The capital of France is Paris and it's a beautiful city",
                sources=sources_with_data,
            ),
        ]
        result = _find_matching_history_sources(items, "The capital of France is Paris")
        assert result == sources_with_data

    def test_fallback_scenario_agent_no_sources_history_available(self):
        """Main use case: agent returns no sources but history has relevant sources."""
        history_sources = [{"sourceId": "kb-doc-123", "sourceIndex": 1}]
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="What are the office hours?",
                response_text="The office hours are Monday to Friday, 9 AM to 5 PM.",
                sources=history_sources,
            ),
        ]
        result = _find_matching_history_sources(items, "The office hours are Monday to Friday, from 9 AM to 5 PM.")
        assert result == history_sources

    def test_returns_best_match_among_multiple_similar_items(self):
        sources_3 = [{"sourceId": "doc3"}]
        items = [
            ConversationItem(
                session_id="s1",
                message_id="m1",
                message="Q1",
                response_text="Python is a programming language",
                sources=[{"sourceId": "doc1"}],
            ),
            ConversationItem(
                session_id="s1",
                message_id="m2",
                message="Q2",
                response_text="Python is a programming language used for web development",
                sources=[{"sourceId": "doc2"}],
            ),
            ConversationItem(
                session_id="s1",
                message_id="m3",
                message="Q3",
                response_text="Python is a programming language used for web development and data science",
                sources=sources_3,
            ),
        ]
        result = _find_matching_history_sources(
            items, "Python is a programming language used for web development and data science applications"
        )
        assert result == sources_3


class TestChatServiceGuardrails:
    @pytest.fixture
    def mock_service(self):
        with patch("backend_orchestrator.services.chat_service.create_agent"):
            service = ChatService()
            service.conversation_store = MagicMock()
            service.conversation_store.get_history.return_value = []
            yield service

    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_guardrail_blocked(
        self, mock_validate_length, mock_run_agent, mock_validate_guardrail, mock_service
    ):
        mock_validate_length.return_value = (True, None)
        mock_validate_guardrail.return_value = GuardrailResult(
            allowed=False, response="Your message was blocked by guardrail"
        )

        result = mock_service.process_message(
            message="Inappropriate content",
            session_id="sess-123",
            request_time_epoch=1234567890,
            message_id="msg-123",
        )

        assert result["response_text"] == "Your message was blocked by guardrail"
        assert result["used_chunks"] == []
        assert result["message_id"] == "msg-123"
        mock_run_agent.assert_not_called()
        mock_service.conversation_store.store_conversation.assert_called_once()
        call_kwargs = mock_service.conversation_store.store_conversation.call_args[1]
        assert call_kwargs["blocked_by_guardrail"] is True

    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_guardrail_passed(
        self, mock_validate_length, mock_run_agent, mock_validate_guardrail, mock_service
    ):
        mock_validate_length.return_value = (True, None)
        mock_validate_guardrail.return_value = GuardrailResult(allowed=True)

        mock_agent_result = MagicMock()
        mock_agent_result.result = "Agent response"
        mock_agent_result.sources = []
        mock_agent_result.all_sources = []
        mock_run_agent.return_value = mock_agent_result

        result = mock_service.process_message(
            message="Valid message",
            session_id="sess-123",
            request_time_epoch=1234567890,
            message_id="msg-123",
        )

        assert result["response_text"] == "Agent response"
        mock_run_agent.assert_called_once()

    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    def test_process_message_allow_with_correction(
        self, mock_validate_length, mock_run_agent, mock_validate_guardrail, mock_service
    ):
        """ALLOW_WITH_CORRECTION prepends static correction instruction."""
        mock_validate_length.return_value = (True, None)
        mock_validate_guardrail.return_value = GuardrailResult(allowed=True, correction_instruction="Falsche Annahme")

        mock_agent_result = MagicMock()
        mock_agent_result.result = "Corrected response"
        mock_agent_result.sources = []
        mock_agent_result.all_sources = []
        mock_run_agent.return_value = mock_agent_result

        result = mock_service.process_message(
            message="Man bekommt mit 55 volle Rente",
            session_id="sess-123",
            request_time_epoch=1234567890,
            message_id="msg-123",
        )

        assert result["response_text"] == "Corrected response"
        agent_message = mock_run_agent.call_args[0][1]
        assert "[HINWEIS:" in agent_message
        assert "Man bekommt mit 55 volle Rente" in agent_message


class TestChatServiceSessionMasking:
    """The full session_id must never appear in ChatService log records (#482 / RFC M4)."""

    _FULL_SESSION = "sess-full-value-12345"

    @pytest.fixture
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent") as mock:
            mock.return_value = MagicMock()
            yield mock

    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    def test_process_message_never_logs_full_session_id(
        self,
        mock_guardrail,
        mock_validate,
        mock_run_agent,
        mock_conversation_store,
        mock_create_agent,
    ):
        mock_validate.return_value = (True, "")
        mock_guardrail.return_value = GuardrailResult(allowed=True)
        agent_result = MagicMock()
        agent_result.result = "resp"
        agent_result.sources = []
        agent_result.all_sources = []
        mock_run_agent.return_value = agent_result
        mock_conversation_store.return_value = MagicMock(get_history=MagicMock(return_value=[]))

        service = ChatService()
        with patch("backend_orchestrator.services.chat_service.logger") as mock_logger:
            service.process_message("hi", self._FULL_SESSION, message_id=f"{self._FULL_SESSION}#uuid")

        for call in mock_logger.method_calls:
            assert self._FULL_SESSION not in str(call), f"full session_id leaked into: {call}"

    @pytest.mark.asyncio
    @patch("backend_orchestrator.services.chat_service.ConversationStore")
    @patch("backend_orchestrator.services.chat_service.run_agent_async")
    @patch("backend_orchestrator.services.chat_service.validate_message_length")
    @patch("backend_orchestrator.services.chat_service.validate_user_input_with_guardrail")
    async def test_process_message_async_never_logs_full_session_id(
        self,
        mock_guardrail,
        mock_validate,
        mock_run_agent_async,
        mock_conversation_store,
        mock_create_agent,
    ):
        mock_validate.return_value = (True, "")
        mock_guardrail.return_value = GuardrailResult(allowed=True)
        agent_result = MagicMock()
        agent_result.result = "resp"
        agent_result.sources = []
        agent_result.all_sources = []
        mock_run_agent_async.return_value = agent_result
        mock_conversation_store.return_value = MagicMock(get_history=MagicMock(return_value=[]))

        service = ChatService()
        with patch("backend_orchestrator.services.chat_service.logger") as mock_logger:
            await service.process_message_async("hi", self._FULL_SESSION, message_id=f"{self._FULL_SESSION}#uuid")

        for call in mock_logger.method_calls:
            assert self._FULL_SESSION not in str(call), f"full session_id leaked into: {call}"


class TestStoreRating:
    """store_rating writes tester ratings to the right row and Langfuse target."""

    @pytest.fixture(autouse=True)
    def mock_create_agent(self):
        with patch("backend_orchestrator.services.chat_service.create_agent"):
            yield

    @pytest.fixture
    def store(self):
        store = _FeedbackLoopFixture._make_store()
        store.put_rating_row.return_value = True
        with patch("backend_orchestrator.services.chat_service.ConversationStore", return_value=store):
            yield store

    @pytest.fixture
    def mock_post(self):
        with patch("backend_orchestrator.services.chat_service.post_langfuse_scores") as mock:
            yield mock

    @pytest.fixture
    def mock_metric(self):
        with patch("backend_orchestrator.services.chat_service._emit_feedback_written") as mock:
            yield mock

    @staticmethod
    def _rating(body: dict, message_id: str | None = _FeedbackLoopFixture.MESSAGE):
        return validate_internal(body, message_id)

    def test_turn_rating_goes_to_answer_row_and_trace(self, store, mock_post, mock_metric):
        rating = self._rating({
            "isMultiturn": True,
            "isPerTurnFeedback": True,
            "technicalCorrectivity": "Likely yes",
            "technicalCorrectivityReason": "Abschläge fehlen",
        })

        assert ChatService().store_rating("sess-1", _FeedbackLoopFixture.MESSAGE, rating, "user-1") is True

        store.update_feedback.assert_called_once_with(
            "sess-1",
            _FeedbackLoopFixture.MESSAGE,
            {
                "producer": "internal_multi_turn",
                "scope": "turn",
                "schema_version": "v2_en_4plus1",
                "ratings": {"technical_correctivity": "Likely yes"},
                "reasons": {"technical_correctivity": "Abschläge fehlen"},
                "user_id": "user-1",
            },
        )
        store.put_rating_row.assert_not_called()
        [event] = mock_post.call_args.args[0]
        assert event["trace_id"] == "trace-xyz"
        assert event["comment"] == "Abschläge fehlen"
        assert event["metadata"] == {
            "producer": "internal_multi_turn",
            "scope": "turn",
            "schema_version": "v2_en_4plus1",
        }
        mock_metric.assert_called_once_with(producer="internal_multi_turn", scope="turn", schema_version="v2_en_4plus1")

    @pytest.mark.parametrize(
        ("body", "sort_key"),
        [
            (
                {"isMultiturn": True, "usedScenario": 2, "dialogueSkills": "Yes", "goalAchievement": "No"},
                "RATING#DIALOG",
            ),
            ({"isFinalFeedback": True, "goodToRecommend": "Likely yes"}, "RATING#FINAL"),
        ],
    )
    def test_conversation_rating_goes_to_rating_row_and_session(self, store, mock_post, mock_metric, body, sort_key):
        rating = self._rating(body, None)

        assert ChatService().store_rating("sess-1", None, rating, None) is True

        store.update_feedback.assert_not_called()
        session_id, written_key, stored = store.put_rating_row.call_args.args
        assert (session_id, written_key) == ("sess-1", sort_key)
        assert stored["scope"] == rating.scope
        events = mock_post.call_args.args[0]
        assert all(event["session_id"] == "sess-1" and "trace_id" not in event for event in events)
        assert all(event["id"].startswith(f"sess-1#{sort_key}#") for event in events)
        assert all(
            event["metadata"] == {"producer": rating.producer, "scope": rating.scope, "schema_version": "v2_en_4plus1"}
            for event in events
        )

    def test_dialog_scores_include_used_scenario(self, store, mock_post, mock_metric):
        rating = self._rating(
            {"isMultiturn": True, "usedScenario": 2, "dialogueSkills": "Yes", "goalAchievement": "No"}, None
        )

        ChatService().store_rating("sess-1", None, rating, None)

        names = [event["name"] for event in mock_post.call_args.args[0]]
        assert names == ["user.goal_achievement", "user.dialogue_skills", "user.used_scenario"]

    def test_form_comment_goes_on_first_score_after_its_reason(self, store, mock_post, mock_metric):
        rating = self._rating(
            {
                "isFinalFeedback": True,
                "goodToRecommend": "Yes",
                "goodToRecommendReason": "hilfreich",
                "comment": "Gesamteindruck gut",
            },
            None,
        )

        ChatService().store_rating("sess-1", None, rating, None)

        [event] = mock_post.call_args.args[0]
        assert event["comment"] == "hilfreich\n\nGesamteindruck gut"

    def test_failed_write_returns_false_and_sends_nothing(self, store, mock_post, mock_metric):
        store.put_rating_row.return_value = False
        rating = self._rating({"isFinalFeedback": True, "goodToRecommend": "Yes"}, None)

        assert ChatService().store_rating("sess-1", None, rating, None) is False
        mock_post.assert_not_called()
        mock_metric.assert_not_called()


class TestConversationLimit:
    """#992: at most MAX_MESSAGES_PER_CONVERSATION messages, fail-closed on read errors."""

    @pytest.fixture
    def service_parts(self):
        """Service with mocked store, guardrail and agent; yields (service, store, guardrail, run_agent)."""
        agent_output = MagicMock(result="Antwort", sources=[], all_sources=[])
        with (
            patch("backend_orchestrator.services.chat_service.create_agent", return_value=MagicMock()),
            patch("backend_orchestrator.services.chat_service.ConversationStore") as store_cls,
            patch("backend_orchestrator.services.chat_service.validate_message_length", return_value=(True, "")),
            patch(
                "backend_orchestrator.services.chat_service.validate_user_input_with_guardrail",
                return_value=GuardrailResult(allowed=True),
            ) as guardrail,
            patch("backend_orchestrator.services.chat_service.run_agent", return_value=agent_output) as run_agent,
            patch(
                "backend_orchestrator.services.chat_service.run_agent_async",
                new_callable=AsyncMock,
                return_value=agent_output,
            ) as run_agent_async,
        ):
            store = MagicMock()
            store_cls.return_value = store
            yield ChatService(), store, guardrail, run_agent, run_agent_async

    @staticmethod
    def _history(count: int) -> list[ConversationItem]:
        return [
            ConversationItem(
                session_id="s1",
                message_id=f"m{i}",
                message=f"Frage {i}",
                response_text=f"Antwort {i}",
                sources=[],
                created_at=i,
            )
            for i in range(count)
        ]

    def test_limit_is_20_and_equals_history_window(self):
        """With limit == history window the model always sees the whole conversation."""
        assert MAX_MESSAGES_PER_CONVERSATION == 20
        assert MAX_MESSAGES_PER_CONVERSATION == DEFAULT_MAX_HISTORY_PAIRS

    def test_history_read_limit_covers_conversation_limit(self):
        """get_history trims to `limit`; below the cap the count could never reach it."""
        default_limit = inspect.signature(ConversationStore.get_history).parameters["limit"].default
        assert default_limit >= MAX_MESSAGES_PER_CONVERSATION

    @pytest.mark.parametrize("stored", [18, 19])
    def test_19th_and_20th_message_reach_the_model(self, service_parts, stored):
        service, store, guardrail, run_agent, _ = service_parts
        store.get_history.return_value = self._history(stored)

        result = service.process_message("Frage", "s1", message_id="s1#new")

        assert result["response_text"] == "Antwort"
        guardrail.assert_called_once()
        run_agent.assert_called_once()

    @pytest.mark.parametrize("stored", [20, 21])
    def test_21st_message_is_rejected_without_model_call(self, service_parts, stored):
        service, store, guardrail, run_agent, _ = service_parts
        store.get_history.return_value = self._history(stored)

        with pytest.raises(ConversationLimitReachedError):
            service.process_message("Frage", "s1", message_id="s1#new")

        # The guardrail is an LLM call too, so it must not run either.
        guardrail.assert_not_called()
        run_agent.assert_not_called()
        store.store_conversation.assert_not_called()

    def test_reused_message_ids_cannot_bypass_the_limit(self, service_parts):
        """19-id ring: put_item overwrites the same sort key, so the row count stays at 19.

        Every reused id must get the stored answer back, never a new guardrail or model call.
        """
        service, store, guardrail, run_agent, _ = service_parts
        history = self._history(19)
        store.get_history.return_value = history

        for _ in range(3):
            for item in history:
                result = service.process_message("Neue Jailbreak-Frage", "s1", message_id=item.message_id)
                assert result["response_text"] == item.response_text

        guardrail.assert_not_called()
        run_agent.assert_not_called()
        store.store_conversation.assert_not_called()

    def test_retry_of_last_message_is_replayed_not_rejected(self, service_parts):
        """A client retry of the 20th message (same id) gets its answer, not 409."""
        service, store, guardrail, run_agent, _ = service_parts
        history = self._history(20)
        store.get_history.return_value = history

        result = service.process_message("Frage 19", "s1", message_id="m19")

        assert result == {"response_text": "Antwort 19", "used_chunks": [], "message_id": "m19"}
        guardrail.assert_not_called()
        run_agent.assert_not_called()

    def test_history_read_error_rejects_without_model_call(self, service_parts):
        service, store, guardrail, run_agent, _ = service_parts
        store.get_history.side_effect = HistoryReadError("throttled")

        with pytest.raises(HistoryReadError):
            service.process_message("Frage", "s1", message_id="s1#new")

        guardrail.assert_not_called()
        run_agent.assert_not_called()
        store.store_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_path_enforces_the_same_limit(self, service_parts):
        service, store, guardrail, _, run_agent_async = service_parts
        store.get_history.return_value = self._history(20)

        with pytest.raises(ConversationLimitReachedError):
            await service.process_message_async("Frage", "s1", message_id="s1#new")

        guardrail.assert_not_called()
        run_agent_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_path_replays_reused_message_id(self, service_parts):
        service, store, guardrail, _, run_agent_async = service_parts
        store.get_history.return_value = self._history(5)

        result = await service.process_message_async("Frage", "s1", message_id="m2")

        assert result["response_text"] == "Antwort 2"
        guardrail.assert_not_called()
        run_agent_async.assert_not_called()
