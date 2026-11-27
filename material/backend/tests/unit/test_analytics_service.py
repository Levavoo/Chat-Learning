"""Unit tests for AnalyticsService."""

from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.services.analytics_service import AnalyticsService, _aggregate


class TestAggregate:
    def test_empty_items_returns_zeros(self):
        result = _aggregate([])
        assert result.total_sessions == 0
        assert result.total_messages == 0
        assert result.avg_messages_per_session == 0.0
        assert result.top_domains == []
        assert result.top_sources == []
        assert result.feedback_thumbs_up_rate is None
        assert result.blocked_rate == 0.0

    def test_counts_sessions_and_messages(self):
        items = [
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {"session_id": "s2", "sources": [], "domain": "reha"},
        ]
        result = _aggregate(items)
        assert result.total_sessions == 2
        assert result.total_messages == 3
        assert result.avg_messages_per_session == 1.5

    def test_top_domains_sorted_by_count(self):
        items = [
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {"session_id": "s2", "sources": [], "domain": "reha"},
        ]
        result = _aggregate(items)
        assert result.top_domains[0].domain == "rente"
        assert result.top_domains[0].count == 2
        assert result.top_domains[1].domain == "reha"
        assert result.top_domains[1].count == 1

    def test_top_sources_counted(self):
        items = [
            {"session_id": "s1", "sources": [{"sourceName": "Broschüre A"}, {"sourceName": "Broschüre B"}]},
            {"session_id": "s2", "sources": [{"sourceName": "Broschüre A"}]},
        ]
        result = _aggregate(items)
        assert result.top_sources[0].source_name == "Broschüre A"
        assert result.top_sources[0].count == 2

    def test_feedback_thumbs_up_rate(self):
        items = [
            {"session_id": "s1", "sources": [], "feedback": {"thumbsUp": "Ja"}},
            {"session_id": "s2", "sources": [], "feedback": {"thumbsUp": "Ja"}},
            {"session_id": "s3", "sources": [], "feedback": {"thumbsUp": "Nein"}},
        ]
        result = _aggregate(items)
        assert result.feedback_thumbs_up_rate == pytest.approx(0.67)

    def test_no_feedback_returns_none_rate(self):
        items = [{"session_id": "s1", "sources": []}]
        result = _aggregate(items)
        assert result.feedback_thumbs_up_rate is None

    def test_feedback_good_count(self):
        items = [
            {"session_id": "s1", "sources": [], "feedback": {"helpfulness": "GOOD"}},
            {"session_id": "s2", "sources": [], "feedback": {"helpfulness": "GOOD"}},
            {"session_id": "s3", "sources": [], "feedback": {"helpfulness": "NEUTRAL"}},
            {"session_id": "s4", "sources": [], "feedback": {"helpfulness": "BAD"}},
            {"session_id": "s5", "sources": []},  # no feedback
        ]
        result = _aggregate(items)
        assert result.feedback_good_count == 2
        assert result.feedback_neutral_count == 1
        assert result.feedback_bad_count == 1

    def test_feedback_counts_historic_thumbsup_rows(self):
        items = [
            {"session_id": "s1", "sources": [], "feedback": {"thumbsUp": "GOOD"}},
            {"session_id": "s2", "sources": [], "feedback": {"helpfulness": "NEUTRAL"}},
        ]
        result = _aggregate(items)
        assert result.feedback_good_count == 1
        assert result.feedback_neutral_count == 1

    def test_feedback_counts_zero_when_no_feedback(self):
        items = [{"session_id": "s1", "sources": []}]
        result = _aggregate(items)
        assert result.feedback_good_count == 0
        assert result.feedback_neutral_count == 0
        assert result.feedback_bad_count == 0

    def test_feedback_counts_zero_on_empty(self):
        result = _aggregate([])
        assert result.feedback_good_count == 0
        assert result.feedback_neutral_count == 0
        assert result.feedback_bad_count == 0

    def test_feedback_old_ja_nein_does_not_affect_counts(self):
        """Legacy 'Ja'/'Nein' values should not increment GOOD/NEUTRAL/BAD counts."""
        items = [
            {"session_id": "s1", "sources": [], "feedback": {"thumbsUp": "Ja"}},
            {"session_id": "s2", "sources": [], "feedback": {"thumbsUp": "Nein"}},
        ]
        result = _aggregate(items)
        assert result.feedback_good_count == 0
        assert result.feedback_neutral_count == 0
        assert result.feedback_bad_count == 0
        assert result.feedback_thumbs_up_rate == 0.5

    def test_blocked_rate(self):
        items = [
            {"session_id": "s1", "sources": [], "blocked_by_guardrail": True},
            {"session_id": "s2", "sources": []},
            {"session_id": "s3", "sources": []},
            {"session_id": "s4", "sources": []},
        ]
        result = _aggregate(items)
        assert result.blocked_rate == 0.25


class TestAnalyticsService:
    @patch("backend_orchestrator.services.analytics_service.boto3")
    def test_get_analytics_returns_response(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.side_effect = [
            {"Items": [{"session_id": "s1", "message_id": "m1", "created_at": 1000, "sources": [], "domain": "rente"}]},
            {"Items": []},
            {"Items": []},
            {"Items": []},
            {"Items": []},
            {"Items": []},
            {"Items": []},
        ]

        service = AnalyticsService()
        result = service.get_analytics(from_ts=0, to_ts=9999999999999)

        assert result.total_sessions == 1
        assert result.total_messages == 1
        assert result.top_domains[0].domain == "rente"

    @patch("backend_orchestrator.services.analytics_service.boto3")
    def test_query_handles_pagination(self, mock_boto3):
        """GSI query paginates correctly via LastEvaluatedKey."""
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        call_count = {"n": 0}

        def query_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"Items": [{"session_id": "s1", "domain": "rente", "sources": []}], "LastEvaluatedKey": "key1"}
            if call_count["n"] == 2:
                return {"Items": [{"session_id": "s2", "domain": "rente", "sources": []}]}
            return {"Items": []}

        mock_table.query.side_effect = query_side_effect

        service = AnalyticsService()
        items = service._query_by_domains(0, 9999999999999)

        assert len(items) == 2
        assert mock_table.query.call_count == 8


