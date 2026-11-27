"""Service for reading the Agent-Search-Index document inventory from S3."""

import json
import time

import boto3
from aws_lambda_powertools import Logger

from backend_orchestrator.config import get_config
from backend_orchestrator.models.api_models import DocumentInventoryItem, DocumentInventoryResponse

logger = Logger(child=True)

_CACHE_TTL_SECONDS = 300  # 5 minutes

# Module-level cache: (response, expiry_timestamp)
_cached_response: DocumentInventoryResponse | None = None
_cache_expiry: float = 0.0


def get_documents() -> DocumentInventoryResponse:
    """Return the document inventory from the Agent-Search-Index; cached for 5 minutes."""
    global _cached_response, _cache_expiry

    now = time.monotonic()
    if _cached_response is not None and now < _cache_expiry:
        logger.debug("Documents inventory served from cache")
        return _cached_response

    result = _load_documents()
    _cached_response = result
    _cache_expiry = now + _CACHE_TTL_SECONDS
    return result


def _load_documents() -> DocumentInventoryResponse:
    """Load and parse index.json from S3 / local fallback."""
    config = get_config()
    bucket = config.agent_search_index_bucket
    prefix = config.agent_search_index_prefix.rstrip("/")

    raw: str | None = None
    try:
        if bucket:
            client = boto3.client("s3", region_name=config.aws_region)
            resp = client.get_object(Bucket=bucket, Key=f"{prefix}/index.json")
            raw = resp["Body"].read().decode("utf-8")
            logger.info("Document inventory loaded from S3", extra={"bucket": bucket})
        else:
            from pathlib import Path

            local_path = Path(__file__).resolve().parents[4] / "cdk" / "seed-data" / "agent-search-index" / "index.json"
            logger.info(f"Trying local document inventory path: {local_path}")
            raw = local_path.read_text(encoding="utf-8")
            logger.info("Document inventory loaded from local file")
    except Exception as e:
        logger.warning(f"Failed to load document inventory: {type(e).__name__}: {e}")
        return DocumentInventoryResponse(total_documents=0, documents=[])

    return _parse_index(raw)


def _parse_index(raw: str) -> DocumentInventoryResponse:
    """Parse raw index.json content into a DocumentInventoryResponse."""
    try:
        # Tolerate leading whitespace/BOM before the JSON object.
        start = raw.find("{")
        if start == -1:
            logger.warning("index.json does not contain a JSON object")
            return DocumentInventoryResponse(total_documents=0, documents=[])
        data = json.loads(raw[start:])
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse index.json: {e}")
        return DocumentInventoryResponse(total_documents=0, documents=[])

    raw_docs = data.get("documents", [])
    items: list[DocumentInventoryItem] = []
    for doc in raw_docs:
        try:
            sections = doc.get("sections", [])
            items.append(
                DocumentInventoryItem(
                    doc_id=doc.get("doc_id", ""),
                    title=doc.get("title", ""),
                    edition=doc.get("edition") or None,
                    published=doc.get("published") or None,
                    category=doc.get("category") or None,
                    section_count=len(sections),
                )
            )
        except Exception as e:
            logger.warning(f"Skipping malformed doc entry: {e}", extra={"doc": doc.get("doc_id", "?")})

    # Sort by category (nulls last) then title.
    items.sort(key=lambda d: (d.category or "\xff", d.title))

    return DocumentInventoryResponse(total_documents=len(items), documents=items)
