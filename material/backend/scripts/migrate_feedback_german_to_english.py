"""One-shot migration: rewrite historic German feedback ratings to English in-place.

Likert values map Ja/Nein/Teilweise -> Yes/No/Likely yes; comparability maps
Besser/Schlechter/Gleich -> Better/Worse/Equally good. Ambiguous German values
(Teilweise, Gleich) use the optimistic reading and get a
``feedback.migrated_from_de`` marker so they can be isolated later.

``Weiß nicht`` is NOT mapped — the mapping is unknown; the script refuses to
apply while any field still carries it, so silent data loss is impossible.

Writes are CAS-gated per touched field (``feedback.<field> = :old_<field>``) so
a late re-apply of a stale German value cannot undo the migration. Idempotent.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_feedback_de")


_LIKERT_MAP: dict[str, str] = {
    "Ja": "Yes",
    "Nein": "No",
    "Teilweise": "Likely yes",  # optimistic reading of ambiguous German
}

_COMPARABILITY_MAP: dict[str, str] = {
    "Besser": "Better",
    "Schlechter": "Worse",
    "Gleich": "Equally good",  # optimistic reading of ambiguous German
}

_LIKERT_FIELDS: tuple[str, ...] = (
    "technical_correctivity",
    "coverage_level",
    "comprehensibility",
    "precision",
    "tonality",
    "utility_value",
    "source_matching",
    "source_quality",
    "goal_achievement",
    "dialogue_skills",
    "handling_corrections",
    "further_development",
    "good_to_recommend",
    "helpfulness",
)

_COMPARABILITY_FIELDS: tuple[str, ...] = ("comparability_to_google_ai",)

# Halt token: refuse to migrate while any field anywhere still carries this.
_WEISS_NICHT = "Weiß nicht"


def _build_filter_expression():
    """OR together ``Attr("feedback.<field>").is_in([...])`` across all affected fields.

    Includes ``Weiß nicht`` so the halt-check sees it.
    """
    german_likert = [*_LIKERT_MAP, _WEISS_NICHT]
    german_comparability = [*_COMPARABILITY_MAP, _WEISS_NICHT]

    expr = None
    for field in _LIKERT_FIELDS:
        clause = Attr(f"feedback.{field}").is_in(german_likert)
        expr = clause if expr is None else expr | clause
    for field in _COMPARABILITY_FIELDS:
        clause = Attr(f"feedback.{field}").is_in(german_comparability)
        expr = clause if expr is None else expr | clause
    return expr


def _scan_rows_with_german_values(table) -> list[dict[str, Any]]:
    """Return every row with at least one German rating (paginated scan)."""
    rows: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "FilterExpression": _build_filter_expression(),
        "ProjectionExpression": "session_id, message_id, feedback",
    }
    while True:
        resp = table.scan(**kwargs)
        rows.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return rows


def _plan_row_rewrites(feedback: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Return ``{field: (old_de, new_en)}`` for every German value on the row (never Weiß nicht)."""
    plan: dict[str, tuple[str, str]] = {}
    for field in _LIKERT_FIELDS:
        value = feedback.get(field)
        if isinstance(value, str) and value in _LIKERT_MAP:
            plan[field] = (value, _LIKERT_MAP[value])
    for field in _COMPARABILITY_FIELDS:
        value = feedback.get(field)
        if isinstance(value, str) and value in _COMPARABILITY_MAP:
            plan[field] = (value, _COMPARABILITY_MAP[value])
    return plan


