"""Service for aggregating analytics data from DynamoDB."""

import json
import os
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key

from backend_orchestrator.models.api_models import (
    AnalyticsResponse,
    DomainCount,
    SourceCount,
    TopicCount,
    TopicTimeSeriesEntry,
    WeekDataPoint,
)

logger = Logger(child=True)

_DEFAULT_WINDOW_DAYS = 30

_TOPIC_TO_DOMAIN: dict[str, str] | None = None


def _load_taxonomy() -> dict[str, str]:
    """Load topic_taxonomy.json and return a topic_id -> domain mapping, cached at module level."""
    global _TOPIC_TO_DOMAIN
    if _TOPIC_TO_DOMAIN is None:
        taxonomy_path = Path(__file__).parent.parent / "data" / "topic_taxonomy.json"
        try:
            with taxonomy_path.open(encoding="utf-8") as f:
                data = json.load(f)
            _TOPIC_TO_DOMAIN = {t["id"]: t["domain"] for t in data.get("topics", [])}
        except Exception as e:
            logger.warning(f"Failed to load topic taxonomy: {e}")
            _TOPIC_TO_DOMAIN = {}
    return _TOPIC_TO_DOMAIN


class AnalyticsService:
    """Aggregate chat analytics from DynamoDB."""

    def __init__(self):
        table_name = os.getenv("DYNAMODB_TABLE_NAME", "test_feedback")
        try:
            self._table = boto3.resource("dynamodb", region_name=os.getenv("REGION", "eu-central-1")).Table(table_name)
            self._enabled = True
        except Exception:
            self._table = None
            self._enabled = False

    def get_analytics(self, from_ts: int | None = None, to_ts: int | None = None) -> AnalyticsResponse:
        """Query DynamoDB GSI and return aggregated analytics; timestamps are Unix ms."""
        now = int(time.time() * 1000)
        if from_ts is None:
            from_ts = now - _DEFAULT_WINDOW_DAYS * 86400 * 1000
        if to_ts is None:
            to_ts = now
        items = self._query_by_domains(from_ts, to_ts)
        return _aggregate(items)

    def _query_by_domains(self, from_ts: int, to_ts: int) -> list[dict[str, Any]]:
        """Query the domain-created_at GSI once per domain; items without a domain field are skipped."""
        if not self._enabled or self._table is None:
            return []

        domains = ["rente", "reha", "versicherung", "sonstiges", "themenfremd", "mehrdeutig", "blocked"]
        items: list[dict[str, Any]] = []

        try:
            for domain in domains:
                response = self._table.query(
                    IndexName="domain-created_at-index",
                    KeyConditionExpression=Key("domain").eq(domain) & Key("created_at").between(from_ts, to_ts),
                )
                items.extend(response.get("Items", []))
                while "LastEvaluatedKey" in response:
                    response = self._table.query(
                        IndexName="domain-created_at-index",
                        KeyConditionExpression=Key("domain").eq(domain) & Key("created_at").between(from_ts, to_ts),
                        ExclusiveStartKey=response["LastEvaluatedKey"],
                    )
                    items.extend(response.get("Items", []))
        except Exception as e:
            # GSI may be CREATING right after deploy (~5-10 min); dashboard shows "loading".
            logger.warning(f"Analytics GSI query failed: {type(e).__name__}: {e}")
            return []

        return items


def _count_feedback(thumbs: str) -> tuple[int, int, int, int]:
    """Return (thumbs_up, good, neutral, bad) increments for a feedback value."""
    thumbs_up = 1 if thumbs == "Ja" else 0
    good = 1 if thumbs == "GOOD" else 0
    neutral = 1 if thumbs == "NEUTRAL" else 0
    bad = 1 if thumbs == "BAD" else 0
    return thumbs_up, good, neutral, bad


