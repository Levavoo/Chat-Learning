"""Deterministically classify malformed chunk-start fragments into cause + disposition.

Causes:
* ``stale_artifact`` (c) — the live doc predates the START fix; disposition: reprocess only.
* ``splitter_defect`` (b) — current code still begins mid-token; disposition: fix the splitter.
* ``source_truncation`` (a) — whole-section chunk char-lossy at source; disposition: source ack.
* ``permitted_continuation`` (d) — real boundary, no letters lost; disposition: ack or auto-clean.

The decisive test is char loss at a token boundary (``text_splitter.starts_mid_token``).
"""

import json
from pathlib import Path
from typing import Any

from etl.util.chunking.text_splitter import is_list_line

# --- Cause categories --------------------------------------------------------
CAUSE_SOURCE_TRUNCATION = "source_truncation"
CAUSE_SPLITTER_DEFECT = "splitter_defect"
CAUSE_STALE_ARTIFACT = "stale_artifact"
CAUSE_PERMITTED_CONTINUATION = "permitted_continuation"

DISPOSITION_SOURCE_ACK = "source_quality_acknowledgement"
DISPOSITION_FIX_SPLITTER = "fix_splitter"
DISPOSITION_REPROCESS_ONLY = "reprocess_only"
DISPOSITION_PERMITTED = "acknowledge_or_auto_joined"

# Whole-unit chunk types (not overlap sub-chunks, whose ``chunk_type`` ends in ``_split``).
WHOLE_SECTION_CHUNK_TYPES = frozenset({
    "flat_section",
    "flat_paragraph_fallback",
    "hierarchical_section",
    "hierarchical_div",
    "section_intro",
    "glossary_entry",
})

_CHUNK_START_ACK_REQUIRED_FIELDS = frozenset({"id", "source", "passage_prefix", "rationale"})


def is_split_chunk(chunk_type: str) -> bool:
    """Return whether ``chunk_type`` is an overlap sub-chunk (``*_split``)."""
    return chunk_type.endswith("_split")


def first_content_line(markdown: str) -> str:
    """Return the first non-empty line of ``markdown`` (stripped), or ""."""
    for line in markdown.splitlines():
        if line.strip():
            return line.strip()
    return ""


def is_lowercase_nonlist_start(first_line: str) -> bool:
    """Return whether ``first_line`` is a lower-case, non-list start (the review set).

    A start is flagged when its first line is neither a list item nor a
    heading/numbered-heading and its first character is a lower-case letter.
    ``str.islower`` is Unicode-aware, so German ``ä ö ü`` are covered.
    """
    stripped = first_line.lstrip()
    if not stripped or is_list_line(stripped):
        return False
    first = stripped[0]
    return first.isalpha() and first.islower()


def classify_start(
    *,
    regenerated_start_malformed: bool,
    regenerated_start_mid_token: bool,
    chunk_type: str,
    source_truncation: bool,
) -> tuple[str, str]:
    """Classify one flagged start into ``(cause, disposition)`` (deterministic).

    Args:
        regenerated_start_malformed: Whether current code still produces a lower-case
            / mid-token start for this chunk position.
        regenerated_start_mid_token: Whether the regenerated start lands mid-token
            in the pre-chunk Markdown.
        chunk_type: The chunk's ``chunk_type`` metadata.
        source_truncation: Whether a source-quality scan flags the aligned head.

    Returns:
        A ``(cause, disposition)`` pair.

    """
    # Invariant: a mid-token start is ALWAYS a splitter defect — never masked by an acknowledgement.
    if regenerated_start_mid_token:
        return CAUSE_SPLITTER_DEFECT, DISPOSITION_FIX_SPLITTER
    if not regenerated_start_malformed:
        return CAUSE_STALE_ARTIFACT, DISPOSITION_REPROCESS_ONLY
    if source_truncation and not is_split_chunk(chunk_type):
        return CAUSE_SOURCE_TRUNCATION, DISPOSITION_SOURCE_ACK
    return CAUSE_PERMITTED_CONTINUATION, DISPOSITION_PERMITTED


def load_chunk_start_acknowledgements(path: Path) -> list[dict[str, Any]]:
    """Load and validate ratified class-(d) continuations (mirrors the #680 schema)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("acknowledgements"), list):
        raise ValueError("Chunk-start acknowledgement file must have version=1 and an acknowledgements list")

    acknowledgements = payload["acknowledgements"]
    for acknowledgement in acknowledgements:
        missing = _CHUNK_START_ACK_REQUIRED_FIELDS - acknowledgement.keys()
        if missing:
            raise ValueError(f"Acknowledgement {acknowledgement.get('id', '<unknown>')} is missing: {sorted(missing)}")
    return acknowledgements


def matching_acknowledgement(
    source: str, passage: str, acknowledgements: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the acknowledgement whose source matches and whose prefix opens ``passage``."""
    for acknowledgement in acknowledgements:
        if acknowledgement.get("source") == source and passage.startswith(acknowledgement.get("passage_prefix", "\0")):
            return acknowledgement
    return None


def _is_resolved(
    finding: dict[str, Any],
    source_acknowledgements: list[dict[str, Any]],
    start_acknowledgements: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None]:
    """Decide whether a classified finding needs no further action."""
    cause = finding["cause"]
    source = finding.get("source_key", "")
    passage = finding.get("first_content_line", "")
    if cause == CAUSE_STALE_ARTIFACT:
        return True, None
    if cause == CAUSE_SPLITTER_DEFECT:
        return False, None
    if cause == CAUSE_SOURCE_TRUNCATION:
        ack = matching_acknowledgement(source, passage, source_acknowledgements)
        return ack is not None, ack
    ack = matching_acknowledgement(source, passage, start_acknowledgements)
    return ack is not None, ack


def build_classification_report(
    findings: list[dict[str, Any]],
    *,
    source_acknowledgements: list[dict[str, Any]] | None = None,
    start_acknowledgements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize classified findings, marking each resolved/unresolved.

    Every finding is retained (nothing dropped, per the acceptance criteria).
    ``unresolved`` counts remaining splitter defects and any un-acknowledged
    source-truncation / permitted-continuation findings.
    """
    source_acks = source_acknowledgements or []
    start_acks = start_acknowledgements or []

    report_findings: list[dict[str, Any]] = []
    by_cause: dict[str, int] = {}
    unresolved = 0
    for finding in findings:
        resolved, acknowledgement = _is_resolved(finding, source_acks, start_acks)
        by_cause[finding["cause"]] = by_cause.get(finding["cause"], 0) + 1
        if not resolved:
            unresolved += 1
        report_findings.append({**finding, "resolved": resolved, "acknowledgement": acknowledgement})

    return {
        "version": 1,
        "status": "failed" if unresolved else "passed",
        "summary": {
            "total": len(findings),
            "unresolved": unresolved,
            "by_cause": by_cause,
        },
        "findings": report_findings,
    }
