"""Unit tests for the analytics_report CLI script."""

import csv
import io
import re
from argparse import Namespace
from datetime import UTC, datetime

import pytest

from backend_orchestrator.models.api_models import (
    AnalyticsResponse,
    DomainCount,
    SourceCount,
    TopicCount,
    TopicTimeSeriesEntry,
    WeekDataPoint,
)
from scripts.analytics_report import (
    _GOLIVE_DATE,
    _NO_VALUE,
    _bar,
    _format_csv,
    _format_ranking,
    _format_text,
    _parse_date_to_ms,
    _percent,
    _preflight,
    _rate_percent,
    _resolve_window,
    _timestamped_path,
    _truncate,
)


def _sample_response() -> AnalyticsResponse:
    return AnalyticsResponse(
        total_sessions=40,
        total_messages=100,
        avg_messages_per_session=2.5,
        top_domains=[DomainCount(domain="rente", count=60), DomainCount(domain="reha", count=40)],
        top_sources=[SourceCount(source_name="Merkblatt Altersrente", count=25)],
        feedback_thumbs_up_rate=0.75,
        blocked_rate=0.1,
        feedback_good_count=15,
        feedback_neutral_count=3,
        feedback_bad_count=2,
        top_topics=[TopicCount(topic="altersrente_regel", domain="rente", count=30)],
        topic_time_series=[
            TopicTimeSeriesEntry(
                topic="altersrente_regel",
                data_points=[WeekDataPoint(week_start="2026-09-14", count=30)],
            )
        ],
    )


def _empty_response() -> AnalyticsResponse:
    return AnalyticsResponse(
        total_sessions=0,
        total_messages=0,
        avg_messages_per_session=0.0,
        top_domains=[],
        top_sources=[],
        feedback_thumbs_up_rate=None,
        blocked_rate=0.0,
    )


