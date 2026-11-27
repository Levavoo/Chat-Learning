"""Unit tests for ConversationStore."""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.repositories.conversation import ConversationStore, HistoryReadError


class TestConversationStoreGetHistory:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_get_history_returns_items_sorted_by_created_at(self, mock_dynamodb):
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "session_id": "sess-1",
                    "message_id": "msg-2",
                    "message": "Second question",
                    "response_text": "Second answer",
                    "created_at": 2000,
                    "sources": [],
                },
                {
                    "session_id": "sess-1",
                    "message_id": "msg-1",
                    "message": "First question",
                    "response_text": "First answer",
                    "created_at": 1000,
                    "sources": [],
                },
            ]
        }

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert len(result) == 2
        assert result[0].created_at == 1000
        assert result[1].created_at == 2000
        assert result[0].message == "First question"
        assert result[1].message == "Second question"

    def test_get_history_empty_session(self, mock_dynamodb):
        mock_dynamodb.query.return_value = {"Items": []}

        store = ConversationStore()
        result = store.get_history("new-session")

        assert result == []

    def test_get_history_respects_limit(self, mock_dynamodb):
        items = [
            {
                "session_id": "sess-1",
                "message_id": f"msg-{i}",
                "message": f"Question {i}",
                "response_text": f"Answer {i}",
                "created_at": i * 1000,
                "sources": [],
            }
            for i in range(1, 11)  # 10 items
        ]
        mock_dynamodb.query.return_value = {"Items": items}

        store = ConversationStore()
        result = store.get_history("sess-1", limit=3)

        assert len(result) == 3
        assert result[0].created_at == 8000
        assert result[1].created_at == 9000
        assert result[2].created_at == 10000

    def test_get_history_returns_empty_when_disabled(self, mock_dynamodb):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_boto.resource.side_effect = Exception("No DynamoDB")
            store = ConversationStore()

        result = store.get_history("sess-1")
        assert result == []

    def test_get_history_raises_on_query_error(self, mock_dynamodb):
        """Fail-closed (#992): a read error must not look like an empty conversation."""
        mock_dynamodb.query.side_effect = Exception("DynamoDB error")

        store = ConversationStore()
        with pytest.raises(HistoryReadError):
            store.get_history("sess-1")

    def test_get_history_returns_conversation_items(self, mock_dynamodb):
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "session_id": "sess-1",
                    "message_id": "msg-1",
                    "message": "Test question",
                    "response_text": "Test answer",
                    "created_at": 1000,
                    "sources": [{"sourceId": "doc1"}],
                }
            ]
        }

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert len(result) == 1
        assert isinstance(result[0], ConversationItem)
        assert result[0].session_id == "sess-1"
        assert result[0].message_id == "msg-1"
        assert result[0].sources == [{"sourceId": "doc1"}]

    def test_get_history_paginates_beyond_1mb_page(self, mock_dynamodb):
        """History follows LastEvaluatedKey so a truncated page cannot drop turns."""

        def item(i):
            return {
                "session_id": "sess-1",
                "message_id": f"msg-{i}",
                "message": f"Question {i}",
                "response_text": f"Answer {i}",
                "created_at": i * 1000,
                "sources": [],
            }

        mock_dynamodb.query.side_effect = [
            {"Items": [item(2), item(1)], "LastEvaluatedKey": {"session_id": "sess-1", "message_id": "msg-1"}},
            {"Items": [item(3)]},
        ]

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert [r.created_at for r in result] == [1000, 2000, 3000]
        assert mock_dynamodb.query.call_count == 2
        second_call_kwargs = mock_dynamodb.query.call_args_list[1][1]
        assert second_call_kwargs["ExclusiveStartKey"] == {"session_id": "sess-1", "message_id": "msg-1"}

    def test_get_history_raises_on_later_page_error(self, mock_dynamodb):
        """A query error on a LATER page raises too: a partial history would undercount the limit (#992)."""

        def item(i):
            return {
                "session_id": "sess-1",
                "message_id": f"msg-{i}",
                "message": f"Question {i}",
                "response_text": f"Answer {i}",
                "created_at": i * 1000,
                "sources": [],
            }

        mock_dynamodb.query.side_effect = [
            {"Items": [item(1), item(2)], "LastEvaluatedKey": {"session_id": "sess-1", "message_id": "msg-2"}},
            Exception("Throttled on page 2"),
        ]

        store = ConversationStore()
        with pytest.raises(HistoryReadError):
            store.get_history("sess-1")

        assert mock_dynamodb.query.call_count == 2

    def test_get_history_skips_invalid_item(self, mock_dynamodb):
        """One un-validatable row is skipped; the rest of the session history still returns."""
        good = {
            "session_id": "sess-1",
            "message_id": "msg-good",
            "message": "Frage",
            "response_text": "Antwort",
            "created_at": 1000,
            "sources": [],
        }
        # extra="forbid": an out-of-band field makes this row invalid.
        bad = {**good, "message_id": "msg-bad", "created_at": 2000, "unexpected_legacy_field": "boom"}
        mock_dynamodb.query.return_value = {"Items": [good, bad]}

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert len(result) == 1
        assert result[0].message_id == "msg-good"

    def test_get_history_skips_rating_rows(self, mock_dynamodb):
        turn = {
            "session_id": "sess-1",
            "message_id": "sess-1#a1",
            "message": "Frage",
            "response_text": "Antwort",
            "created_at": 1000,
            "sources": [],
        }
        rating = {"session_id": "sess-1", "message_id": "RATING#DIALOG", "created_at": 2000, "feedback": {}}
        mock_dynamodb.query.return_value = {"Items": [turn, rating]}

        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            result = ConversationStore().get_history("sess-1")

        assert [item.message_id for item in result] == ["sess-1#a1"]
        mock_logger.warning.assert_not_called()


