r"""Exportiert Antworten, Tester-Bewertungen und zitierte Chunks einer Review-Umgebung aus DynamoDB als CSV (read-only).

Regulärer Weg ist der manuell auslösbare Pipeline-Job
``export:review-feedback:dev`` in ``renate/scheduled/evaluation`` (GitLab "Run
pipeline" auf ``main``, ``REVIEW_NAME`` setzen, Artefakt laden) — kein lokaler
AWS-Login, keine lokale Python-Umgebung nötig. Dieses Skript bleibt als lokaler
Fallback. Hintergrund: RFC 0039 (Review-Feedback-Export-Automatisierung).

Runbook: docs/runbooks/review_feedback_export.md.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend_orchestrator.repositories.conversation import RATING_DIALOG, RATING_FINAL, RATING_ROW_PREFIX

_DEFAULT_TABLE = "renate-conversations-dev"
_TIMEZONE = ZoneInfo("Europe/Berlin")
_DELIMITER = ";"
_FORMULA_START = ("=", "+", "-", "@")
_FREE_TEXT_COLUMNS = {"message", "response_text", "comment", "user_id", "source_titles", "title", "chunk_text"}
_ROW_TYPES = {RATING_DIALOG: "dialog_rating", RATING_FINAL: "final_feedback"}

_CRITERIA = [
    "comparability_to_google_ai",
    "comprehensibility",
    "coverage_level",
    "precision",
    "source_matching",
    "source_quality",
    "technical_correctivity",
    "good_to_recommend",
    "tonality",
    "dialogue_skills",
    "goal_achievement",
    "handling_corrections",
]
_HEADER = [
    "conversation_id",
    "turn",
    "row_type",
    "message_id",
    "message",
    "response_text",
    "num_sources",
    "source_titles",
    *(column for criterion in _CRITERIA for column in (criterion, f"{criterion}_score")),
    "comment",
    "producer",
    "scope",
    "schema_version",
    "used_scenario",
    "user_id",
    "created_at_cet",
]
_CHUNK_HEADER = [
    "conversation_id",
    "message_id",
    "citation_number",
    "search_rank",
    "brochure_number",
    "title",
    "document_id",
    "score",
    "chunk_text",
]

# Stored value → (label of the tester form, score). "Cannot evaluate" has no score.
_SCALE = {
    "Yes": ("Ja", 4),
    "Likely yes": ("Eher Ja", 3),
    "Probably not": ("Eher Nein", 2),
    "No": ("Nein", 1),
    "Cannot evaluate": ("Kann ich nicht bewerten", ""),
    "Better": ("Besser", 4),
    "Equally good": ("Gleich Gut", 3),
    "Equally bad": ("Gleich Schlecht", 2),
    "Worse": ("Schlechter", 1),
}


def _review_prefix(review: str) -> str:
    """Return the session_id prefix of a review environment, as in conversation.py."""
    return f"review/{review}#"


def _scan_review_rows(table: str, region: str, prefix: str) -> list[dict[str, Any]]:
    """Return all rows of the review environment."""
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=region).Table(table)
    kwargs: dict[str, Any] = {
        "FilterExpression": "begins_with(session_id, :p)",
        "ExpressionAttributeValues": {":p": prefix},
    }
    items: list[dict[str, Any]] = []
    while True:
        page = dynamodb.scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _plain(value: Any) -> Any:
    """Convert DynamoDB Decimals to int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _created_at_ms(item: dict[str, Any]) -> int:
    """Return created_at in epoch ms, 0 if missing."""
    return int(_plain(item.get("created_at")) or 0)


