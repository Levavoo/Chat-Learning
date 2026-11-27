"""Contextual grounding for chunks."""

import os
from typing import Any

from etl.util.chunking.base import Chunk
from etl.util.chunking.llm_context import generate_document_summary

CONTEXT_SEPARATOR = "\n---\n"


def build_context_header(metadata: dict[str, Any]) -> str:
    """Build a contextual grounding header from chunk metadata.

    Returns an empty string if no useful metadata is available.
    """
    parts: list[str] = []

    name = metadata.get("name", "")
    if name:
        parts.append(f"**Quelle:** {name}")

    category = metadata.get("category")
    if category:
        parts.append(f"**Kategorie:** {category}")

    section = metadata.get("section_title")
    subsection = metadata.get("subsection_title")
    if section and subsection:
        parts.append(f"**Abschnitt:** {section} → {subsection}")
    elif section:
        parts.append(f"**Abschnitt:** {section}")

    if not parts:
        return ""

    return "  \n".join(parts)


def apply_contextual_grounding(chunks: list[Chunk], full_document: str = "") -> list[Chunk]:
    """Prepend contextual grounding headers to all chunks.

    Generates a single LLM document summary (one API call) and prepends it to every chunk.
    Falls back to static metadata header when LLM returns None but contextual grounding is enabled.
    Returns new Chunk instances; input chunks are not mutated.
    """
    if os.environ.get("CONTEXTUAL_GROUNDING_ENABLED", "false").lower() != "true":
        return list(chunks)

    doc_summary = generate_document_summary(full_document) if full_document else None

    result: list[Chunk] = []
    for chunk in chunks:
        if doc_summary:
            result.append(
                Chunk(
                    content=f"<!-- {doc_summary} -->" + CONTEXT_SEPARATOR + chunk.content,
                    metadata=chunk.metadata,
                )
            )
            continue

        header = build_context_header(chunk.metadata)
        if header:
            result.append(
                Chunk(
                    content=header + CONTEXT_SEPARATOR + chunk.content,
                    metadata=chunk.metadata,
                )
            )
        else:
            result.append(chunk)

    return result
