"""LLM-based contextual grounding via Bedrock Converse API."""

import os
import time

import boto3

from etl.util.logging_setup import get_logger

logger = get_logger("LLM_CONTEXT")

_bedrock_client = None

SYSTEM_PROMPT = (
    "You are a helpful assistant that summarizes documents. "
    "Given a document, write a concise summary (2-4 sentences) in German.\n\n"
    "IMPORTANT: Always start with the exact document title and its specific topic area. "
    "Focus on what makes THIS document unique compared to other brochures — "
    "mention the specific benefits, conditions, or target audience it covers. "
    "Avoid generic phrases like 'Deutsche Rentenversicherung' or 'Rehabilitation' without "
    "specifying which exact type of benefit or service is discussed.\n\n"
    "Output ONLY the summary, nothing else."
)


def _get_bedrock_client():
    """Get or create cached bedrock-runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        region = os.environ.get("AWS_REGION", "eu-central-1")
        _bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return _bedrock_client


def _truncate_document(document: str, max_chars: int | None = None) -> str:
    """Truncate document to max_chars, preserving complete lines."""
    if max_chars is None:
        max_chars = int(os.environ.get("CONTEXTUAL_GROUNDING_MAX_DOC_CHARS", "50000"))
    if len(document) <= max_chars:
        return document
    truncated = document[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > 0:
        truncated = truncated[:last_newline]
    return truncated


def generate_document_summary(full_document: str) -> str | None:
    """Generate a single LLM summary for the entire document.

    Returns None on any failure so the caller can fall back to static headers.
    """
    if os.environ.get("CONTEXTUAL_GROUNDING_ENABLED", "false").lower() != "true":
        return None

    model_id = os.environ.get("CONTEXTUAL_GROUNDING_MODEL_ID", "eu.amazon.nova-pro-v1:0")
    delay_ms = int(os.environ.get("CONTEXTUAL_GROUNDING_DELAY_MS", "0"))

    truncated_doc = _truncate_document(full_document)

    user_message = f"<document>\n{truncated_doc}\n</document>"

    try:
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        client = _get_bedrock_client()
        response = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 256},
        )

        text = response["output"]["message"]["content"][0]["text"]
        return text.strip() if text.strip() else None
    except Exception:
        logger.exception("LLM context generation failed")
        return None
