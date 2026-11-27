"""Agent response parsing utilities."""

import json
import re
from typing import Any

from aws_lambda_powertools import Logger

from backend_orchestrator.models import (
    ChatOutput,
    ChatOutputMessage,
    MessageChunk,
    MessageContent,
)

logger = Logger(child=True)


def extract_cited_indices(text: str) -> set[int]:
    """Extract [1], [2], [3] citation indices from response text."""
    pattern = r"\[(\d+)\]"
    matches = re.findall(pattern, text)
    return {int(m) for m in matches}


def filter_sources_by_citations(sources: list[dict], response_text: str) -> list[dict]:
    """Filter sources to only those cited (by sourceIndex) in the response."""
    cited_indices = extract_cited_indices(response_text)

    if not cited_indices:
        logger.info("No citations found in response, returning empty sources")
        return []

    filtered = [s for s in sources if s.get("sourceIndex") in cited_indices]
    logger.info(
        "Filtered sources by citations",
        extra={"total": len(sources), "cited": len(filtered), "indices": list(cited_indices)},
    )
    return filtered


_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_UNICODE_HYPHEN_TABLE = str.maketrans({
    "­": "",
    "‐": "-",  # noqa: RUF001
    "‑": "-",  # noqa: RUF001
    "‒": "-",  # noqa: RUF001
    "–": "-",  # noqa: RUF001
})


def sanitize_urls(text: str) -> str:
    """Strip soft hyphens everywhere; normalize other Unicode hyphens inside URLs only."""
    text = text.replace("­", "")
    return _URL_RE.sub(lambda m: m.group(0).translate(_UNICODE_HYPHEN_TABLE), text)


def unescape_literal_whitespace(text: str) -> str:
    r"""Convert literal ``\n``/``\r``/``\t`` escape sequences into real whitespace.

    gpt-oss and similar JSON-mode models double-escape control characters, so after json.loads
    the two-character sequences remain and render as visible ``\n`` in the UI.
    """
    if "\\n" not in text and "\\r" not in text and "\\t" not in text:
        return text
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n").replace("\\t", "\t")


def parse_agent_response(response_text: str) -> tuple[str, list[dict] | None]:
    """Parse agent JSON response and return (text, related_documents)."""
    try:
        response_data = json.loads(response_text)
        if isinstance(response_data, dict):
            related_documents = response_data.get("relatedDocuments")

            if "result" in response_data:
                result = response_data["result"]
                if isinstance(result, dict) and "content" in result:
                    content_list = result["content"]
                    if isinstance(content_list, list) and content_list:
                        first_content = content_list[0]
                        if isinstance(first_content, dict) and "text" in first_content:
                            return first_content["text"], related_documents
                elif isinstance(result, str):
                    return result, related_documents

    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.warning("Failed to parse agent response JSON", extra={"error": str(e)})

    return response_text, None


def build_chat_response(
    session_id: str,
    response_text: str,
    used_chunks: list[Any],
    request_time_epoch: int | None,
    message_id: str | None = None,
    trace_id: str | None = None,
    all_sources: list[Any] | None = None,
    root_span_id: str | None = None,
    eval_mode: bool = False,
) -> dict[str, Any]:
    """Build standardized chat response via ChatOutput.

    When eval_mode is false (every normal caller), eval-only fields (all_sources, sectionTitle,
    domainTier, rootSpanId) are stripped so the public payload is byte-identical to pre-eval shape.
    """
    response_text = sanitize_urls(response_text)
    typed_chunks: list[MessageChunk] | None = None
    if used_chunks:
        typed_chunks = [MessageChunk.model_validate(c) for c in used_chunks]
    typed_all_sources: list[MessageChunk] | None = None
    if eval_mode and all_sources:
        typed_all_sources = [MessageChunk.model_validate(c) for c in all_sources]

    message = ChatOutputMessage(
        role="assistant",
        content=[MessageContent(content_type="text", body=response_text)],
        feedback=None,
        used_chunks=typed_chunks,
        all_sources=typed_all_sources,
        root_span_id=root_span_id if eval_mode else None,
        parent=str(request_time_epoch) if request_time_epoch else session_id,
        message_id=message_id,
    )

    response = ChatOutput(
        conversation_id=session_id,
        message=message,
        create_time=int(request_time_epoch / 1000) if request_time_epoch else 0,
        trace_id=trace_id,
    )

    dumped = response.model_dump(by_alias=True)
    # Normal callers get the pre-eval-mode shape; the frontend parses against a strict schema.
    if not eval_mode:
        dumped["message"].pop("allSources", None)
        dumped["message"].pop("rootSpanId", None)
        for chunk in dumped["message"].get("usedChunks") or []:
            chunk.pop("sectionTitle", None)
            chunk.pop("domainTier", None)
    return dumped