def _format_created_at(ms: int) -> str:
    """Format epoch ms as 'YYYY-MM-DD HH:MM:SS' in German time."""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(value: str) -> datetime:
    """Parse YYYY-MM-DD as midnight German time."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_TIMEZONE)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Ungültiges Datum '{value}', erwartet YYYY-MM-DD") from None


def _from_date_ms(value: str) -> int:
    """Return epoch ms of the start of the day, German time."""
    return int(_parse_date(value).timestamp() * 1000)


def _to_date_ms(value: str) -> int:
    """Return epoch ms of the last millisecond of the day, German time."""
    next_day = (_parse_date(value) + timedelta(days=1)).replace(tzinfo=_TIMEZONE)
    return int(next_day.timestamp() * 1000) - 1


def _is_rating_row(item: dict[str, Any]) -> bool:
    """Return True for the dialog and final feedback rows."""
    return item["message_id"].startswith(RATING_ROW_PREFIX)


def _answer_uuid(message_id: str) -> str:
    """Return the UUID part of '<session>#<uuid>'."""
    return message_id.rsplit("#", 1)[-1]


def _sorted_sources(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the cited sources of an answer in citation order."""
    sources = item.get("sources") or []
    return sorted(sources, key=lambda s: _plain(s.get("sourceIndex") or 0))


def _source_label(source: dict[str, Any]) -> str:
    """Return '<brochure number> <title>'."""
    return " ".join(part for part in (source.get("brochureNumber"), source.get("title")) if part)


def _rating_columns(feedback: dict[str, Any]) -> dict[str, Any]:
    """Return label and score columns plus the form fields of a new-format rating."""
    ratings = feedback.get("ratings", {})
    columns: dict[str, Any] = {}
    for criterion in _CRITERIA:
        value = ratings.get(criterion, "")
        label, score = _SCALE.get(value, (value, ""))
        columns[criterion] = label
        columns[f"{criterion}_score"] = score
    columns.update(
        comment=feedback.get("comment", ""),
        producer=feedback.get("producer", ""),
        scope=feedback.get("scope", ""),
        schema_version=feedback["schema_version"],
        used_scenario=_plain(feedback.get("used_scenario", "")),
        user_id=feedback.get("user_id", ""),
    )
    return columns


def _to_csv_row(item: dict[str, Any], conversation_id: str, turn: int | str) -> dict[str, Any]:
    """Flatten one DynamoDB row. Ratings in the old format leave the rating columns empty."""
    if _is_rating_row(item):
        row: dict[str, Any] = {"row_type": _ROW_TYPES.get(item["message_id"], item["message_id"])}
    else:
        sources = _sorted_sources(item)
        row = {
            "row_type": "answer",
            "message_id": _answer_uuid(item["message_id"]),
            "message": item.get("message", ""),
            "response_text": item.get("response_text", ""),
            "num_sources": len(sources),
            "source_titles": "; ".join(_source_label(s) for s in sources),
        }
    row.update(conversation_id=conversation_id, turn=turn, created_at_cet=_format_created_at(_created_at_ms(item)))

    feedback = item.get("feedback")
    if isinstance(feedback, dict) and feedback.get("schema_version"):
        row.update(_rating_columns(feedback))
    return row


def _to_chunk_rows(item: dict[str, Any], conversation_id: str) -> list[dict[str, Any]]:
    """Return one row per cited chunk of an answer."""
    return [
        {
            "conversation_id": conversation_id,
            "message_id": _answer_uuid(item["message_id"]),
            "citation_number": _plain(source.get("sourceIndex", "")),
            "search_rank": _plain(source.get("rank", "")),
            "brochure_number": source.get("brochureNumber", ""),
            "title": source.get("title", ""),
            "document_id": source.get("documentId", ""),
            "score": _plain(source.get("originalScore", "")),
            "chunk_text": source.get("content", ""),
        }
        for source in _sorted_sources(item)
    ]


