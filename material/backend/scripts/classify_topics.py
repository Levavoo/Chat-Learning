"""Klassifiziert DynamoDB-Items ohne topic-Feld per Nova Lite (RFC-0008)."""

import argparse
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).parent.parent / "src" / "backend_orchestrator" / "data" / "topic_taxonomy.json"
_MODEL_ID = "eu.amazon.nova-lite-v1:0"
_REGION = os.getenv("AWS_REGION", "eu-central-1")
_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "renate-conversations-dev")
_MAX_RETRIES = 3
# Sort key prefix of the rows that hold a rating of the whole conversation.
_RATING_ROW_PREFIX = "RATING#"


def _load_taxonomy() -> list[dict]:
    """Load and return the topic taxonomy entries."""
    with _TAXONOMY_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data.get("topics", [])


def _build_taxonomy_ids(taxonomy: list[dict]) -> set[str]:
    """Return the set of valid topic IDs from the taxonomy."""
    return {t["id"] for t in taxonomy}


def _build_prompt(question: str, taxonomy: list[dict]) -> str:
    """Build the Nova Lite classification prompt."""
    topics_text = "\n".join(f'- "{t["id"]}": {t["label"]} — {t["description"]}' for t in taxonomy)
    return (
        "Ordne die folgende Frage genau einem der unten aufgelisteten Sub-Themen zu. "
        'Antworte NUR mit einem JSON-Objekt der Form {"topic": "<id>"} und keinem weiteren Text.\n\n'
        f"Verfuegbare Sub-Themen:\n{topics_text}\n\n"
        "Hinweise zur Zuordnung:\n"
        "- Bevorzuge immer ein spezifisches Sub-Thema, falls eines inhaltlich passt.\n"
        "- Falls die Frage eine allgemeine Dienstleistungs-, Kontakt- oder Beratungsanfrage an die DRV ist, "
        "die zu keinem der spezifischen Service-Sub-Themen passt, wähle 'service_nicht_zuordenbar'.\n"
        "- Falls die Frage themenfremd (ohne DRV-Bezug), mehrdeutig oder anderweitig nicht zuordenbar ist, "
        "wähle 'sonstiges_nicht_zuordenbar'.\n\n"
        "Beispiele:\n"
        'Frage: "Wie wird das Wetter morgen?" → {"topic": "sonstiges_nicht_zuordenbar"}\n'
        'Frage: "Wo finde ich das Formular V0800?" → {"topic": "service_nicht_zuordenbar"}\n'
        'Frage: "Kann ich mit 63 in Rente gehen?" → {"topic": "altersrente_fruehzeitig"}\n\n'
        f"Frage: {question}\n\n"
        "Antwort (nur JSON):"
    )