def _collect_weiss_nicht(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count ``Weiß nicht`` occurrences per field."""
    counts: dict[str, int] = {}
    for row in rows:
        feedback = row.get("feedback") or {}
        for field in _LIKERT_FIELDS + _COMPARABILITY_FIELDS:
            if feedback.get(field) == _WEISS_NICHT:
                counts[field] = counts.get(field, 0) + 1
    return counts


def _migrate_row(table, row: dict[str, Any], dry_run: bool) -> str:
    """Rewrite one row. Returns 'moved' | 'skipped' | 'raced' | 'invalid' | 'error'."""
    feedback = row.get("feedback") or {}
    key = {"session_id": row["session_id"], "message_id": row["message_id"]}

    plan = _plan_row_rewrites(feedback)
    if not plan:
        return "skipped"

    # Route every attribute path through ExpressionAttributeNames so DynamoDB
    # reserved keywords (e.g. `precision`) don't trip ValidationException.
    set_parts: list[str] = []
    expr_values: dict[str, Any] = {}
    expr_names: dict[str, str] = {"#feedback": "feedback", "#marker": "migrated_from_de"}
    condition_parts: list[str] = []
    marker: dict[str, str] = {}

    for field, (old_de, new_en) in plan.items():
        name_placeholder = f"#f_{field}"
        expr_names[name_placeholder] = field
        set_parts.append(f"#feedback.{name_placeholder} = :new_{field}")
        expr_values[f":new_{field}"] = new_en
        expr_values[f":old_{field}"] = old_de
        condition_parts.append(f"#feedback.{name_placeholder} = :old_{field}")
        marker[field] = old_de

    set_parts.append("#feedback.#marker = :marker")
    expr_values[":marker"] = marker

    update_expr = "SET " + ", ".join(set_parts)
    condition = " AND ".join(condition_parts)

    if dry_run:
        logger.info(
            "[dry-run] moved session=%s message=%s rewrites=%s",
            row["session_id"],
            row["message_id"],
            {f: f"{old} -> {new}" for f, (old, new) in plan.items()},
        )
        return "moved"

    try:
        table.update_item(
            Key=key,
            UpdateExpression=update_expr,
            ConditionExpression=condition,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        if code == "ConditionalCheckFailedException":
            return "raced"
        logger.exception(
            "update_item failed session=%s message=%s error=%s",
            row["session_id"],
            row["message_id"],
            code,
        )
        return "error"
    return "moved"


def run(dry_run: bool) -> int:
    """Scan the configured table, halt on Weiß nicht, rewrite every German value in place."""
    table_name = os.environ.get("DYNAMODB_TABLE_NAME")
    if not table_name:
        logger.error("DYNAMODB_TABLE_NAME env var is required")
        return 2

    region = os.environ.get("AWS_REGION", "eu-central-1")
    boto_config = Config(retries={"max_attempts": 10, "mode": "adaptive"})
    table = boto3.resource("dynamodb", region_name=region, config=boto_config).Table(table_name)

    logger.info("Scanning table %s in %s (dry_run=%s)", table_name, region, dry_run)
    started = time.monotonic()
    rows = _scan_rows_with_german_values(table)
    logger.info("Found %d rows with at least one German or Weiß nicht value", len(rows))

    weiss_nicht_counts = _collect_weiss_nicht(rows)
    if weiss_nicht_counts:
        logger.error(
            "Found Weiß nicht values with no English mapping: %s",
            weiss_nicht_counts,
        )
        if not dry_run:
            logger.error("Refusing to apply — resolve Weiß nicht manually before re-running.")
            return 3
        logger.warning(
            "[dry-run] continuing report; apply would refuse to proceed until Weiß nicht is resolved.",
        )

    counts = {"moved": 0, "skipped": 0, "raced": 0, "invalid": 0, "error": 0}
    for row in rows:
        counts[_migrate_row(table, row, dry_run)] += 1

    elapsed = time.monotonic() - started
    logger.info(
        "Done in %.1fs — moved=%d skipped=%d raced=%d invalid=%d error=%d",
        elapsed,
        counts["moved"],
        counts["skipped"],
        counts["raced"],
        counts["invalid"],
        counts["error"],
    )
    return 1 if counts["error"] else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Log planned writes, write nothing.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run(dry_run=args.dry_run))