def _build_rows(
    items: list[dict[str, Any]], prefix: str, from_ms: int = 0, to_ms: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Return the main rows, the chunk rows and the number of ratings in the old format.

    Rows are grouped by conversation (oldest conversation first) and sorted by time inside a conversation.
    """
    items = [
        item for item in items if from_ms <= _created_at_ms(item) and (to_ms is None or _created_at_ms(item) <= to_ms)
    ]
    conversations: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        conversations.setdefault(item["session_id"].removeprefix(prefix), []).append(item)

    rows: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    for conversation_id, conv_items in sorted(
        conversations.items(), key=lambda entry: min(_created_at_ms(i) for i in entry[1])
    ):
        turn = 0
        for item in sorted(conv_items, key=lambda i: (_is_rating_row(i), _created_at_ms(i))):
            if _is_rating_row(item):
                rows.append(_to_csv_row(item, conversation_id, ""))
                continue
            turn += 1
            rows.append(_to_csv_row(item, conversation_id, turn))
            chunks.extend(_to_chunk_rows(item, conversation_id))

    old_format = sum(
        1 for item in items if isinstance(item.get("feedback"), dict) and not item["feedback"].get("schema_version")
    )
    return rows, chunks, old_format


def _escape_formula(value: Any) -> Any:
    """Put a single quote before text that Excel would run as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return f"'{value}"
    return value


def _escape_row(row: dict[str, Any]) -> dict[str, Any]:
    """Escape all free-text cells of a row."""
    return {key: _escape_formula(value) if key in _FREE_TEXT_COLUMNS else value for key, value in row.items()}


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    """Write the CSV with semicolon delimiter and a BOM."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, restval="", delimiter=_DELIMITER)
        writer.writeheader()
        writer.writerows(_escape_row(row) for row in rows)


def _chunk_path(path: Path) -> Path:
    """Return the chunk file path next to the main file."""
    return path.with_name(f"{path.stem}-chunks{path.suffix or '.csv'}")


def _default_output(review: str) -> Path:
    """Return a timestamped file path in the home directory."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return Path.home() / f"feedback-{review}-{stamp}.csv"


def _preflight(table: str, region: str) -> str | None:
    """Return the error text if the table is not reachable."""
    import boto3

    try:
        boto3.client("dynamodb", region_name=region).describe_table(TableName=table)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Exportiert Antworten, Bewertungen und zitierte Chunks einer Review-Umgebung als CSV (read-only).",
    )
    parser.add_argument(
        "--review",
        required=True,
        help="Name der Review-Umgebung = Dateiname in deployments/review/ ohne .yml",
    )
    parser.add_argument(
        "--from-date",
        type=_from_date_ms,
        default=0,
        help="Nur Zeilen ab diesem Tag, YYYY-MM-DD, deutsche Zeit (Default: alle)",
    )
    parser.add_argument(
        "--to-date",
        type=_to_date_ms,
        default=None,
        help="Nur Zeilen bis einschließlich zu diesem Tag, YYYY-MM-DD, deutsche Zeit (Default: alle)",
    )
    parser.add_argument("--table", default=_DEFAULT_TABLE, help=f"DynamoDB-Tabelle (Default {_DEFAULT_TABLE})")
    parser.add_argument("--region", default=os.getenv("REGION", "eu-central-1"), help="AWS-Region")
    parser.add_argument("--output", help="Zieldatei (Default: ~/feedback-<review>-<Datum>.csv)")
    return parser


def main() -> int:
    """Export the rows of one review environment."""
    parser = _build_arg_parser()
    args = parser.parse_args()
    if args.to_date is not None and args.to_date < args.from_date:
        parser.error("--to-date liegt vor --from-date")

    if error := _preflight(args.table, args.region):
        print(
            "Fehler: Zugriff auf die Tabelle nicht möglich.\n"
            f"  Tabelle: {args.table}\n"
            f"  Ursache: {error}\n\n"
            "Prüfe den AWS-Login für das Dev-Konto (aws sso login --profile <Profil>).",
            file=sys.stderr,
        )
        return 3

    prefix = _review_prefix(args.review)
    rows, chunks, old_format = _build_rows(
        _scan_review_rows(args.table, args.region, prefix), prefix, args.from_date, args.to_date
    )

    if not rows:
        print(
            f"Keine Daten für Review-Umgebung '{args.review}' gefunden.\n"
            "Prüfe den Namen, --from-date und --to-date. Nach dem Abbau der Review-Umgebung sind die Daten gelöscht.",
            file=sys.stderr,
        )
        return 4

    target = Path(args.output).expanduser() if args.output else _default_output(args.review)
    _write_csv(target, _HEADER, rows)
    _write_csv(_chunk_path(target), _CHUNK_HEADER, chunks)
    rated = sum(1 for row in rows if row.get("schema_version"))
    print(f"{len(rows)} Zeilen, davon {rated} mit Bewertung, geschrieben: {target}", file=sys.stderr)
    print(f"{len(chunks)} zitierte Chunks geschrieben: {_chunk_path(target)}", file=sys.stderr)
    if old_format:
        print(f"{old_format} Bewertungen im alten Format ohne Bewertungsspalten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
