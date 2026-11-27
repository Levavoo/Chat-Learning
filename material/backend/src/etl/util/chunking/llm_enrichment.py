"""LLM-based chunk enrichment via Bedrock Converse API."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from etl.util.chunking.base import Chunk
from etl.util.chunking.llm_context import _get_bedrock_client
from etl.util.logging_setup import get_logger

logger = get_logger("LLM_ENRICHMENT")

_SYSTEM_PROMPT = (
    "Du bist ein Indexierungs-Assistent für die Deutsche Rentenversicherung.\n"
    "Analysiere den folgenden Textabschnitt und erstelle:\n\n"
    "1. section_title: Ein prägnanter Titel (5-10 Wörter) der den Inhalt beschreibt\n"
    "2. keywords: 5-10 Fachbegriffe die im Text behandelt werden\n"
    "3. colloquial_terms: 3-5 umgangssprachliche Suchphrasen, wie Bürger danach suchen würden\n\n"
    "Antworte ausschließlich als JSON:\n"
    '{"section_title": "...", "keywords": ["..."], "colloquial_terms": ["..."]}'
)

_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0
_MAX_WORKERS = 5
_TIMEOUT_RESERVE_MS = 60_000  # Abort enrichment when less than 60s remain

_deadline_ms: float = 0


def set_lambda_deadline(remaining_ms: int) -> None:
    """Set the enrichment deadline from Lambda context.get_remaining_time_in_millis()."""
    global _deadline_ms
    _deadline_ms = time.time() * 1000 + remaining_ms


def _time_remaining_ms() -> float:
    """Return ms until deadline. Returns inf if no deadline set."""
    if _deadline_ms == 0:
        return float("inf")
    return _deadline_ms - time.time() * 1000


def apply_llm_enrichment(chunks: list[Chunk]) -> list[Chunk]:
    """Enrich chunks that lack section_title/keywords with LLM-generated metadata.

    Skips chunks that already have DITA-sourced metadata. Returns chunks unmodified
    if enrichment is disabled or fails. Aborts early if Lambda timeout is approaching.
    """
    if os.environ.get("ENRICHMENT_ENABLED", "false").lower() != "true":
        return chunks

    if _time_remaining_ms() < _TIMEOUT_RESERVE_MS:
        logger.warning("Skipping enrichment — insufficient Lambda time remaining")
        return chunks

    # `keywords` is the reliable discriminator for DITA-sourced metadata: DITA
    # brochure chunks always have it, whereas the header-less paragraph fallback
    # (Merkblätter/PDFs) never does. The per-field guards in _apply_result still
    # protect any existing section_title/keywords from being overwritten.
    to_enrich = [c for c in chunks if not c.metadata.get("keywords")]
    if not to_enrich:
        return chunks

    logger.info(f"Enriching {len(to_enrich)}/{len(chunks)} chunks via LLM")

    _get_bedrock_client()
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_enrich_single_chunk, chunk): chunk for chunk in to_enrich}
        for future in as_completed(futures):
            if _time_remaining_ms() < _TIMEOUT_RESERVE_MS:
                logger.warning("Aborting enrichment mid-flight — timeout approaching")
                pool.shutdown(wait=False, cancel_futures=True)
                break
            chunk = futures[future]
            try:
                result = future.result()
                if result:
                    _apply_result(chunk, result)
            except Exception:
                logger.exception("Enrichment failed for chunk", extra={"chunk": chunk.content[:80]})

    enriched = sum(1 for c in to_enrich if c.metadata.get("section_title"))
    logger.info(f"Enrichment complete: {enriched}/{len(to_enrich)} chunks enriched")
    return chunks


def _enrich_single_chunk(chunk: Chunk) -> dict | None:
    """Call Nova Lite for a single chunk. Returns parsed result or None."""
    model_id = os.environ.get("ENRICHMENT_MODEL_ID", "eu.amazon.nova-lite-v1:0")
    client = _get_bedrock_client()

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": chunk.content}]}],
                inferenceConfig={"temperature": 0.0, "maxTokens": 256},
            )
            text = response["output"]["message"]["content"][0]["text"]
            return _parse_response(text)
        except client.exceptions.ThrottlingException:
            delay = _BACKOFF_BASE * (2**attempt)
            logger.warning(f"Throttled, retrying in {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(delay)
        except Exception:
            logger.exception("LLM enrichment call failed")
            return None
    logger.error("Max retries exceeded for chunk enrichment")
    return None


def _parse_response(text: str) -> dict | None:
    """Parse JSON from LLM response defensively."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("No JSON found in LLM response", extra={"response": text[:200]})
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LLM response", extra={"response": text[:200]})
        return None

    if not isinstance(data.get("section_title"), str):
        return None
    for field in ("keywords", "colloquial_terms"):
        if field in data and isinstance(data[field], list):
            data[field] = [item for item in data[field] if isinstance(item, str)]
    return data


def _apply_result(chunk: Chunk, result: dict) -> None:
    """Apply enrichment result to chunk metadata without overwriting existing fields."""
    if not chunk.metadata.get("section_title") and result.get("section_title"):
        chunk.metadata["section_title"] = result["section_title"]
    if not chunk.metadata.get("keywords") and isinstance(result.get("keywords"), list):
        chunk.metadata["keywords"] = ", ".join(str(k) for k in result["keywords"])
    if not chunk.metadata.get("colloquial_terms") and isinstance(result.get("colloquial_terms"), list):
        chunk.metadata["colloquial_terms"] = ", ".join(str(t) for t in result["colloquial_terms"])
    chunk.metadata["enriched"] = True