class TestConversationStoreShrink:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_store_conversation_caps_source_count_and_content(self, mock_dynamodb):
        """Stored items keep at most 8 sources with capped content."""
        sources = [{"sourceIndex": i, "title": f"S{i}", "content": "x" * 5000} for i in range(1, 12)]

        store = ConversationStore()
        store.store_conversation(
            session_id="sess-1",
            message="Frage",
            response_text="Antwort",
            sources=sources,
            message_id="msg-1",
        )

        stored_item = mock_dynamodb.put_item.call_args[1]["Item"]
        stored_sources = stored_item["sources"]
        assert len(stored_sources) == 8
        assert all(len(s["content"]) <= 2000 + len(" …[gekürzt]") for s in stored_sources)
        assert stored_sources[0]["content"].endswith("…[gekürzt]")

    def test_store_conversation_leaves_small_sources_untouched(self, mock_dynamodb):
        sources = [{"sourceIndex": 1, "title": "S1", "content": "short"}]

        store = ConversationStore()
        store.store_conversation(
            session_id="sess-1",
            message="Frage",
            response_text="Antwort",
            sources=sources,
            message_id="msg-1",
        )

        stored_item = mock_dynamodb.put_item.call_args[1]["Item"]
        assert stored_item["sources"] == sources

    def test_store_conversation_swallows_put_failure_and_logs_marker(self, mock_dynamodb):
        """A failed put_item must not raise (it would 500 the request) and must log the stable marker."""
        from backend_orchestrator.repositories.conversation import _STORE_FAILURE_LOG_MESSAGE

        mock_dynamodb.put_item.side_effect = Exception("boom")

        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.store_conversation(
                session_id="sess-1",
                message="Frage",
                response_text="Antwort",
                sources=[],
                message_id="msg-1",
            )

        mock_logger.exception.assert_called_once()
        assert mock_logger.exception.call_args.args[0] == _STORE_FAILURE_LOG_MESSAGE


class TestConversationStoreItemSizeValidation:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_store_conversation_rejects_oversized_item_and_logs_error(self, mock_dynamodb):
        store = ConversationStore()

        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.store_conversation(
                session_id="sess-1",
                message="x" * (390 * 1024),
                response_text="Antwort",
                sources=[],
                message_id="msg-1",
            )

        mock_dynamodb.put_item.assert_not_called()
        mock_logger.error.assert_called_once()
        assert "DynamoDB item validation failed" in mock_logger.error.call_args.args[0]
        assert mock_logger.error.call_args.kwargs["extra"]["context"] == "store_conversation"

    def test_store_conversation_writes_item_when_size_within_limit(self, mock_dynamodb):
        store = ConversationStore()

        store.store_conversation(
            session_id="sess-1",
            message="Frage",
            response_text="Antwort",
            sources=[{"sourceId": "doc-1", "content": "short"}],
            message_id="msg-1",
        )

        mock_dynamodb.put_item.assert_called_once()

    def test_calculate_item_size_handles_nested_bytes_decimal_and_bool(self, mock_dynamodb):
        store = ConversationStore()

        size = store._calculate_item_size({
            "nested": {
                "arr": [1, Decimal("1.23"), b"ab", True],
            }
        })

        # nested(6) + arr(3) + [int(1) + decimal(4) + bytes(2) + bool(1)]
        assert size == 17

    def test_calculate_item_size_counts_bool_as_single_byte_not_int_string(self, mock_dynamodb):
        """Bool must be counted before int because bool is an int subclass."""
        store = ConversationStore()

        assert store._calculate_item_size({"flag": True}) == 5


