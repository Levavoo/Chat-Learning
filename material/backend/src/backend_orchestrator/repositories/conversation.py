import os
import time
from decimal import Decimal
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Attr, Key
from pydantic import ValidationError

from backend_orchestrator.config import get_config
from backend_orchestrator.models.conversation_item import ConversationItem
from backend_orchestrator.utils.session_masking import mask_message_id, mask_session_id

logger = Logger(child=True)

# DynamoDB hard item limit is 400KB; reject above _LIMIT, warn above _WARNING.
_ITEM_SIZE_WARNING_KB = 350
_ITEM_SIZE_LIMIT_KB = 380

# Cap sources before persisting; uncapped turns reached 40-120KB, risking the 400KB item cap.
_MAX_STORED_SOURCES = 8
_MAX_STORED_SOURCE_CONTENT_CHARS = 2000

_REVIEW_TTL_DAYS = 21

# Sort keys of the rows that hold a rating of the whole conversation.
RATING_ROW_PREFIX = "RATING#"
RATING_DIALOG = "RATING#DIALOG"
RATING_FINAL = "RATING#FINAL"

# Stable log marker: a failed put_item silently removes the turn from history.
_STORE_FAILURE_LOG_MESSAGE = "Conversation store put_item failed"


class HistoryReadError(Exception):
    """Reading the conversation history from DynamoDB failed."""


def _floats_to_decimals(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimals(v) for v in obj]
    return obj


