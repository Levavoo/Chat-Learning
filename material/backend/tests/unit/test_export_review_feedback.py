"""Unit tests for the export_review_feedback CLI script."""

import csv
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from backend_orchestrator.repositories.conversation import ConversationStore
from backend_orchestrator.services.feedback_rating import FORM_CRITERIA
from scripts.export_review_feedback import (
    _CHUNK_HEADER,
    _CRITERIA,
    _HEADER,
    _build_rows,
    _chunk_path,
    _from_date_ms,
    _review_prefix,
    _scan_review_rows,
    _to_date_ms,
    _write_csv,
)

PREFIX = "review/test-review-20261026#"

# 2026-11-03 10:00:00 UTC = 11:00:00 CET
T0 = 1793700000000


def _source(citation: int, rank: int, number: str, title: str) -> dict:
    return {
        "sourceIndex": Decimal(citation),
        "rank": Decimal(rank),
        "brochureNumber": number,
        "title": title,
        "documentId": f"doc-{number}",
        "originalScore": Decimal("0.5"),
        "content": f"Chunk aus {title}",
    }


def _answer(session: str, uuid: str, offset_s: int, feedback: dict | None = None) -> dict:
    item: dict[str, Any] = {
        "session_id": f"{PREFIX}{session}",
        "message_id": f"{session}#{uuid}",
        "created_at": Decimal(T0 + offset_s * 1000),
        "message": f"Frage {uuid}",
        "response_text": f"Antwort {uuid}",
        "sources": [_source(2, 3, "B26", "Freiwillig"), _source(1, 28, "B34", "Selbstständig")],
    }
    if feedback:
        item["feedback"] = feedback
    return item


def _turn_rating(value: str = "Likely yes") -> dict:
    return {
        "producer": "internal_multi_turn",
        "scope": "turn",
        "schema_version": "v2_en_4plus1",
        "ratings": {"technical_correctivity": value},
        "used_scenario": Decimal("2"),
        "user_id": "tester-1",
    }


def _dialog_row(session: str, offset_s: int) -> dict:
    return {
        "session_id": f"{PREFIX}{session}",
        "message_id": "RATING#DIALOG",
        "created_at": Decimal(T0 + offset_s * 1000),
        "feedback": {
            "producer": "internal_multi_turn",
            "scope": "dialog",
            "schema_version": "v2_en_4plus1",
            "ratings": {"goal_achievement": "No", "dialogue_skills": "Cannot evaluate"},
            "comment": "Kommentar",
            "used_scenario": Decimal("6"),
        },
    }


def test_review_prefix_matches_conversation_store(monkeypatch):
    monkeypatch.setenv("REVIEW_ID", "test-review-20261026")
    store = ConversationStore.__new__(ConversationStore)

    assert _review_prefix("test-review-20261026") == store._ns("")


def test_criteria_cover_all_form_criteria():
    form_criteria = {c for required, optional in FORM_CRITERIA.values() for c in (*required, *optional)}

    assert form_criteria <= set(_CRITERIA)


def test_build_rows_groups_by_conversation_and_numbers_turns():
    items = [
        _dialog_row("s1", 60),
        _answer("s2", "u3", 10),
        _answer("s1", "u2", 30),
        _answer("s1", "u1", 0, _turn_rating()),
    ]

    rows, _, old_format = _build_rows(items, PREFIX)

    assert old_format == 0
    assert [(r["conversation_id"], r["turn"], r["row_type"]) for r in rows] == [
        ("s1", 1, "answer"),
        ("s1", 2, "answer"),
        ("s1", "", "dialog_rating"),
        ("s2", 1, "answer"),
    ]
    assert rows[0]["message_id"] == "u1"
    assert "message_id" not in rows[2]