def _call_nova_lite(bedrock_client, prompt: str) -> str | None:
    """Call Nova Lite with exponential backoff on throttling; return raw text or None."""
    body = json.dumps({
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 50, "temperature": 0.0},
    })

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = bedrock_client.invoke_model(modelId=_MODEL_ID, body=body)
            result = json.loads(response["body"].read())
            return result["output"]["message"]["content"][0]["text"]
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ThrottlingException" and attempt < _MAX_RETRIES:
                wait = 2 ** (attempt - 1)
                logger.warning(f"ThrottlingException (attempt {attempt}/{_MAX_RETRIES}), retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.exception(f"Bedrock call failed after {attempt} attempt(s)")
                return None
        except Exception:
            logger.exception("Unexpected error calling Nova Lite")
            return None
    return None


def _parse_topic(response_text: str, valid_ids: set[str]) -> str | None:
    """Extract and validate topic ID from Nova Lite response."""
    match = re.search(r'\{[^}]*"topic"\s*:\s*"([^"]+)"[^}]*\}', response_text)
    if not match:
        logger.warning("Could not parse topic from response (no valid JSON found)")
        return None

    topic_id = match.group(1).strip()
    if topic_id not in valid_ids:
        logger.warning(f"LLM returned unknown topic '{topic_id}' — skipping item")
        return None

    return topic_id


def _scan_unclassified(table, from_ts_ms: int | None, limit: int | None) -> list[dict]:
    """Scan DynamoDB for items without a topic field."""
    from boto3.dynamodb.conditions import Attr

    filter_expr = (
        Attr("topic").not_exists()
        & Attr("blocked_by_guardrail").ne(True)
        & ~Attr("message_id").begins_with(_RATING_ROW_PREFIX)
    )
    if from_ts_ms is not None:
        filter_expr = filter_expr & Attr("created_at").gte(from_ts_ms)

    items: list[dict] = []
    kwargs: dict = {"FilterExpression": filter_expr}

    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        if limit and len(items) >= limit:
            items = items[:limit]
            break
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return items


_SKIP_PREFIXES = ("throttle-test", "waf-test", "qa-waf-")


def _classify_item(
    item: dict,
    i: int,
    total: int,
    taxonomy: list[dict],
    valid_ids: set[str],
    bedrock,
    table,
    dry_run: bool,
) -> str:
    """Classify one item and write unless dry_run. Returns 'classified' | 'skipped' | 'errors'."""
    session_id = item.get("session_id", "?")
    message_id = item.get("message_id", "?")
    question = item.get("message", "")

    if any(session_id.startswith(p) for p in _SKIP_PREFIXES):
        logger.debug(f"[{i}/{total}] Skipping test item {session_id}/{message_id}")
        return "skipped"

    if not question:
        logger.debug(f"[{i}/{total}] Skipping item {message_id} (empty message)")
        return "skipped"

    prompt = _build_prompt(question, taxonomy)
    response_text = _call_nova_lite(bedrock, prompt)

    if response_text is None:
        logger.error(f"[{i}/{total}] Nova Lite call failed for item {message_id}")
        return "errors"

    topic_id = _parse_topic(response_text, valid_ids)
    if topic_id is None:
        logger.info(f"[{i}/{total}] Skipped item {message_id} (unrecognized topic)")
        return "skipped"

    if dry_run:
        logger.info(f"[{i}/{total}] DRY RUN — would write topic='{topic_id}' to {session_id}/{message_id}")
        return "classified"

    try:
        table.update_item(
            Key={"session_id": session_id, "message_id": message_id},
            UpdateExpression="SET topic = :t",
            ConditionExpression="attribute_not_exists(topic)",
            ExpressionAttributeValues={":t": topic_id},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Classified by a concurrent run between scan and update — idempotent skip.
            logger.debug(f"[{i}/{total}] Item {message_id} already classified (race) — skipping")
            return "skipped"
        logger.exception(f"[{i}/{total}] DynamoDB update failed for {message_id}")
        return "errors"
    else:
        logger.info(f"[{i}/{total}] Classified {session_id}/{message_id} -> '{topic_id}'")
        return "classified"


def run(dry_run: bool, limit: int | None, from_date_str: str | None) -> None:
    """Classify unclassified DynamoDB items with Nova Lite sub-topics."""
    from_ts_ms: int | None = None
    if from_date_str:
        from_dt = datetime.strptime(from_date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        from_ts_ms = int(from_dt.timestamp() * 1000)

    taxonomy = _load_taxonomy()
    valid_ids = _build_taxonomy_ids(taxonomy)
    logger.info(f"Taxonomy loaded: {len(valid_ids)} topics")

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    table = dynamodb.Table(_TABLE_NAME)
    bedrock = boto3.client("bedrock-runtime", region_name=_REGION)

    logger.info(f"Scanning DynamoDB table '{_TABLE_NAME}' for unclassified items...")
    items = _scan_unclassified(table, from_ts_ms, limit)
    total = len(items)
    logger.info(f"Found {total} items without topic field")

    if total == 0:
        logger.info("Nothing to classify.")
        return

    outcomes = {"classified": 0, "skipped": 0, "errors": 0}
    for i, item in enumerate(items, 1):
        outcome = _classify_item(item, i, total, taxonomy, valid_ids, bedrock, table, dry_run)
        outcomes[outcome] += 1

    classified, skipped, errors = outcomes["classified"], outcomes["skipped"], outcomes["errors"]

    logger.info(
        f"Done. classified={classified}, skipped={skipped}, errors={errors}, total={total}"
        + (" (DRY RUN — no writes)" if dry_run else "")
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify DynamoDB conversation items with Nova Lite sub-topics.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and classify but do not write to DynamoDB")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of items to process")
    parser.add_argument(
        "--from-date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Only classify items created on or after this date",
    )
    args = parser.parse_args()

    if args.from_date:
        try:
            datetime.strptime(args.from_date, "%Y-%m-%d")
        except ValueError as e:
            parser.error(f"Invalid date format: {e}. Use YYYY-MM-DD.")

    return args


if __name__ == "__main__":
    args = _parse_args()
    run(dry_run=args.dry_run, limit=args.limit, from_date_str=args.from_date)