def _shrink_sources_for_storage(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Cap source count and per-source content length before persisting."""
    shrunk: list[dict[str, Any]] = []
    for source in (sources or [])[:_MAX_STORED_SOURCES]:
        item = dict(source)
        content = item.get("content")
        if isinstance(content, str) and len(content) > _MAX_STORED_SOURCE_CONTENT_CHARS:
            item["content"] = content[:_MAX_STORED_SOURCE_CONTENT_CHARS] + " …[gekürzt]"
        shrunk.append(item)
    return shrunk


class ConversationStore:
    """Persist chat interactions to DynamoDB."""

    def __init__(self):
        table_name = os.getenv("DYNAMODB_TABLE_NAME", "test_feedback")
        self._table_name = table_name
        try:
            self._table = boto3.resource("dynamodb", region_name=get_config().aws_region).Table(table_name)
            self._enabled = True
        except Exception:
            logger.warning(f"DynamoDB table {table_name} not available, storage disabled")
            self._table = None
            self._enabled = False

    @staticmethod
    def _review_id() -> str:
        """Return the current REVIEW_ID env var; single source of truth for the review-env gate."""
        return os.environ.get("REVIEW_ID", "")

    def _ttl(self) -> int:
        """Return the deletion time of a new row: 21 days in review environments, else the configured days."""
        ttl_days = _REVIEW_TTL_DAYS if self._review_id() else get_config().conversation_ttl_days
        return int(time.time()) + ttl_days * 86400

    def _ns(self, session_id: str) -> str:
        review_id = self._review_id()
        return f"review/{review_id}#{session_id}" if review_id else session_id

    def _calculate_item_size(self, item: dict[str, Any]) -> int:
        """Approximate DynamoDB item size in bytes; the 20KB safety margin absorbs omitted overhead."""

        def _value_size(value: Any) -> int:
            if value is None:
                return 1
            if isinstance(value, bool):
                return 1
            if isinstance(value, str):
                return len(value.encode("utf-8"))
            if isinstance(value, (int, float, Decimal)):
                return len(str(value))
            if isinstance(value, bytes):
                return len(value)
            if isinstance(value, list):
                return sum(_value_size(v) for v in value)
            if isinstance(value, dict):
                return sum(len(k.encode("utf-8")) + _value_size(v) for k, v in value.items())
            return len(str(value).encode("utf-8"))

        return sum(len(k.encode("utf-8")) + _value_size(v) for k, v in item.items())

    def _validate_item_size(self, item: dict[str, Any], session_id: str, context: str) -> bool:
        """Check item size against DynamoDB thresholds. Returns False if item exceeds limit."""
        size = self._calculate_item_size(item)
        size_kb = size / 1024

        if size > _ITEM_SIZE_LIMIT_KB * 1024:
            field_sizes_kb = {k: round(self._calculate_item_size({k: v}) / 1024, 1) for k, v in item.items()}
            logger.error(
                "DynamoDB item validation failed: session_id %s size %.1fKB exceeds limit %dKB",
                mask_session_id(session_id),
                size_kb,
                _ITEM_SIZE_LIMIT_KB,
                extra={
                    "context": context,
                    "size_kb": round(size_kb, 1),
                    "threshold_kb": _ITEM_SIZE_LIMIT_KB,
                    "field_sizes_kb": field_sizes_kb,
                },
            )
            return False

        if size > _ITEM_SIZE_WARNING_KB * 1024:
            logger.warning(
                "DynamoDB item size warning: session_id %s size %.1fKB approaching limit %dKB",
                mask_session_id(session_id),
                size_kb,
                _ITEM_SIZE_LIMIT_KB,
                extra={
                    "context": context,
                    "size_kb": round(size_kb, 1),
                    "threshold_kb": _ITEM_SIZE_LIMIT_KB,
                },
            )

        return True

    def store_conversation(
        self,
        session_id: str,
        message: str,
        response_text: str,
        sources: list[dict[str, Any]] | None = None,
        request_time_epoch: int | None = None,
        message_id: str | None = None,
        blocked_by_guardrail: bool | None = None,
        domain: str | None = None,
        langfuse_trace_id: str | None = None,
    ) -> None:
        """Store a conversation interaction in DynamoDB."""
        if not self._enabled or self._table is None:
            logger.info("DynamoDB storage disabled, skipping conversation store")
            return
        if not message_id:
            logger.info("Missing message_id, skipping conversation store")
            return

        try:
            item = ConversationItem(
                session_id=self._ns(session_id),
                message_id=message_id,
                created_at=request_time_epoch,
                message=message,
                response_text=response_text,
                sources=_shrink_sources_for_storage(sources),
                blocked_by_guardrail=blocked_by_guardrail,
                domain=domain,
                langfuse_trace_id=langfuse_trace_id,
                ttl=self._ttl(),
            )
        except ValidationError as exc:
            logger.warning(
                "Conversation item validation failed: session_id %s message_id %s errors %s",
                mask_session_id(session_id),
                mask_message_id(message_id),
                exc.errors(),
            )
            return

        item_dict = _floats_to_decimals(item.model_dump(exclude_none=True))
        if not self._validate_item_size(item_dict, session_id, context="store_conversation"):
            return

        try:
            self._table.put_item(Item=item_dict)
        except Exception:
            logger.exception(
                _STORE_FAILURE_LOG_MESSAGE,
                extra={
                    "session_id": mask_session_id(session_id),
                    "message_id": mask_message_id(message_id),
                    "table": self._table_name,
                },
            )

    def update_feedback(
        self,
        session_id: str,
        message_id: str | None,
        feedback: dict[str, Any],
    ) -> bool:
        """Update feedback for an existing conversation item in DynamoDB."""
        if not self._enabled or self._table is None:
            logger.info("DynamoDB storage disabled, skipping feedback update")
            return False
        if not message_id:
            logger.info("Missing message_id, skipping feedback update")
            return False

        key: dict[str, Any] = {"session_id": self._ns(session_id), "message_id": message_id}

        try:
            self._table.update_item(
                Key=key,
                UpdateExpression="SET #feedback = :feedback",
                ExpressionAttributeNames={"#feedback": "feedback"},
                ExpressionAttributeValues={":feedback": feedback},
                ConditionExpression="attribute_exists(session_id) AND attribute_exists(message_id)",
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            logger.warning(
                "Feedback update skipped: item not found for session_id %s message_id %s table %s",
                mask_session_id(session_id),
                mask_message_id(message_id),
                self._table_name,
            )
            return False
        except Exception as e:
            logger.warning(
                "Failed to update feedback: session_id %s message_id %s table %s error %s",
                mask_session_id(session_id),
                mask_message_id(message_id),
                self._table_name,
                e,
            )
            return False
        else:
            return True

    def put_rating_row(self, session_id: str, sort_key: str, feedback: dict[str, Any]) -> bool:
        """Write the rating row of a conversation. A new rating replaces the old one."""
        if not self._enabled or self._table is None:
            logger.info("DynamoDB storage disabled, skipping rating row")
            return False
        item = {
            "session_id": self._ns(session_id),
            "message_id": sort_key,
            "created_at": int(time.time() * 1000),
            "ttl": self._ttl(),
            "feedback": _floats_to_decimals(feedback),
        }
        try:
            self._table.put_item(Item=item)
        except Exception as e:
            logger.warning(
                "Failed to write rating row: session_id %s sort_key %s table %s error %s",
                mask_session_id(session_id),
                sort_key,
                self._table_name,
                e,
            )
            return False
        return True

    def delete_session(self, session_id: str) -> int:
        """Delete all conversation items for a session_id. Best-effort; returns deleted count."""
        if not self._enabled or self._table is None:
            logger.info("DynamoDB storage disabled, skipping session deletion")
            return 0

        deleted = 0
        try:
            items: list[dict[str, str]] = []
            query_kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("session_id").eq(self._ns(session_id)),
                "ProjectionExpression": "session_id, message_id",
            }
            while True:
                response = self._table.query(**query_kwargs)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                query_kwargs["ExclusiveStartKey"] = last_key

            # 25 items per batch — DynamoDB limit.
            with self._table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={"session_id": item["session_id"], "message_id": item["message_id"]})
                    deleted += 1
        except Exception:
            logger.exception(
                "Session deletion failed (partial)",
                extra={"session_id": mask_session_id(session_id), "deleted_so_far": deleted},
            )

        return deleted

    def get_message(self, session_id: str, message_id: str) -> "ConversationItem | None":
        """Retrieve a single conversation item by composite key."""
        if not self._enabled or self._table is None:
            return None
        try:
            response = self._table.get_item(Key={"session_id": self._ns(session_id), "message_id": message_id})
            item = response.get("Item")
        except Exception:
            logger.exception(
                "get_message failed: session_id %s message_id %s",
                mask_session_id(session_id),
                mask_message_id(message_id),
            )
            return None

        if not item:
            return None
        try:
            validated = ConversationItem.model_validate(item)
        except ValidationError as e:
            logger.warning(
                "Invalid conversation item in get_message",
                extra={"error": str(e), "message_id": mask_message_id(message_id)},
            )
            return None
        # DynamoDB deletes expired items within ~48h; filter on read for exact cutoff.
        if validated.ttl is not None and validated.ttl <= int(time.time()):
            return None
        return validated

    def get_history(self, session_id: str, limit: int = 50) -> list[ConversationItem]:
        """Retrieve conversation history sorted by created_at ascending, trimmed to `limit`.

        Raises HistoryReadError if any query page fails. A partial history would undercount
        the conversation and let a request past the message limit (#992), so callers fail closed.
        """
        if not self._enabled or self._table is None:
            return []

        # Paginate fully: a 1MB query page could drop arbitrary turns (message_id is a random UUID),
        # and sorting by created_at only works on the complete set.
        items: list[dict[str, Any]] = []
        now = int(time.time())
        query_kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("session_id").eq(self._ns(session_id)),
            # FilterExpression saves transfer/CPU but still consumes RCU for filtered-out items.
            # not_exists() keeps legacy items (written before TTL was added) visible.
            "FilterExpression": Attr("ttl").not_exists() | Attr("ttl").gt(now),
        }
        try:
            while True:
                response = self._table.query(**query_kwargs)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                query_kwargs["ExclusiveStartKey"] = last_key
        except Exception as e:
            logger.warning(
                "get_history failed: %s",
                mask_session_id(session_id),
                extra={"error": str(e), "fetched": len(items), "table": self._table_name},
            )
            raise HistoryReadError("conversation history could not be read") from e

        validated: list[ConversationItem] = []
        for raw in items:
            if str((raw or {}).get("message_id", "")).startswith(RATING_ROW_PREFIX):
                continue
            try:
                item = ConversationItem.model_validate(raw)
            except ValidationError as e:
                # One bad row must not wipe the whole session history.
                logger.warning(
                    "Skipping invalid conversation item",
                    extra={"error": str(e), "message_id": mask_message_id((raw or {}).get("message_id"))},
                )
                continue
            # Backstop against clock skew / future callers bypassing the FilterExpression.
            if item.ttl is not None and item.ttl <= now:
                continue
            validated.append(item)
        validated.sort(key=lambda x: x.created_at or 0)
        return validated[-limit:] if len(validated) > limit else validated