class TestConversationStoreUpdateFeedback:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_update_feedback_does_not_use_feedback_only_size_precheck(self, mock_dynamodb):
        """update_feedback does not claim to validate full post-update item size."""
        store = ConversationStore()

        with patch.object(store, "_validate_item_size", return_value=False) as mock_validate:
            result = store.update_feedback("sess-1", "msg-1", {"rating": 1, "comment": "ok"})

        assert result is True
        mock_validate.assert_not_called()
        mock_dynamodb.update_item.assert_called_once()


class TestConversationStorePutRatingRow:
    """Tests for the rating rows of a conversation."""

    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_writes_row_with_ttl_and_created_at(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        store = ConversationStore()
        before = int(time.time())

        assert store.put_rating_row("sess-1", "RATING#DIALOG", {"scope": "dialog", "used_scenario": 2}) is True

        item = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert item["session_id"] == "sess-1"
        assert item["message_id"] == "RATING#DIALOG"
        assert item["feedback"] == {"scope": "dialog", "used_scenario": 2}
        assert item["created_at"] >= before * 1000
        assert item["ttl"] > before
        assert "message" not in item

    def test_review_row_uses_namespace_and_7_day_ttl(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-mr")
        store = ConversationStore()

        store.put_rating_row("sess-1", "RATING#FINAL", {"scope": "test"})

        item = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert item["session_id"] == "review/my-mr#sess-1"
        assert item["ttl"] <= int(time.time()) + 21 * 86400

    def test_returns_false_on_write_error(self, mock_dynamodb):
        mock_dynamodb.put_item.side_effect = Exception("throttled")

        assert ConversationStore().put_rating_row("sess-1", "RATING#FINAL", {}) is False


class TestConversationStoreReviewPrefix:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_ns_prefixes_when_review_id_set(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        store = ConversationStore()
        assert store._ns("abc123") == "review/my-branch#abc123"

    def test_ns_passthrough_when_review_id_absent(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        store = ConversationStore()
        assert store._ns("abc123") == "abc123"

    def test_store_conversation_uses_namespaced_session_id(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        store = ConversationStore()
        store.store_conversation("abc123", "q", "a", message_id="msg-1")
        assert mock_dynamodb.put_item.call_args.kwargs["Item"]["session_id"] == "review/my-branch#abc123"

    def test_get_history_uses_namespaced_session_id(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        mock_dynamodb.query.return_value = {"Items": []}
        store = ConversationStore()
        store.get_history("abc123")
        key_cond = mock_dynamodb.query.call_args.kwargs["KeyConditionExpression"]
        assert key_cond.get_expression()["values"][1] == "review/my-branch#abc123"

    def test_update_feedback_uses_namespaced_session_id(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        store = ConversationStore()
        store.update_feedback("abc123", "msg-1", {"rating": 1})
        assert mock_dynamodb.update_item.call_args.kwargs["Key"]["session_id"] == "review/my-branch#abc123"

    def test_get_message_uses_namespaced_session_id(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        mock_dynamodb.get_item.return_value = {"Item": None}
        store = ConversationStore()
        store.get_message("abc123", "msg-1")
        assert mock_dynamodb.get_item.call_args.kwargs["Key"]["session_id"] == "review/my-branch#abc123"


class TestConversationItemTtl:
    """Tests for the optional ttl field on ConversationItem (TKT-REV-09)."""

    def _base_item(self) -> dict:
        return {
            "session_id": "sess-1",
            "message_id": "msg-1",
            "message": "Frage",
            "response_text": "Antwort",
            "created_at": 1000,
            "sources": [],
        }

    def test_validates_item_with_ttl(self):
        item = ConversationItem.model_validate({**self._base_item(), "ttl": 1234567890})
        assert item.ttl == 1234567890

    def test_validates_item_without_ttl_defaults_none(self):
        item = ConversationItem.model_validate(self._base_item())
        assert item.ttl is None

    def test_model_dump_excludes_none_ttl(self):
        item = ConversationItem.model_validate(self._base_item())
        assert "ttl" not in item.model_dump(exclude_none=True)

    def test_model_dump_includes_set_ttl(self):
        item = ConversationItem.model_validate({**self._base_item(), "ttl": 42})
        assert item.model_dump(exclude_none=True)["ttl"] == 42

    def test_unexpected_field_still_forbidden(self):
        """extra='forbid' remains intact for genuinely unknown fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConversationItem.model_validate({**self._base_item(), "unexpected_legacy_field": "boom"})


class TestConversationStoreTtl:
    """Tests for TTL on store_conversation (#480: always set, review=7d, default=30d)."""

    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_store_sets_ttl_when_review_id_present(self, mock_dynamodb, monkeypatch):
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        before = int(time.time()) + 21 * 86400

        store = ConversationStore()
        store.store_conversation("abc123", "q", "a", message_id="msg-1")

        after = int(time.time()) + 21 * 86400
        stored = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert "ttl" in stored
        assert isinstance(stored["ttl"], int)
        assert before <= stored["ttl"] <= after

    def test_store_sets_ttl_without_review_id(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        monkeypatch.setenv("CONVERSATION_TTL_DAYS", "30")
        from backend_orchestrator.config import Config

        Config._instance = None

        before = int(time.time()) + 30 * 86400

        store = ConversationStore()
        store.store_conversation("abc123", "q", "a", message_id="msg-1")

        after = int(time.time()) + 30 * 86400
        stored = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert "ttl" in stored
        assert isinstance(stored["ttl"], int)
        assert before <= stored["ttl"] <= after

        Config._instance = None

    def test_store_uses_custom_ttl_days_from_config(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        monkeypatch.setenv("CONVERSATION_TTL_DAYS", "90")
        from backend_orchestrator.config import Config

        Config._instance = None

        before = int(time.time()) + 90 * 86400

        store = ConversationStore()
        store.store_conversation("abc123", "q", "a", message_id="msg-1")

        after = int(time.time()) + 90 * 86400
        stored = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert before <= stored["ttl"] <= after

        Config._instance = None

    def test_store_preserves_other_fields_with_review_id(self, mock_dynamodb, monkeypatch):
        """Enabling ttl must not disturb namespacing or other stored fields."""
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        sources = [{"sourceIndex": 1, "title": "S1", "content": "short"}]

        store = ConversationStore()
        store.store_conversation("abc123", "Frage", "Antwort", sources=sources, message_id="msg-1")

        stored = mock_dynamodb.put_item.call_args.kwargs["Item"]
        assert stored["session_id"] == "review/my-branch#abc123"
        assert stored["message_id"] == "msg-1"
        assert stored["message"] == "Frage"
        assert stored["response_text"] == "Antwort"
        assert stored["sources"] == sources

    def test_get_history_returns_item_with_ttl(self, mock_dynamodb, monkeypatch):
        """A stored item carrying ttl round-trips through read validation."""
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "session_id": "review/my-branch#abc123",
                    "message_id": "msg-1",
                    "message": "Frage",
                    "response_text": "Antwort",
                    "created_at": 1000,
                    "sources": [],
                    "ttl": int(time.time()) + 7 * 86400,
                }
            ]
        }

        store = ConversationStore()
        result = store.get_history("abc123")

        assert len(result) == 1
        assert result[0].ttl is not None
        assert result[0].message_id == "msg-1"

    def test_get_history_filters_expired_items(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        now = int(time.time())
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "session_id": "sess-1",
                    "message_id": "msg-expired",
                    "message": "old question",
                    "response_text": "old answer",
                    "created_at": 1000,
                    "sources": [],
                    "ttl": now - 100,
                },
                {
                    "session_id": "sess-1",
                    "message_id": "msg-valid",
                    "message": "new question",
                    "response_text": "new answer",
                    "created_at": 2000,
                    "sources": [],
                    "ttl": now + 86400,
                },
            ]
        }

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert len(result) == 1
        assert result[0].message_id == "msg-valid"

    def test_get_history_includes_items_without_ttl(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        mock_dynamodb.query.return_value = {
            "Items": [
                {
                    "session_id": "sess-1",
                    "message_id": "msg-legacy",
                    "message": "question",
                    "response_text": "answer",
                    "created_at": 1000,
                    "sources": [],
                },
            ]
        }

        store = ConversationStore()
        result = store.get_history("sess-1")

        assert len(result) == 1
        assert result[0].message_id == "msg-legacy"

    def test_get_message_returns_item_with_ttl(self, mock_dynamodb, monkeypatch):
        """get_message also round-trips a ttl-bearing item."""
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        ttl_value = int(time.time()) + 7 * 86400
        mock_dynamodb.get_item.return_value = {
            "Item": {
                "session_id": "review/my-branch#abc123",
                "message_id": "msg-1",
                "message": "Frage",
                "response_text": "Antwort",
                "created_at": 1000,
                "sources": [],
                "ttl": ttl_value,
            }
        }

        store = ConversationStore()
        result = store.get_message("abc123", "msg-1")

        assert result is not None
        assert result.ttl == ttl_value

    def test_get_message_returns_none_for_expired_item(self, mock_dynamodb, monkeypatch):
        monkeypatch.delenv("REVIEW_ID", raising=False)
        mock_dynamodb.get_item.return_value = {
            "Item": {
                "session_id": "sess-1",
                "message_id": "msg-1",
                "message": "Frage",
                "response_text": "Antwort",
                "created_at": 1000,
                "sources": [],
                "ttl": int(time.time()) - 100,
            }
        }

        store = ConversationStore()
        result = store.get_message("sess-1", "msg-1")

        assert result is None


class TestConversationTtlDaysConfig:
    """Tests for CONVERSATION_TTL_DAYS parsing in Config (#480)."""

    def test_falls_back_to_default_on_invalid_env(self, monkeypatch):
        """Non-numeric CONVERSATION_TTL_DAYS must not crash Lambda cold-start."""
        monkeypatch.setenv("CONVERSATION_TTL_DAYS", "not-a-number")
        from backend_orchestrator.config import Config

        Config._instance = None
        try:
            cfg = Config()
            assert cfg.conversation_ttl_days == 30
        finally:
            Config._instance = None


class TestConversationStoreSessionMasking:
    """The full session_id / message_id must never appear in log records (#482)."""

    _FULL_SESSION = "sess-full-value-12345"
    _FULL_MESSAGE = "sess-full-value-12345#uuid-abcdef"

    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def _assert_no_leak(self, mock_logger):
        for call in mock_logger.method_calls:
            call_str = str(call)
            assert self._FULL_SESSION not in call_str, f"full session_id leaked into: {call_str}"

    def test_store_conversation_masks_on_put_failure(self, mock_dynamodb):
        mock_dynamodb.put_item.side_effect = Exception("boom")
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.store_conversation(
                session_id=self._FULL_SESSION,
                message="q",
                response_text="a",
                sources=[],
                message_id=self._FULL_MESSAGE,
            )
        self._assert_no_leak(mock_logger)

    def test_store_conversation_masks_on_oversized_item(self, mock_dynamodb):
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.store_conversation(
                session_id=self._FULL_SESSION,
                message="x" * (390 * 1024),
                response_text="a",
                sources=[],
                message_id=self._FULL_MESSAGE,
            )
        self._assert_no_leak(mock_logger)

    def test_update_feedback_masks_on_missing_item(self, mock_dynamodb):
        exc_cls = mock_dynamodb.meta.client.exceptions.ConditionalCheckFailedException
        real_exc = type("ConditionalCheckFailedException", (Exception,), {})
        mock_dynamodb.meta.client.exceptions.ConditionalCheckFailedException = real_exc
        mock_dynamodb.update_item.side_effect = real_exc("nope")
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.update_feedback(self._FULL_SESSION, self._FULL_MESSAGE, {"thumbs_up": True})
        mock_dynamodb.meta.client.exceptions.ConditionalCheckFailedException = exc_cls
        self._assert_no_leak(mock_logger)

    def test_update_feedback_masks_on_generic_exception(self, mock_dynamodb):
        real_ccfe = type("ConditionalCheckFailedException", (Exception,), {})
        mock_dynamodb.meta.client.exceptions.ConditionalCheckFailedException = real_ccfe
        mock_dynamodb.update_item.side_effect = RuntimeError("boom")
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.update_feedback(self._FULL_SESSION, self._FULL_MESSAGE, {"thumbs_up": True})
        self._assert_no_leak(mock_logger)

    def test_get_message_masks_on_exception(self, mock_dynamodb):
        mock_dynamodb.get_item.side_effect = Exception("boom")
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.get_message(self._FULL_SESSION, self._FULL_MESSAGE)
        self._assert_no_leak(mock_logger)

    def test_delete_session_masks_on_exception(self, mock_dynamodb):
        mock_dynamodb.query.side_effect = Exception("boom")
        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            store.delete_session(self._FULL_SESSION)
        self._assert_no_leak(mock_logger)

    def test_get_history_masks_on_pagination_error(self, mock_dynamodb):
        mock_dynamodb.query.side_effect = Exception("boom")
        store = ConversationStore()
        with (
            patch("backend_orchestrator.repositories.conversation.logger") as mock_logger,
            pytest.raises(HistoryReadError),
        ):
            store.get_history(self._FULL_SESSION)
        self._assert_no_leak(mock_logger)

    def test_store_conversation_validation_error_masks(self, mock_dynamodb):
        from pydantic import ValidationError

        with patch(
            "backend_orchestrator.repositories.conversation.ConversationItem",
        ) as mock_item:
            mock_item.side_effect = ValidationError.from_exception_data("ConversationItem", [])
            store = ConversationStore()
            with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
                store.store_conversation(
                    session_id=self._FULL_SESSION,
                    message="q",
                    response_text="a",
                    sources=[],
                    message_id=self._FULL_MESSAGE,
                )
        self._assert_no_leak(mock_logger)


class TestConversationStoreDeleteSession:
    @pytest.fixture
    def mock_dynamodb(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_table = MagicMock()
            mock_boto.resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_delete_session_queries_and_batch_deletes(self, mock_dynamodb):
        mock_dynamodb.query.return_value = {
            "Items": [
                {"session_id": "sess-1", "message_id": "msg-1"},
                {"session_id": "sess-1", "message_id": "msg-2"},
            ]
        }
        mock_batch_writer = MagicMock()
        mock_dynamodb.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_dynamodb.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        store = ConversationStore()
        count = store.delete_session("sess-1")

        assert count == 2
        assert mock_batch_writer.delete_item.call_count == 2

    def test_delete_session_empty_session(self, mock_dynamodb):
        mock_dynamodb.query.return_value = {"Items": []}
        mock_batch_writer = MagicMock()
        mock_dynamodb.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_dynamodb.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        store = ConversationStore()
        count = store.delete_session("nonexistent")

        assert count == 0
        mock_batch_writer.delete_item.assert_not_called()

    def test_delete_session_handles_pagination(self, mock_dynamodb):
        mock_dynamodb.query.side_effect = [
            {"Items": [{"session_id": "s", "message_id": "m1"}], "LastEvaluatedKey": {"k": "v"}},
            {"Items": [{"session_id": "s", "message_id": "m2"}]},
        ]
        mock_batch_writer = MagicMock()
        mock_dynamodb.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_dynamodb.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        store = ConversationStore()
        count = store.delete_session("s")

        assert count == 2
        assert mock_dynamodb.query.call_count == 2

    def test_delete_session_logs_error_on_failure(self, mock_dynamodb):
        mock_dynamodb.query.side_effect = Exception("DynamoDB error")

        store = ConversationStore()
        with patch("backend_orchestrator.repositories.conversation.logger") as mock_logger:
            count = store.delete_session("sess-1")

        assert count == 0
        mock_logger.exception.assert_called_once()

    def test_delete_session_uses_namespaced_id(self, mock_dynamodb, monkeypatch):
        """Uses _ns() for review-env compatibility."""
        monkeypatch.setenv("REVIEW_ID", "my-branch")
        mock_dynamodb.query.return_value = {"Items": []}
        mock_batch_writer = MagicMock()
        mock_dynamodb.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_dynamodb.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        store = ConversationStore()
        store.delete_session("abc123")

        key_cond = mock_dynamodb.query.call_args.kwargs["KeyConditionExpression"]
        assert key_cond.get_expression()["values"][1] == "review/my-branch#abc123"

    def test_delete_session_disabled_store(self):
        with patch("backend_orchestrator.repositories.conversation.boto3") as mock_boto:
            mock_boto.resource.side_effect = Exception("no db")
            store = ConversationStore()

        count = store.delete_session("sess-1")
        assert count == 0