class TestParseDateToMs:
    def test_start_of_day(self):
        result = _parse_date_to_ms("2026-09-15")
        assert datetime.fromtimestamp(result / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S") == "2026-09-15 00:00:00"

    def test_end_of_day_is_inclusive(self):
        result = _parse_date_to_ms("2026-09-15", end_of_day=True)
        rendered = datetime.fromtimestamp(result / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        assert rendered == "2026-09-15 23:59:59"

    def test_invalid_date_raises(self):
        with pytest.raises(Exception, match="Ungueltiges Datum"):
            _parse_date_to_ms("15.09.2026")


class TestPercentFormatting:
    def test_percent_regular_value(self):
        assert _percent(1, 4) == "25 %"

    def test_percent_zero_denominator_yields_placeholder(self):
        assert _percent(0, 0) == _NO_VALUE

    def test_rate_percent_regular_value(self):
        assert _rate_percent(0.75) == "75 %"

    def test_rate_percent_none_yields_placeholder(self):
        assert _rate_percent(None) == _NO_VALUE


class TestBar:
    def test_zero_count_renders_empty(self):
        assert _bar(0, 10) == ""

    def test_max_count_renders_full_width(self):
        assert len(_bar(10, 10)) == 30

    def test_zero_max_is_safe(self):
        assert _bar(5, 0) == ""


class TestTruncate:
    def test_short_value_unchanged(self):
        assert _truncate("kurz") == "kurz"

    def test_long_value_is_shortened_with_ellipsis(self):
        result = _truncate("x" * 60, limit=10)
        assert result == "xxxxxxx..."
        assert len(result) == 10


class TestFormatRanking:
    def test_empty_rows_yield_no_lines(self):
        assert _format_ranking("TITEL", []) == []

    def test_rows_render_with_title(self):
        lines = _format_ranking("TITEL", [("rente", 10), ("reha", 5)])
        assert lines[0] == "TITEL"
        assert "rente" in lines[1]
        assert "10" in lines[1]


class TestResolveWindow:
    def test_defaults_to_golive_date(self):
        args = Namespace(from_date=None, to_date=None, days=None)
        from_ts, to_ts = _resolve_window(args)
        assert from_ts == _parse_date_to_ms(_GOLIVE_DATE)
        assert to_ts > from_ts

    def test_from_date_takes_precedence_over_days(self):
        args = Namespace(from_date="2026-09-16", to_date="2026-09-17", days=90)
        from_ts, _ = _resolve_window(args)
        assert from_ts == _parse_date_to_ms("2026-09-16")

    def test_days_is_used_when_no_from_date(self):
        args = Namespace(from_date=None, to_date="2026-09-20", days=2)
        from_ts, to_ts = _resolve_window(args)
        assert to_ts - from_ts == 2 * 86_400_000

    def test_to_date_is_inclusive(self):
        args = Namespace(from_date="2026-09-15", to_date="2026-09-15", days=None)
        from_ts, to_ts = _resolve_window(args)
        assert to_ts - from_ts == 86_400_000 - 1


class TestFormatText:
    def test_contains_usage_kpis(self):
        out = _format_text(_sample_response(), "renate-conversations-prod", 0, 1)
        assert "Sitzungen" in out
        assert "40" in out
        assert "Nachrichten" in out
        assert "100" in out

    def test_contains_table_name(self):
        out = _format_text(_sample_response(), "renate-conversations-prod", 0, 1)
        assert "renate-conversations-prod" in out

    def test_feedback_percentages_match_dashboard_logic(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        assert "75 %" in out
        assert "20 %" in out

    def test_blocked_rate_rendered_as_percent(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        assert "10 %" in out

    def test_sections_present(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        for heading in (
            "NUTZUNG",
            "FEEDBACK",
            "GUARDRAIL",
            "TOP-THEMENFELDER",
            "TOP-THEMEN",
            "TOP-QUELLEN",
        ):
            assert heading in out

    def test_weekly_series_is_not_shown(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        assert "WOCHENVERLAUF" not in out
        assert "KW ab" not in out

    def test_topic_shows_taxonomy_domain(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        assert "altersrente_regel (rente)" in out

    def test_empty_response_shows_hint(self):
        out = _format_text(_empty_response(), "t", 0, 1)
        assert "Keine Daten im gewaehlten Zeitraum" in out

    def test_empty_response_omits_ranking_sections(self):
        out = _format_text(_empty_response(), "t", 0, 1)
        assert "TOP-THEMENFELDER" not in out

    def test_undefined_rates_render_placeholder(self):
        out = _format_text(_empty_response(), "t", 0, 1)
        assert _NO_VALUE in out

    def test_thumbs_up_rate_is_not_shown(self):
        out = _format_text(_sample_response(), "t", 0, 1)
        assert "Daumen" not in out


class TestTimestampedPath:
    _STAMP = r"\d{4}-\d{2}-\d{2}_\d{4}"

    def test_timestamp_inserted_before_extension(self):
        result = _timestamped_path("kpis.csv", "csv")
        assert re.fullmatch(rf"kpis-{self._STAMP}\.csv", result)

    def test_suffix_added_from_format_when_missing(self):
        assert _timestamped_path("kpis", "csv").endswith(".csv")
        assert _timestamped_path("kpis", "json").endswith(".json")
        assert _timestamped_path("kpis", "text").endswith(".txt")

    def test_parent_directory_preserved(self, tmp_path):
        result = _timestamped_path(str(tmp_path / "kpis.csv"), "csv")
        assert result.startswith(str(tmp_path))
        assert re.fullmatch(rf"{re.escape(str(tmp_path))}/kpis-{self._STAMP}\.csv", result)

    def test_tilde_is_expanded(self):
        result = _timestamped_path("~/kpis.csv", "csv")
        assert not result.startswith("~")
        assert result.endswith(".csv")

    def test_existing_suffix_wins_over_format_default(self):
        assert _timestamped_path("kpis.txt", "csv").endswith(".txt")


class TestPreflight:
    def test_returns_none_when_table_reachable(self, monkeypatch):
        class _Client:
            def describe_table(self, TableName):
                return {"Table": {"TableName": TableName}}

        monkeypatch.setattr("boto3.client", lambda *a, **kw: _Client())
        assert _preflight("renate-conversations-prod", "eu-central-1") is None

    def test_returns_message_when_access_fails(self, monkeypatch):
        class _Client:
            def describe_table(self, TableName):
                raise RuntimeError("no credentials")

        monkeypatch.setattr("boto3.client", lambda *a, **kw: _Client())
        result = _preflight("renate-conversations-prod", "eu-central-1")
        assert result is not None
        assert "RuntimeError" in result
        assert "no credentials" in result


class TestFormatCsv:
    def _rows(self, data) -> list[list[str]]:
        return list(csv.reader(io.StringIO(_format_csv(data)), delimiter=";"))

    def test_has_header_and_usage_rows(self):
        rows = self._rows(_sample_response())
        assert rows[0] == ["Bereich", "Bezeichnung", "Wert"]
        assert ["Nutzung", "Sitzungen", "40"] in rows

    def test_includes_domains_topics_and_sources(self):
        flat = [";".join(r) for r in self._rows(_sample_response())]
        assert any("Themenfeld;rente;60" in r for r in flat)
        assert any("altersrente_regel;30" in r for r in flat)
        assert any("Quelle;Merkblatt Altersrente;25" in r for r in flat)

    def test_weekly_series_is_not_exported(self):
        flat = [";".join(r) for r in self._rows(_sample_response())]
        assert not any("Wochenverlauf" in r for r in flat)

    def test_thumbs_up_rate_is_not_exported(self):
        flat = [";".join(r) for r in self._rows(_sample_response())]
        assert not any("Daumen" in r for r in flat)

    def test_feedback_totals_are_exported(self):
        flat = [";".join(r) for r in self._rows(_sample_response())]
        assert any("Feedback;Rueckmeldungen insgesamt;20" in r for r in flat)
