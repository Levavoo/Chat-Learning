"""Agent-based document search tools: read_index, list_sections, fetch_section."""

import json
import os
import re
from contextvars import ContextVar
from pathlib import Path

import boto3
from aws_lambda_powertools import Logger

from backend_orchestrator.config import get_config

logger = Logger(child=True)

_VALID_DOC_ID = re.compile(r"^[A-Za-z0-9_-]+$")

_cached_index: str | None = None
_cached_docs: dict[str, str] = {}

# Reset per invocation.
fetched_docs_context: ContextVar[list[dict] | None] = ContextVar("fetched_docs_context", default=None)

_LOCAL_INDEX_DIR = Path(__file__).resolve().parents[4] / "cdk" / "seed-data" / "agent-search-index"


def _load_from_s3(bucket: str, key: str, region: str) -> str:
    """Load a file from S3 and return its content as string."""
    client = boto3.client("s3", region_name=region)
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read().decode("utf-8")


def _load_document(doc_id: str) -> str:
    """Load raw document JSON (internal, cached)."""
    if not _VALID_DOC_ID.match(doc_id):
        return json.dumps({"error": f"Ungültige doc_id: {doc_id}"})

    if doc_id in _cached_docs:
        return _cached_docs[doc_id]

    config = get_config()
    bucket = config.agent_search_index_bucket
    prefix = config.agent_search_index_prefix

    try:
        if bucket:
            content = _load_from_s3(bucket, f"{prefix}documents/{doc_id}.json", config.aws_region)
        else:
            local_dir = os.environ.get("AGENT_SEARCH_INDEX_LOCAL_DIR", str(_LOCAL_INDEX_DIR))
            with open(Path(local_dir) / "documents" / f"{doc_id}.json") as f:
                content = f.read()
        _cached_docs[doc_id] = content
        logger.info("Document loaded", extra={"doc_id": doc_id, "source": "s3" if bucket else "local"})
    except Exception:
        logger.exception("Failed to load document", extra={"doc_id": doc_id})
        return json.dumps({"error": f"Dokument {doc_id} nicht gefunden."})

    return content


def read_index() -> str:
    """Return the full document index as JSON string."""
    global _cached_index
    if _cached_index is not None:
        return _cached_index

    config = get_config()
    bucket = config.agent_search_index_bucket
    prefix = config.agent_search_index_prefix

    try:
        if bucket:
            _cached_index = _load_from_s3(bucket, f"{prefix}index.json", config.aws_region)
        else:
            local_dir = os.environ.get("AGENT_SEARCH_INDEX_LOCAL_DIR", str(_LOCAL_INDEX_DIR))
            with open(Path(local_dir) / "index.json") as f:
                _cached_index = f.read()
        logger.info("Agent search index loaded", extra={"source": "s3" if bucket else "local"})
    except Exception:
        logger.exception("Failed to load agent search index")
        return '{"documents": []}'

    return _cached_index


def list_sections(doc_id: str) -> str:
    """List section indices and titles for a document."""
    raw = _load_document(doc_id)
    try:
        doc_data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if "error" in doc_data:
        return raw

    sections = doc_data.get("sections", [])
    result = {
        "doc_id": doc_data.get("doc_id", doc_id),
        "title": doc_data.get("title", doc_id),
        "sections": [{"index": i, "title": s.get("title", "")} for i, s in enumerate(sections)],
    }
    logger.info("Sections listed", extra={"doc_id": doc_id, "count": len(sections)})
    return json.dumps(result, ensure_ascii=False)


def fetch_section(doc_id: str, section_index: int) -> str:
    """Fetch a single section (0-based index) from a document."""
    raw = _load_document(doc_id)
    try:
        doc_data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if "error" in doc_data:
        return raw

    sections = doc_data.get("sections", [])
    if not sections:
        return json.dumps({"error": f"Dokument {doc_id} hat keine Abschnitte."})
    if section_index < 0 or section_index >= len(sections):
        return json.dumps({
            "error": f"Section {section_index} nicht gefunden in {doc_id}. Verfügbar: 0-{len(sections) - 1}"
        })

    section = sections[section_index]
    result = {
        "doc_id": doc_data.get("doc_id", doc_id),
        "title": doc_data.get("title", doc_id),
        "edition": doc_data.get("edition", ""),
        "published": doc_data.get("published", ""),
        "section_title": section.get("title", ""),
        "section_index": section_index,
        "content": section.get("content", ""),
    }

    current = fetched_docs_context.get()
    if current is None:
        current = []
        fetched_docs_context.set(current)
    current.append({
        "doc_id": result["doc_id"],
        "title": result["title"],
        "edition": result["edition"],
        "published": result["published"],
        "category": doc_data.get("category", ""),
        "brochure_url_short": doc_data.get("brochure_url_short", ""),
        "content": result["content"],
    })

    logger.info("Section fetched", extra={"doc_id": doc_id, "section_index": section_index})
    return json.dumps(result, ensure_ascii=False)