class TestConversationItemTopic:
    def test_topic_field_defaults_to_none(self):
        item = ConversationItem(
            session_id="s1",
            message_id="m1",
            message="test",
            response_text="response",
            sources=[],
        )
        assert item.topic is None

    def test_topic_field_accepts_string(self):
        item = ConversationItem(
            session_id="s1",
            message_id="m1",
            message="test",
            response_text="response",
            sources=[],
            topic="altersrente_regulaer",
        )
        assert item.topic == "altersrente_regulaer"

    def test_topic_field_no_validation_error_on_extra_forbid(self):
        """extra='forbid' must not reject items with topic written by classify_topics.py."""
        item = ConversationItem.model_validate({
            "session_id": "s1",
            "message_id": "m1",
            "message": "test",
            "response_text": "response",
            "sources": [],
            "topic": "reha_medizinisch",
        })
        assert item.topic == "reha_medizinisch"


class TestTopicAggregation:
    def test_items_with_topic_aggregated(self):
        items = [
            {
                "session_id": "s1",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": 1_700_000_000_000,
            },
            {
                "session_id": "s2",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": 1_700_000_000_000,
            },
            {
                "session_id": "s3",
                "sources": [],
                "domain": "reha",
                "topic": "reha_medizinisch",
                "created_at": 1_700_000_000_000,
            },
        ]
        result = _aggregate(items)
        assert len(result.top_topics) == 2
        assert result.top_topics[0].topic == "altersrente_regulaer"
        assert result.top_topics[0].count == 2

    def test_topic_domain_resolved_from_taxonomy_not_dynamodb(self):
        """TopicCount.domain must come from taxonomy, not item's domain field."""
        items = [
            {
                "session_id": "s1",
                "sources": [],
                "domain": "rente",
                "topic": "betriebliche_altersvorsorge",
                "created_at": 1_700_000_000_000,
            },
        ]
        result = _aggregate(items)
        assert result.top_topics[0].topic == "betriebliche_altersvorsorge"
        assert result.top_topics[0].domain == "sonstiges"

    def test_items_without_topic_excluded_from_topic_counts(self):
        items = [
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {
                "session_id": "s2",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": 1_700_000_000_000,
            },
        ]
        result = _aggregate(items)
        assert len(result.top_topics) == 1
        assert result.top_topics[0].count == 1
        assert result.total_messages == 2
        assert result.total_sessions == 2

    def test_all_topics_none_returns_empty_lists(self):
        items = [
            {"session_id": "s1", "sources": [], "domain": "rente"},
            {"session_id": "s2", "sources": [], "domain": "rente"},
        ]
        result = _aggregate(items)
        assert result.top_topics == []
        assert result.topic_time_series == []

    def test_empty_items_returns_empty_topic_lists(self):
        result = _aggregate([])
        assert result.top_topics == []
        assert result.topic_time_series == []

    def test_top_15_cap(self):
        items = [
            {
                "session_id": f"s{i}",
                "sources": [],
                "domain": "rente",
                "topic": f"topic_{i:02d}",
                "created_at": 1_700_000_000_000,
            }
            for i in range(25)
        ]
        result = _aggregate(items)
        assert len(result.top_topics) == 15

    def test_topic_time_series_top_5_cap(self):
        items = [
            {
                "session_id": f"s{i}_{j}",
                "sources": [],
                "domain": "rente",
                "topic": f"topic_{i:02d}",
                "created_at": 1_700_000_000_000,
            }
            for i in range(6)
            for j in range(2)
        ]
        result = _aggregate(items)
        assert len(result.topic_time_series) == 5

    def test_time_series_grouped_by_iso_week(self):
        week1_ts = 1_748_736_000_000  # 2025-06-02 (Monday)
        week2_ts = 1_749_340_800_000  # 2025-06-09 (Monday)
        items = [
            {
                "session_id": "s1",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": week1_ts,
            },
            {
                "session_id": "s2",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": week1_ts,
            },
            {
                "session_id": "s3",
                "sources": [],
                "domain": "rente",
                "topic": "altersrente_regulaer",
                "created_at": week2_ts,
            },
        ]
        result = _aggregate(items)
        ts_entry = result.topic_time_series[0]
        assert ts_entry.topic == "altersrente_regulaer"
        assert len(ts_entry.data_points) == 2
        counts = {dp.week_start: dp.count for dp in ts_entry.data_points}
        assert list(counts.values()) == [2, 1]  # sorted by week

    def test_existing_analytics_fields_unaffected_by_topic_changes(self):
        """Adding topic aggregation must not regress domain/sources/feedback/blocked."""
        items = [
            {
                "session_id": "s1",
                "sources": [{"sourceName": "Brosch A"}],
                "domain": "rente",
                "feedback": {"thumbsUp": "GOOD"},
                "topic": "altersrente_regulaer",
                "created_at": 1_700_000_000_000,
            },
            {"session_id": "s2", "sources": [], "domain": "reha", "blocked_by_guardrail": True},
        ]
        result = _aggregate(items)
        assert result.total_messages == 2
        assert result.top_domains[0].domain == "rente"
        assert result.top_sources[0].source_name == "Brosch A"
        assert result.feedback_good_count == 1
        assert result.blocked_rate == 0.5