def _build_topic_aggregation(
    topic_counter: Counter,
    topic_week_counter: dict[str, Counter],
) -> tuple[list[TopicCount], list[TopicTimeSeriesEntry]]:
    """Return (top_topics, topic_time_series) from the given counters."""
    taxonomy = _load_taxonomy()

    top_topics = []
    for t, c in topic_counter.most_common(15):
        domain = taxonomy.get(t)
        if domain is None:
            logger.warning(f"Topic '{t}' not found in taxonomy — defaulting domain to 'sonstiges'")
            domain = "sonstiges"
        top_topics.append(TopicCount(topic=t, domain=domain, count=c))

    top_5_topics = [t for t, _ in topic_counter.most_common(5)]
    topic_time_series = [
        TopicTimeSeriesEntry(
            topic=t,
            data_points=[
                WeekDataPoint(week_start=week, count=cnt) for week, cnt in sorted(topic_week_counter.get(t, {}).items())
            ],
        )
        for t in top_5_topics
    ]

    return top_topics, topic_time_series


def _track_topic_week(
    topic: str,
    created_at_ms: int | None,
    topic_week_counter: dict[str, Counter],
) -> None:
    """Update the week counter for a topic in-place."""
    if not created_at_ms:
        return
    item_date = date.fromtimestamp(int(created_at_ms) / 1000)
    week_start = item_date - timedelta(days=item_date.weekday())
    week_key = week_start.isoformat()
    if topic not in topic_week_counter:
        topic_week_counter[topic] = Counter()
    topic_week_counter[topic][week_key] += 1


def _aggregate(items: list[dict[str, Any]]) -> AnalyticsResponse:
    if not items:
        return AnalyticsResponse(
            total_sessions=0,
            total_messages=0,
            avg_messages_per_session=0.0,
            top_domains=[],
            top_sources=[],
            feedback_thumbs_up_rate=None,
            blocked_rate=0.0,
            feedback_good_count=0,
            feedback_neutral_count=0,
            feedback_bad_count=0,
            top_topics=[],
            topic_time_series=[],
        )

    sessions: set[str] = set()
    domain_counter: Counter = Counter()
    source_counter: Counter = Counter()
    topic_counter: Counter = Counter()
    topic_week_counter: dict[str, Counter] = {}
    thumbs_up_count = 0
    thumbs_total = 0
    blocked_count = 0
    feedback_good_count = 0
    feedback_neutral_count = 0
    feedback_bad_count = 0

    for item in items:
        if sid := item.get("session_id"):
            sessions.add(sid)

        if domain := item.get("domain"):
            domain_counter[domain] += 1

        for source in item.get("sources", []):
            if name := source.get("sourceName") or source.get("source_name"):
                source_counter[name] += 1

        feedback = item.get("feedback") or {}
        if thumbs := feedback.get("helpfulness") or feedback.get("thumbsUp") or feedback.get("thumbs_up"):
            thumbs_total += 1
            inc_up, inc_good, inc_neutral, inc_bad = _count_feedback(thumbs)
            thumbs_up_count += inc_up
            feedback_good_count += inc_good
            feedback_neutral_count += inc_neutral
            feedback_bad_count += inc_bad

        if item.get("blocked_by_guardrail"):
            blocked_count += 1

        if topic := item.get("topic"):
            topic_counter[topic] += 1
            _track_topic_week(topic, item.get("created_at"), topic_week_counter)

    total_messages = len(items)
    total_sessions = len(sessions)
    top_topics, topic_time_series = _build_topic_aggregation(topic_counter, topic_week_counter)

    return AnalyticsResponse(
        total_sessions=total_sessions,
        total_messages=total_messages,
        avg_messages_per_session=round(total_messages / total_sessions, 2) if total_sessions else 0.0,
        top_domains=[DomainCount(domain=d, count=c) for d, c in domain_counter.most_common(10)],
        top_sources=[SourceCount(source_name=s, count=c) for s, c in source_counter.most_common(10)],
        feedback_thumbs_up_rate=round(thumbs_up_count / thumbs_total, 2) if thumbs_total else None,
        blocked_rate=round(blocked_count / total_messages, 2) if total_messages else 0.0,
        feedback_good_count=feedback_good_count,
        feedback_neutral_count=feedback_neutral_count,
        feedback_bad_count=feedback_bad_count,
        top_topics=top_topics,
        topic_time_series=topic_time_series,
    )