def test_build_rows_flattens_answer_with_labels_scores_and_sources():
    (row,), _, _ = _build_rows([_answer("s1", "u1", 0, _turn_rating())], PREFIX)

    assert row["created_at_cet"] == "2026-11-03 11:00:00"
    assert row["num_sources"] == 2
    assert row["source_titles"] == "B34 Selbstständig; B26 Freiwillig"
    assert row["technical_correctivity"] == "Eher Ja"
    assert row["technical_correctivity_score"] == 3
    assert row["used_scenario"] == 2
    assert row["goal_achievement"] == ""


def test_build_rows_leaves_score_empty_for_cannot_evaluate():
    (row,), _, _ = _build_rows([_dialog_row("s1", 0)], PREFIX)

    assert row["goal_achievement"] == "Nein"
    assert row["goal_achievement_score"] == 1
    assert row["dialogue_skills"] == "Kann ich nicht bewerten"
    assert row["dialogue_skills_score"] == ""
    assert row["comment"] == "Kommentar"


def test_build_rows_returns_one_chunk_row_per_source_in_citation_order():
    _, chunks, _ = _build_rows([_answer("s1", "u1", 0)], PREFIX)

    assert [(c["message_id"], c["citation_number"], c["search_rank"], c["brochure_number"]) for c in chunks] == [
        ("u1", 1, 28, "B34"),
        ("u1", 2, 3, "B26"),
    ]
    assert chunks[0]["chunk_text"] == "Chunk aus Selbstständig"
    assert chunks[0]["score"] == 0.5


def test_build_rows_counts_old_format_and_leaves_ratings_empty():
    (row,), _, old_format = _build_rows([_answer("s1", "u1", 0, {"helpfulness": "GOOD"})], PREFIX)

    assert old_format == 1
    assert "producer" not in row


def test_build_rows_drops_rows_before_from_date():
    items = [_answer("s1", "u1", -86400), _answer("s2", "u2", 0)]

    rows, chunks, _ = _build_rows(items, PREFIX, _from_date_ms("2026-11-03"))

    assert [r["conversation_id"] for r in rows] == ["s2"]
    assert {c["conversation_id"] for c in chunks} == {"s2"}


def test_build_rows_keeps_only_rows_inside_date_range():
    items = [_answer("s1", "u1", -86400), _answer("s2", "u2", 0), _answer("s3", "u3", 86400)]

    rows, _, _ = _build_rows(items, PREFIX, _from_date_ms("2026-11-03"), _to_date_ms("2026-11-03"))

    assert [r["conversation_id"] for r in rows] == ["s2"]


def test_to_date_includes_the_whole_day():
    assert _to_date_ms("2026-11-03") - _from_date_ms("2026-11-03") == 86400000 - 1


def test_write_csv_uses_semicolon_bom_and_escapes_formulas(tmp_path):
    answer = _answer("s1", "u1", 0)
    answer["message"] = "=HYPERLINK(1)"
    rows, chunks, _ = _build_rows([answer], PREFIX)
    target = tmp_path / "out.csv"

    _write_csv(target, _HEADER, rows)
    _write_csv(_chunk_path(target), _CHUNK_HEADER, chunks)

    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with open(target, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        parsed = next(reader)
    assert reader.fieldnames == _HEADER
    assert parsed["conversation_id"] == "s1"
    assert parsed["message"] == "'=HYPERLINK(1)"
    with open(tmp_path / "out-chunks.csv", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.DictReader(f, delimiter=";"))) == 2


def test_scan_review_rows_follows_pagination():
    table = MagicMock()
    table.scan.side_effect = [
        {"Items": [{"a": 1}], "LastEvaluatedKey": {"k": "1"}},
        {"Items": [{"a": 2}]},
    ]
    resource = MagicMock()
    resource.Table.return_value = table

    with patch("boto3.resource", return_value=resource):
        items = _scan_review_rows("tbl", "eu-central-1", PREFIX)

    assert items == [{"a": 1}, {"a": 2}]
    assert table.scan.call_args_list[0].kwargs["ExpressionAttributeValues"] == {":p": PREFIX}
    assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"k": "1"}
